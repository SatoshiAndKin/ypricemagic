"""Historical pricing regressions with production adapters and controlled RPCs."""

import asyncio
import importlib
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from eth_abi.packed import encode_packed
from eth_typing import BlockNumber, ChecksumAddress
from y.prices._rpc import BlockRef
from multicall import Call
from web3.exceptions import ContractLogicError

from tests.test_amount_quotes import BLOCK, CHILD, TOKEN, USD
from tests.test_pricing_correctness import Ready, instance, run_async_test
from y.constants import EEE_ADDRESS
from y.datatypes import QuoteAsset
from y.prices import _markets
from y.prices._markets import Market


@run_async_test
async def test_historical_guni_bucket_uses_production_collector(monkeypatch: Any) -> None:
    from y.prices.utils import buckets
    from y.prices.tokenized_fund import gelato
    import y._db.utils.token as db

    monkeypatch.setattr(db, "get_bucket", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "set_bucket", lambda *a: None)
    monkeypatch.setattr(buckets, "string_matchers", {})
    monkeypatch.setattr(buckets, "calls_only", {"gelato": gelato.is_gelato_pool})

    async def response(self: Any, *a: Any, **kw: Any) -> Any:
        assert self.block_id == BLOCK.number
        assert self.signature.signature == "getUnderlyingBalances()(uint256,uint256)"
        return (33513541671, 70242472545)

    monkeypatch.setattr(Call, "coroutine", response)
    assert (
        await buckets.check_bucket(
            "0x000000000000000000000000000000000000beef", block=BLOCK.number, sync=False
        )
        == "gelato"
    )


@run_async_test
@pytest.mark.parametrize("available", [True, False])
async def test_v1_native_discovery_and_exclusions(monkeypatch: Any, available: bool) -> None:
    from dank_mids import brownie_patch
    from y import constants
    from y.prices.dex.uniswap import uniswap_multiplexer
    from y.prices import _routing

    eth = EEE_ADDRESS.lower()
    monkeypatch.setattr(constants, "usdc", USD)
    monkeypatch.setattr(uniswap_multiplexer, "v1", SimpleNamespace(factory=TOKEN))
    deployed = AsyncMock(return_value=available)
    monkeypatch.setattr(_markets, "deployed", deployed)
    exchange = AsyncMock(return_value=CHILD)
    monkeypatch.setattr(_markets, "optional_read", exchange)
    balance = AsyncMock(return_value=10**20)
    monkeypatch.setattr(
        brownie_patch, "dank_web3", SimpleNamespace(eth=SimpleNamespace(get_balance=balance))
    )
    result = await _markets.discover(eth, BLOCK)
    expected = (Market("Uniswap V1", CHILD, (eth, USD), (10**20, 0)),) if available else ()
    assert result == expected
    if available:
        exchange.assert_awaited_once_with(TOKEN, "getExchange(address)(address)", BLOCK, USD)
        balance.assert_awaited_once_with(CHILD, BLOCK.identifier)
        service = _routing.QuoteService()
        monkeypatch.setattr(_routing, "discover", AsyncMock(return_value=result))
        swap = AsyncMock(side_effect=AssertionError("excluded exchange must not be used"))
        monkeypatch.setattr(_routing, "swap", swap)
        monkeypatch.setattr(service, "redeem", AsyncMock(return_value=None))
        monkeypatch.setattr(service, "explicit", AsyncMock(return_value=None))
        monkeypatch.setattr(service, "usd", AsyncMock(return_value=None))
        monkeypatch.setattr(BlockRef, "verify", AsyncMock())
        assert await service.price(eth, BLOCK, 1, ignored=frozenset({CHILD})) is None
        swap.assert_not_awaited()
    else:
        exchange.assert_not_awaited()
        balance.assert_not_awaited()
    assert await _markets.discover(eth, BLOCK, ("Uniswap V3",)) == ()


@run_async_test
@pytest.mark.parametrize("viable", [True, False])
async def test_partial_fill_falls_back_to_later_pool(monkeypatch: Any, viable: bool) -> None:
    from tests.test_amount_quotes import graph
    from y.prices import _routing

    module = importlib.import_module("y.prices.dex.uniswap.v3")
    pools = [
        Market("Uniswap V3", name, (TOKEN, USD), (depth, depth), name, 3000)
        for name, depth in (("deep", 2 * 10**9), ("later", 10**9))
    ]
    service, _, _ = graph(monkeypatch, pools)
    monkeypatch.setattr(_routing, "swap", _markets.swap)
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=6))
    calls = []

    async def load(pool: str) -> Any:
        calls.append(pool)
        return SimpleNamespace(
            quoteExactInput=SimpleNamespace(
                coroutine=AsyncMock(return_value=42 if pool == "deep" else 997000)
            ),
            quoteExactOutput=SimpleNamespace(
                coroutine=AsyncMock(
                    return_value=1000001,
                    side_effect=(
                        ContractLogicError("execution reverted")
                        if pool == "deep" or not viable
                        else None
                    ),
                )
            ),
        )

    monkeypatch.setattr(module, "load_quoter", load)
    result = await service.price(TOKEN, BLOCK, 1)
    if viable:
        assert result is not None and result.quote is not None
        assert result.quote.outputs == (QuoteAsset(USD, 997000, 6),)
        assert result.quote.total_usd == Decimal("0.997")
        assert [step.contract for step in result.quote.steps] == ["later"]
    else:
        assert result is None
    assert calls == ["deep", "later"]
    if not viable:
        from y.prices import magic
        from y.exceptions import yPriceMagicError

        monkeypatch.setattr(_routing, "quote_service", lambda: service)
        monkeypatch.setattr(BlockRef, "resolve", AsyncMock(return_value=BLOCK))
        monkeypatch.setattr(magic, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("TEST")))
        assert (
            await cast(Any, magic.get_price)(
                TOKEN, BLOCK.number, amount=1, fail_to_None=True, skip_cache=True, sync=False
            )
            is None
        )
        with pytest.raises(yPriceMagicError):
            await cast(Any, magic.get_price)(
                TOKEN, BLOCK.number, amount=1, skip_cache=True, sync=False
            )


@run_async_test
@pytest.mark.parametrize("viable,fail_soft", [(True, True), (False, True), (False, False)])
async def test_missing_child_uses_parent_fallback(
    monkeypatch: Any, viable: bool, fail_soft: bool
) -> None:
    from y.prices import magic, utils
    from y.exceptions import NonStandardERC20, yPriceMagicError

    monkeypatch.setattr(magic, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("TEST")))
    monkeypatch.setattr(magic, "_get_price_from_api", AsyncMock(return_value=None))
    error = yPriceMagicError(
        NonStandardERC20(CHILD), cast(ChecksumAddress, CHILD), BlockNumber(BLOCK.number), "CHILD"
    )
    monkeypatch.setattr(magic, "_exit_early_for_known_tokens", AsyncMock(side_effect=error))
    dex = AsyncMock(return_value=(7 if viable else None, "fallback"))
    monkeypatch.setattr(magic, "_get_price_from_dexes", dex)
    monkeypatch.setattr(utils, "sense_check", AsyncMock())
    if not viable and not fail_soft:
        with pytest.raises(yPriceMagicError):
            await cast(Any, magic.get_price)(TOKEN, BLOCK.number, skip_cache=True, sync=False)
    else:
        result = await cast(Any, magic.get_price)(
            TOKEN, BLOCK.number, fail_to_None=fail_soft, skip_cache=True, sync=False
        )
        assert (float(result) if result is not None else None) == (7 if viable else None)
    dex.assert_awaited_once()


@run_async_test
@pytest.mark.parametrize(
    "error", [RuntimeError("RPC failure"), TypeError("bad result"), asyncio.CancelledError()]
)
async def test_child_unexpected_failure_propagates(monkeypatch: Any, error: BaseException) -> None:
    from y.prices import magic

    monkeypatch.setattr(magic, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("TEST")))
    monkeypatch.setattr(magic, "_get_price_from_api", AsyncMock(return_value=None))
    monkeypatch.setattr(magic, "_exit_early_for_known_tokens", AsyncMock(side_effect=error))
    with pytest.raises(type(error), match=str(error)):
        await cast(Any, magic.get_price)(
            TOKEN, BLOCK.number, skip_cache=True, fail_to_None=True, sync=False
        )


@run_async_test
async def test_stable_synth_uses_historical_oracle(monkeypatch: Any) -> None:
    from y.prices import magic, utils

    monkeypatch.setattr(magic, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("sUSD")))
    monkeypatch.setattr(magic, "_get_price_from_api", AsyncMock(return_value=None))
    monkeypatch.setattr(utils, "check_bucket", AsyncMock(return_value="stable usd"))
    monkeypatch.setattr(magic, "chainlink", SimpleNamespace(get_price=AsyncMock(return_value=None)))
    synth = AsyncMock(return_value=1)
    monkeypatch.setattr(magic, "synthetix", SimpleNamespace(get_price=synth))
    monkeypatch.setattr(magic, "_get_price_from_dexes", AsyncMock(return_value=(None, None)))
    result = await cast(Any, magic.get_price)(
        TOKEN, BLOCK.number, skip_cache=True, fail_to_None=True, sync=False
    )
    assert result is not None and float(result) == 1
    synth.assert_awaited_once_with(TOKEN, BLOCK.number, sync=False)


@run_async_test
@pytest.mark.parametrize("missing", [True, False])
async def test_optional_sense_check_metadata(monkeypatch: Any, missing: bool) -> None:
    module = importlib.import_module("y.prices.utils.sense_check")
    from y.exceptions import CantFetchParam

    monkeypatch.setattr(module, "check_bucket", AsyncMock(return_value="yearn or yearn-like"))

    class Vault:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        @property
        async def underlying(self) -> Any:
            raise CantFetchParam("unknown asset") if missing else RuntimeError("RPC failure")

    monkeypatch.setattr(module, "YearnInspiredVault", Vault)
    monkeypatch.setattr(module, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("TEST")))
    observed: tuple[str, str] | None
    # mypyc exceptions can lack line metadata in this pytest version. Capture
    # the outcome before asserting so a regression remains a reported failure.
    try:
        await module.sense_check(TOKEN, BLOCK.number, 1001)
    except Exception as exc:
        observed = (type(exc).__name__, str(exc))
    else:
        observed = None
    assert observed == (None if missing else ("RuntimeError", "RPC failure"))


@run_async_test
@pytest.mark.parametrize("representation", ["web3", "web3_context", "brownie"])
@pytest.mark.parametrize(
    "reason",
    [
        "Feed not found",
        "grace period not over",
        "Chainlink feeds are not being updated",
        "token config not found",
        "no price",
        "invalid resilient oracle price",
    ],
)
async def test_compound_feed_reverts_are_unavailable(
    monkeypatch: Any, reason: str, representation: str
) -> None:
    module = importlib.import_module("y.prices.lending.compound")
    token = module.CToken(TOKEN, asynchronous=True)
    calls = []

    async def response(self: Any, *args: Any, **kwargs: Any) -> Any:
        signature = self.signature.signature
        calls.append((signature, self.block_id))
        if signature == "comptroller()(address)":
            return CHILD
        if signature == "oracle()(address)":
            return USD
        if signature == "getUnderlyingPrice(address)(uint256)":
            if representation == "brownie":
                from brownie.exceptions import VirtualMachineError
                from eth_abi.abi import encode

                raise VirtualMachineError(
                    ValueError(
                        {
                            "message": f"execution reverted: {reason}",
                            "data": "0x08c379a0" + encode(["string"], [reason]).hex(),
                        }
                    )
                )
            error = ContractLogicError(f"execution reverted: {reason}")
            if representation == "web3_context":
                error.args += ("RPC request context",)
            raise error
        raise AssertionError(signature)

    monkeypatch.setattr(Call, "coroutine", response)
    assert await token.get_underlying_price(BLOCK.number, sync=False) is None
    assert calls == [
        (method, BLOCK.number)
        for method in (
            "comptroller()(address)",
            "oracle()(address)",
            "getUnderlyingPrice(address)(uint256)",
        )
    ]


@run_async_test
@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("state missing"),
        TypeError("bad decode"),
        TypeError("execution reverted: Feed not found"),
        ContractLogicError("execution reverted: unknown"),
        asyncio.CancelledError(),
    ],
)
async def test_compound_unexpected_oracle_failure_propagates(
    monkeypatch: Any, error: BaseException
) -> None:
    module = importlib.import_module("y.prices.lending.compound")
    token = module.CToken(TOKEN, asynchronous=True)

    async def response(self: Any, *args: Any, **kwargs: Any) -> Any:
        if self.signature.signature == "getUnderlyingPrice(address)(uint256)":
            raise error
        return CHILD

    monkeypatch.setattr(Call, "coroutine", response)
    with pytest.raises(type(error), match=str(error)):
        await token.get_underlying_price(BLOCK.number, sync=False)


@run_async_test
@pytest.mark.parametrize(
    "known_oracle,retired,exception_type",
    [
        (True, True, ContractLogicError),
        (True, False, ContractLogicError),
        (False, True, ContractLogicError),
        (True, True, TypeError),
    ],
)
async def test_compound_blank_revert_requires_verified_retired_feed(
    monkeypatch: Any, known_oracle: bool, retired: bool, exception_type: Any
) -> None:
    from brownie import ZERO_ADDRESS

    module = importlib.import_module("y.prices.lending.compound")
    token = module.CToken(TOKEN, asynchronous=True)
    calls = []

    async def response(self: Any, *args: Any, **kwargs: Any) -> Any:
        signature = self.signature.signature
        calls.append(signature)
        assert self.block_id == BLOCK.number
        if signature == "comptroller()(address)":
            return CHILD
        if signature == "oracle()(address)":
            return "0xe8929afd47064efd36a7fb51da3f8c5eb40c4cb4" if known_oracle else CHILD
        if signature == "getUnderlyingPrice(address)(uint256)":
            raise exception_type("execution reverted")
        if signature == "feeds(address)(address,uint8)":
            return (USD, 9)
        if signature == "aggregator()(address)":
            return ZERO_ADDRESS if retired else TOKEN
        raise AssertionError(signature)

    monkeypatch.setattr(Call, "coroutine", response)
    if known_oracle and retired and exception_type is ContractLogicError:
        assert await token.get_underlying_price(BLOCK.number, sync=False) is None
    else:
        with pytest.raises(exception_type, match="execution reverted"):
            await token.get_underlying_price(BLOCK.number, sync=False)
    assert ("aggregator()(address)" in calls) == (
        known_oracle and exception_type is ContractLogicError
    )


@run_async_test
@pytest.mark.parametrize("legacy,expected", [(False, 2), (True, 4000)])
async def test_compound_oracle_denomination(monkeypatch: Any, legacy: bool, expected: int) -> None:
    module = importlib.import_module("y.prices.lending.compound")
    token = module.CToken(TOKEN, asynchronous=True)
    oracle = "0x4b7dba23bea9d1a2d652373bcd1b78b0e9e0188a" if legacy else USD

    async def response(self: Any, *args: Any, **kwargs: Any) -> Any:
        assert self.block_id == BLOCK.number
        return {
            "comptroller()(address)": CHILD,
            "oracle()(address)": oracle,
            "getUnderlyingPrice(address)(uint256)": 2 * 10**30,
        }[self.signature.signature]

    monkeypatch.setattr(Call, "coroutine", response)
    monkeypatch.setattr(
        module.CToken,
        "__underlying__",
        property(lambda self: Ready(SimpleNamespace(__decimals__=Ready(6)))),
    )
    eth_price = AsyncMock(return_value=2000)
    monkeypatch.setattr(module, "ERC20", lambda *args, **kw: SimpleNamespace(price=eth_price))
    assert await token.get_underlying_price(BLOCK.number, skip_cache=True, sync=False) == expected
    assert eth_price.await_count == int(legacy)
    if legacy:
        eth_price.assert_awaited_once_with(
            block=BLOCK.number, skip_cache=True, return_None_on_failure=True, asynchronous=True
        )


@run_async_test
async def test_compound_unavailable_exchange_rate(monkeypatch: Any) -> None:
    module = importlib.import_module("y.prices.lending.compound")
    token = module.CToken(TOKEN, asynchronous=True)
    monkeypatch.setattr(
        module.CToken,
        "underlying_per_ctoken",
        AsyncMock(side_effect=ContractLogicError("execution reverted: subtraction underflow")),
    )
    oracle = AsyncMock(side_effect=AssertionError("cannot value unavailable shares"))
    monkeypatch.setattr(module.CToken, "get_underlying_price", oracle)
    assert await token.get_price(BLOCK.number, sync=False) is None
    oracle.assert_not_awaited()


@run_async_test
async def test_guni_uses_aggregate_underlying_balances(monkeypatch: Any) -> None:
    module = importlib.import_module("y.prices.tokenized_fund.gelato")
    signatures = []

    async def response(self: Any, *args: Any, **kwargs: Any) -> Any:
        signatures.append(self.signature.signature)
        assert self.block_id == BLOCK.number
        return (3 * 10**6, 7 * 10**18)

    monkeypatch.setattr(Call, "coroutine", response)
    monkeypatch.setattr(
        module,
        "raw_call",
        AsyncMock(
            side_effect=lambda address, method, **kw: (
                TOKEN if method == "token0()" else CHILD if method == "token1()" else 99
            )
        ),
    )

    class Token:
        def __init__(self, *a: Any, **kw: Any) -> None:
            pass

        @staticmethod
        async def _get_scale_for(token: str) -> int:
            return 10**6 if token == TOKEN else 10**18

        async def total_supply_readable(self, *a: Any, **kw: Any) -> float:
            return 2.0

    monkeypatch.setattr(module, "ERC20", Token)
    monkeypatch.setattr(module.y.prices.magic, "get_price", AsyncMock(return_value=1))
    assert await module.get_price(TOKEN, BLOCK.number, sync=False) == 5
    assert signatures == ["getUnderlyingBalances()(uint256,uint256)"]


@run_async_test
@pytest.mark.parametrize("version", [1, 2, 3])
async def test_aave_sync_default_registry_async_dispatch(monkeypatch: Any, version: int) -> None:
    module = importlib.import_module("y.prices.lending.aave")
    market = getattr(module, f"AaveMarketV{version}")(f"0x{0xB000 + version:040x}")
    data: Any = {"aTokenAddress": CHILD} if version == 1 else [0] * 16
    if version != 1:
        data[7 if version == 2 else 8] = CHILD

    # Keep the a_sync method descriptors and real map dispatch active.
    async def response(self: Any, *args: Any, **kwargs: Any) -> Any:
        return [TOKEN] if "getReserves" in self.signature.signature else data

    monkeypatch.setattr(Call, "coroutine", response)
    monkeypatch.setattr(
        module.AaveMarketBase,
        "contract",
        property(
            lambda self: SimpleNamespace(
                getReserveData=SimpleNamespace(coroutine=AsyncMock(return_value=data))
            )
        ),
    )
    tokens = await market.__atokens__
    assert [token.address.lower() for token in tokens] == [CHILD]


@run_async_test
@pytest.mark.parametrize("protocol", ["Uniswap V3", "Slipstream"])
@pytest.mark.parametrize("shape", ["scalar", "tuple"])
@pytest.mark.parametrize("capacity", [1000001, 1000000, None])
async def test_v3_requires_full_input(
    monkeypatch: Any, protocol: str, shape: str, capacity: int | None
) -> None:
    module = importlib.import_module("y.prices.dex.uniswap.v3")
    quoted = 997000 if shape == "scalar" else (997000, [12345], [1], 45000)
    exact_input = AsyncMock(return_value=quoted)
    exact_output = AsyncMock(
        return_value=capacity if shape == "scalar" else (capacity, [12345], [1], 45000),
        side_effect=(
            ContractLogicError("execution reverted: Unexpected error") if capacity is None else None
        ),
    )
    monkeypatch.setattr(
        module,
        "load_quoter",
        AsyncMock(
            return_value=SimpleNamespace(
                quoteExactInput=SimpleNamespace(coroutine=exact_input),
                quoteExactOutput=SimpleNamespace(coroutine=exact_output),
            )
        ),
    )
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=6))
    market = Market(protocol, CHILD, (TOKEN, USD), (10**9, 10**9), USD, 3000, tick_spacing=60)
    asset = QuoteAsset(TOKEN, 1000000, 6)
    result = await _markets.swap(market, asset, USD, BLOCK)
    if capacity == 1000001:
        assert result is not None
        assert result.input == asset
        assert result.outputs == (QuoteAsset(USD, 997000, 6),)
    else:
        assert result is None
    index, key = ("int24", 60) if protocol == "Slipstream" else ("uint24", 3000)
    exact_output.assert_awaited_once_with(
        encode_packed(["address", index, "address"], [USD, key, TOKEN]),
        997001,
        block_identifier=BLOCK.identifier,
    )


@run_async_test
@pytest.mark.parametrize(
    "error", [RuntimeError("RPC failure"), TypeError("bad response"), asyncio.CancelledError()]
)
async def test_v3_capacity_unexpected_errors_propagate(
    monkeypatch: Any, error: BaseException
) -> None:
    module = importlib.import_module("y.prices.dex.uniswap.v3")
    monkeypatch.setattr(
        module,
        "load_quoter",
        AsyncMock(
            return_value=SimpleNamespace(
                quoteExactInput=SimpleNamespace(coroutine=AsyncMock(return_value=997000)),
                quoteExactOutput=SimpleNamespace(coroutine=AsyncMock(side_effect=error)),
            )
        ),
    )
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=6))
    market = Market("Uniswap V3", CHILD, (TOKEN, USD), (10**9, 10**9), USD, 3000)
    with pytest.raises(type(error), match=str(error)):
        await _markets.swap(market, QuoteAsset(TOKEN, 1000000, 6), USD, BLOCK)


@run_async_test
async def test_v1_native_eth_to_usdc(monkeypatch: Any) -> None:
    eth = EEE_ADDRESS.lower()
    native = AsyncMock(return_value=202725805)
    monkeypatch.setattr(_markets, "optional_read", native)
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=6))
    asset = QuoteAsset(eth, 10**18, 18)
    market = Market("Uniswap V1", CHILD, (USD, eth), (10**12, 10**21))
    result = await _markets.swap(market, asset, USD, BLOCK)
    assert result is not None
    assert result.outputs == (QuoteAsset(USD, 202725805, 6),)
    assert result.method == "getEthToTokenInputPrice(uint256)"
    native.assert_awaited_once_with(
        CHILD, "getEthToTokenInputPrice(uint256)(uint256)", BLOCK, 10**18
    )


@run_async_test
async def test_popsicle_zero_supply(monkeypatch: Any) -> None:
    module = importlib.import_module("y.prices.popsicle")
    monkeypatch.setattr(module, "get_tvl", AsyncMock(return_value=Decimal(42)))
    monkeypatch.setattr(
        module,
        "ERC20",
        lambda *a, **kw: SimpleNamespace(
            total_supply=AsyncMock(return_value=0), total_supply_readable=AsyncMock(return_value=0)
        ),
    )
    assert await module.get_price(TOKEN, BLOCK.number, sync=False) is None


@run_async_test
async def test_popsicle_historical_supply_scale(monkeypatch: Any) -> None:
    module = importlib.import_module("y.prices.popsicle")
    supply = AsyncMock(return_value=3 * 10**18)
    decimals = AsyncMock(return_value=18)
    monkeypatch.setattr(module.ERC20, "total_supply", supply)
    monkeypatch.setattr(module.ERC20, "_decimals", decimals)
    monkeypatch.setattr(module, "get_tvl", AsyncMock(return_value=Decimal(42)))
    assert await module.get_price(TOKEN, BLOCK.number, skip_cache=True, sync=False) == 14
    supply.assert_awaited_once_with(BLOCK.number, sync=False)
    decimals.assert_awaited_once_with(BLOCK.number)


@run_async_test
async def test_piedao_balance_uses_encoded_call(monkeypatch: Any) -> None:
    module = importlib.import_module("y.prices.tokenized_fund.piedao")
    calls = []

    async def response(self: Any, *a: Any, **kw: Any) -> int:
        calls.append((self.data, self.block_id))
        return 1234567

    monkeypatch.setattr(Call, "coroutine", response)
    result = await module.get_balance(
        CHILD, SimpleNamespace(address=TOKEN, __scale__=Ready(10**6)), BLOCK.number
    )
    assert result == Decimal("1.234567")
    assert calls == [(Call(TOKEN, ["balanceOf(address)(uint)", CHILD]).data, BLOCK.number)]


@run_async_test
async def test_piedao_values_each_token_in_its_pool(monkeypatch: Any) -> None:
    module = importlib.import_module("y.prices.tokenized_fund.piedao")
    tokens = [
        SimpleNamespace(address=TOKEN, __scale__=Ready(10**6), price=AsyncMock(return_value=2)),
        SimpleNamespace(address=USD, __scale__=Ready(10**18), price=AsyncMock(return_value=4)),
    ]
    monkeypatch.setattr(module, "get_bpool", AsyncMock(return_value=CHILD))
    monkeypatch.setattr(module, "get_tokens", AsyncMock(return_value=tokens))
    calls = []

    async def response(self: Any, *a: Any, **kw: Any) -> int:
        calls.append((self.target.lower(), self.data, self.block_id))
        return 3 * 10**6 if self.target.lower() == TOKEN else 5 * 10**18

    monkeypatch.setattr(Call, "coroutine", response)
    assert await module.get_tvl(TOKEN, BLOCK.number, skip_cache=True) == 26
    assert set(calls) == {
        (token.address, Call(token.address, ["balanceOf(address)(uint)", CHILD]).data, BLOCK.number)
        for token in tokens
    }
    for token in tokens:
        token.price.assert_awaited_once_with(BLOCK.number, skip_cache=True, sync=False)


@run_async_test
async def test_unverified_aave_v3_uses_contract_methods(monkeypatch: Any) -> None:
    module = importlib.import_module("y.prices.lending.aave")
    registry = instance(module.AaveRegistry)
    monkeypatch.setattr(
        module.Contract, "coroutine", AsyncMock(return_value=SimpleNamespace(verified=False))
    )

    async def response(self: Any, *a: Any, **kw: Any) -> str:
        return CHILD

    monkeypatch.setattr(Call, "coroutine", response)
    assert await registry.is_wrapped_atoken_v3(TOKEN, sync=False) is True


@run_async_test
async def test_synthetix_historical_resolver(monkeypatch: Any) -> None:
    module = importlib.import_module("y.prices.synthetix")
    synth = instance(module.Synthetix)
    calls = []
    key = b"sUSD".ljust(32, b"\0")

    async def response(self: Any, *a: Any, **kw: Any) -> Any:
        signature = self.signature.signature
        calls.append((self.target.lower(), signature, self.block_id))
        return {
            "target()(address)": TOKEN,
            "currencyKey()(bytes32)": key,
            "resolver()(address)": CHILD,
            "getAddress(bytes32)(address)": USD,
            "rateIsStale(bytes32)(bool)": False,
            "rateForCurrency(bytes32)(uint256)": 10**18,
        }[signature]

    monkeypatch.setattr(Call, "coroutine", response)
    monkeypatch.setattr(module.Synthetix, "get_address", AsyncMock(return_value=None))
    monkeypatch.setattr(module.Synthetix, "get_currency_key", AsyncMock(return_value=None))
    assert await synth.get_price(TOKEN, BLOCK.number, sync=False) == 1
    assert all(block == BLOCK.number for _, _, block in calls)
    assert (CHILD, "getAddress(bytes32)(address)", BLOCK.number) in calls
    assert (USD, "rateForCurrency(bytes32)(uint256)", BLOCK.number) in calls
