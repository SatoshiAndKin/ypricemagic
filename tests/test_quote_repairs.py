"""Quote policy and native-adapter regressions with controlled RPC responses."""

import asyncio
import importlib
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest
from eth_abi.exceptions import InsufficientDataBytes
from web3.exceptions import ContractLogicError

from tests.test_amount_quotes import BLOCK, CHILD, TOKEN, USD, graph, market
from tests.test_pricing_correctness import Ready, run_async_test
from y import constants
from y.contracts import Contract
from y.datatypes import QuoteAsset
from y.exceptions import ContractNotVerified, yPriceMagicError
from y.prices import _markets, _redemptions, _routing, magic, utils
from y.prices._routing import QuoteService
from y.prices._rpc import BlockRef

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
USDC_CASES = [
    (int(chain), token)
    for chain, tokens in constants._STABLECOINS.items()
    for token, name in tokens.items()
    if name in ("usdc", "usdc.e", "usdbc")
]


def multiplexer_graph(monkeypatch: Any, pools: Any, rates: Any = None) -> Any:
    """Keep the public multiplexer and routing code over a controlled market graph."""
    service, seen, discovery = graph(monkeypatch, pools, rates)
    monkeypatch.setattr(_routing, "quote_service", lambda: service)
    monkeypatch.setattr(BlockRef, "resolve", AsyncMock(return_value=BLOCK))
    return service, seen, discovery


@run_async_test
@pytest.mark.parametrize(
    "protocol,fee,spacing",
    [("Uniswap V3", 3000, 60), ("Uniswap V3", 10000, 200), ("Slipstream", 0, 60)],
)
async def test_pool_created_event_reaches_native_quoter(
    monkeypatch: Any, protocol: str, fee: int, spacing: int
) -> None:
    from y import convert
    from y.prices.dex.uniswap import uniswap_multiplexer, v3

    pool_address = f"0x{fee + spacing + 100000:040x}"
    values: tuple[Any, ...] = (TOKEN, USD, spacing, pool_address)
    registry = v3.SlipstreamPools if protocol == "Slipstream" else v3.UniV3Pools
    if protocol == "Uniswap V3":
        values = (TOKEN, USD, fee, spacing, pool_address)
    event = SimpleNamespace(values=lambda: values, block_number=BLOCK.number - 1)
    pool = registry._process_event(cast(Any, SimpleNamespace(asynchronous=True)), cast(Any, event))

    async def pools_for_token(token: str, block: int) -> AsyncIterator[Any]:
        assert token == convert.to_address(TOKEN) and block == BLOCK.number
        yield pool

    router = SimpleNamespace(_quoter=CHILD, _factory=USD, pools_for_token=pools_for_token)
    monkeypatch.setattr(uniswap_multiplexer, "v2_routers", {})
    monkeypatch.setattr(uniswap_multiplexer, "v1", None)
    monkeypatch.setattr(uniswap_multiplexer, "v3", None)
    monkeypatch.setattr(uniswap_multiplexer, "v3_forks", [router])
    balancer = importlib.import_module("y.prices.dex.balancer")
    monkeypatch.setattr(
        balancer, "balancer_multiplexer", SimpleNamespace(__v1__=Ready(None), __v2__=Ready(None))
    )
    monkeypatch.setattr(importlib.import_module("y.prices.stable_swap.curve"), "curve", None)
    deployed = AsyncMock(return_value=True)
    monkeypatch.setattr(_markets, "deployed", deployed)

    async def balance(target: str, signature: str, block: BlockRef, owner: str) -> int:
        assert target in (TOKEN, USD)
        assert signature == "balanceOf(address)(uint256)" and block == BLOCK
        assert owner == pool_address
        return 2000000 if target == TOKEN else 3000000

    monkeypatch.setattr(_markets, "state", balance)
    native = AsyncMock(return_value=997000)
    monkeypatch.setattr(
        Contract,
        "coroutine",
        AsyncMock(return_value=SimpleNamespace(quoteExactInput=SimpleNamespace(coroutine=native))),
    )
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=6))
    markets = await _markets.discover(TOKEN, BLOCK)
    assert len(markets) == 1
    result = await _markets.swap(markets[0], QuoteAsset(TOKEN, 1000001, 6), USD, BLOCK)
    key = spacing if protocol == "Slipstream" else fee
    native.assert_awaited_once_with(
        bytes.fromhex(TOKEN[2:])
        + key.to_bytes(3, "big", signed=protocol == "Slipstream")
        + bytes.fromhex(USD[2:]),
        1000001,
        block_identifier=BLOCK.identifier,
    )
    assert result is not None and result.outputs == (QuoteAsset(USD, 997000, 6),)
    assert result.contract == pool_address and result.protocol == protocol
    assert pool.fee == fee and pool.tick_spacing == spacing
    assert pool._deploy_block == BLOCK.number - 1
    assert markets[0].balances == (2000000, 3000000)
    assert markets[0].fee == fee
    assert markets[0].tick_spacing == (spacing if protocol == "Slipstream" else None)
    deployed.assert_awaited_once_with(pool_address, BLOCK)


@run_async_test
@pytest.mark.parametrize("scenario", ["only", "deepest", "excluded", "unavailable"])
async def test_multiplexer_includes_slipstream(monkeypatch: Any, scenario: str) -> None:
    from y.prices.dex.uniswap import uniswap_multiplexer

    pools = [market("slipstream", depth=2000, protocol="Slipstream")]
    if scenario != "only":
        pools.append(market("shallow", depth=1000))
    rates = {"slipstream": 2, "shallow": 9}
    if scenario == "unavailable":
        rates["slipstream"] = 0
    _, seen, _ = multiplexer_graph(monkeypatch, pools, rates)
    ignored = ("slipstream",) if scenario == "excluded" else ()
    result = await uniswap_multiplexer.get_price(
        TOKEN, BLOCK.number, ignore_pools=ignored, skip_cache=True
    )
    fallback = scenario in ("excluded", "unavailable")
    assert result is not None and float(result) == (9 if fallback else 2)
    expected = ["shallow"] if scenario == "excluded" else ["slipstream"]
    if scenario == "unavailable":
        expected.append("shallow")
    assert seen == [(pool, TOKEN, 10**6, USD) for pool in expected]


@run_async_test
@pytest.mark.parametrize("kind", ["integer", "hexbytes", "bytes", "checksum", "lower", "erc20"])
async def test_multiplexer_normalizes_supported_addresses(monkeypatch: Any, kind: str) -> None:
    from hexbytes import HexBytes

    from y import convert
    from y.classes.common import ERC20
    from y.prices.dex.uniswap import uniswap_multiplexer

    token = f"0x{0xABCD:040x}"
    inputs = {
        "integer": int(token, 16),
        "hexbytes": HexBytes(token),
        "bytes": bytes.fromhex(token[2:]),
        "checksum": convert.to_address(token),
        "lower": token,
        "erc20": ERC20(token, asynchronous=True),
    }
    _, seen, discovery = multiplexer_graph(monkeypatch, [market("pool", first=token)], {"pool": 2})
    result = await uniswap_multiplexer.get_price(inputs[kind], BLOCK.number, skip_cache=True)
    assert result is not None and float(result) == 2
    assert seen == [("pool", token, 10**6, USD)]
    discovery.assert_awaited_once_with(token, BLOCK)


@run_async_test
async def test_multiplexer_rejects_invalid_address_before_rpc(monkeypatch: Any) -> None:
    from y.prices.dex.uniswap import uniswap_multiplexer

    rpc = AsyncMock(return_value=None)
    monkeypatch.setattr(_routing, "liquidity_price", rpc)
    with pytest.raises(ValueError, match="not a valid ETH address"):
        await uniswap_multiplexer.get_price("not-an-address", BLOCK.number)
    rpc.assert_not_awaited()


@run_async_test
@pytest.mark.parametrize("value", [0, 1, 0xABCD, int(DAI, 16), 2**160 - 1])
async def test_integer_address_conversion_preserves_every_byte(value: int) -> None:
    from y import convert

    expected = convert.to_address(f"0x{value:040x}")
    assert convert.to_address(value) == expected
    assert await convert.to_address_async(value) == expected


@run_async_test
@pytest.mark.parametrize("value", [-1, 2**160])
async def test_integer_address_conversion_rejects_out_of_range(value: int) -> None:
    from y import convert

    with pytest.raises(ValueError):
        convert.to_address(value)
    with pytest.raises(ValueError):
        await convert.to_address_async(value)


@run_async_test
@pytest.mark.parametrize("chain,token", USDC_CASES)
async def test_terminal_usdc_policy_precedes_oracles(
    monkeypatch: Any, chain: int, token: str
) -> None:
    import y.prices

    lookup = AsyncMock(return_value=Decimal("0.88"))
    monkeypatch.setattr(y.prices, "chainlink", SimpleNamespace(get_price=lookup))
    for address in (token.lower(), token, token.upper()):
        result = await QuoteService().usd(address, replace(BLOCK, chain=chain))
        assert result is not None and float(result) == 1
        assert "1 USDC = $1" in result.path[0].source
    lookup.assert_not_awaited()


@run_async_test
@pytest.mark.parametrize("value", ["0.88", "1.01"])
@pytest.mark.parametrize("chain,token", USDC_CASES)
async def test_spot_usdc_overrides_cache_api_and_oracle(
    monkeypatch: Any, value: str, chain: int, token: str
) -> None:
    from y._db.utils import price as db

    monkeypatch.setattr(constants, "CHAINID", chain)
    cached = AsyncMock(return_value=Decimal(value))
    api = AsyncMock(return_value=Decimal(value))
    monkeypatch.setattr(db, "get_price", cached)
    monkeypatch.setattr(magic, "_get_price_from_api", api)
    monkeypatch.setattr(magic, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("USDC")))
    monkeypatch.setattr(utils, "sense_check", AsyncMock())
    for skip in (False, True):
        for block in (16785000, 16795000):
            result = await cast(Any, magic.get_price)(token, block, skip_cache=skip, sync=False)
            assert float(result) == 1
            assert "1 USDC = $1" in result.path[0].source
    cached.assert_not_awaited()
    api.assert_not_awaited()


@run_async_test
async def test_other_stablecoins_and_wrong_chain_keep_variable_prices(monkeypatch: Any) -> None:
    import y.prices

    lookup = AsyncMock(return_value=Decimal("0.88"))
    monkeypatch.setattr(y.prices, "chainlink", SimpleNamespace(get_price=lookup))
    service = QuoteService()
    for token, block in ((DAI, BLOCK), (USDC, replace(BLOCK, chain=10))):
        result = await service.usd(token, block)
        assert result is not None and float(result) == 0.88
    assert lookup.await_count == 2


@run_async_test
async def test_band_rate_uses_fixed_usdc_source(monkeypatch: Any) -> None:
    import y.prices

    band = AsyncMock(return_value=1.25)
    monkeypatch.setattr(
        y.prices, "chainlink", SimpleNamespace(get_price=AsyncMock(return_value=None))
    )
    monkeypatch.setattr(y.prices, "band", SimpleNamespace(get_price=band))
    result = await QuoteService().usd(DAI, BLOCK)
    assert result is not None and float(result) == 1.25
    assert "Band" in result.path[0].source and "1 USDC = $1" in result.path[0].source
    assert "historical USD" not in result.path[0].source
    monkeypatch.setattr(utils, "check_bucket", AsyncMock(return_value="chainlink and band"))
    monkeypatch.setattr(magic, "chainlink", y.prices.chainlink)
    monkeypatch.setattr(magic, "band", y.prices.band)
    price, source = await cast(Any, magic._exit_early_for_known_tokens)(TOKEN, BLOCK.number, Mock())
    assert price == 1.25 and "1 USDC = $1" in source


@run_async_test
async def test_usdc_amount_keeps_native_output_fees_and_impact(monkeypatch: Any) -> None:
    service, _, _ = graph(monkeypatch, [market("pool", first=USDC, second=DAI)])
    monkeypatch.setattr(service, "usd", QuoteService.usd.__get__(service))
    monkeypatch.setattr(_routing, "swap", _markets.swap)
    calls = []

    async def read(target: str, signature: str, block: BlockRef, *args: Any) -> Any:
        assert block == BLOCK
        if signature == "decimals()(uint8)":
            return 6
        calls.append((target, args))
        return [1000000000, 994000000]

    monkeypatch.setattr(_markets, "read", read)
    import y.prices

    monkeypatch.setattr(y.prices, "chainlink", SimpleNamespace(get_price=AsyncMock(return_value=1)))
    result = await service.price(USDC, BLOCK, 1000)
    assert result is not None and result.quote is not None
    assert result.quote.total_usd == Decimal(994)
    assert result.quote.outputs == (QuoteAsset(DAI, 994000000, 6),)
    assert result.quote.steps[0].fees == "DEX fees included in native quote"
    assert calls == [("router", (1000000000, [USDC, DAI]))]


@run_async_test
@pytest.mark.parametrize(
    "error", [InsufficientDataBytes("empty decimals"), ContractLogicError("execution reverted")]
)
@pytest.mark.parametrize("fail", [True, False])
async def test_missing_decimals_obey_public_failure_policy(
    monkeypatch: Any, error: Exception, fail: bool
) -> None:
    monkeypatch.setattr(BlockRef, "resolve", AsyncMock(return_value=BLOCK))
    verify = AsyncMock()
    monkeypatch.setattr(BlockRef, "verify", verify)
    monkeypatch.setattr(_routing, "state", AsyncMock(side_effect=error))
    if fail:
        assert (
            await cast(Any, magic.get_price)(
                USDC, BLOCK.number, amount=1, fail_to_None=True, sync=False
            )
            is None
        )
    else:
        with pytest.raises(yPriceMagicError):
            await cast(Any, magic.get_price)(USDC, BLOCK.number, amount=1, sync=False)
    verify.assert_awaited_once()


@run_async_test
async def test_missing_decimals_mixed_batch_preserves_order(monkeypatch: Any) -> None:
    service, _, _ = graph(monkeypatch, [market("pool")])
    monkeypatch.setattr(_routing, "quote_service", lambda: service)
    monkeypatch.setattr(BlockRef, "resolve", AsyncMock(return_value=BLOCK))

    async def state(token: str, *args: Any) -> int:
        if token == CHILD:
            raise InsufficientDataBytes("empty decimals")
        return 6

    monkeypatch.setattr(_routing, "state", state)
    results = await cast(Any, magic.get_prices)(
        [TOKEN, CHILD, TOKEN], BLOCK.number, amounts=[1, 2, 3], fail_to_None=True, sync=False
    )
    assert results[1] is None
    assert [results[i].quote.total_usd for i in (0, 2)] == [1, 3]


@run_async_test
@pytest.mark.parametrize("error", [RuntimeError("RPC disconnected"), asyncio.CancelledError()])
async def test_unexpected_decimals_errors_propagate(monkeypatch: Any, error: BaseException) -> None:
    monkeypatch.setattr(_routing, "state", AsyncMock(side_effect=error))
    with pytest.raises(type(error)):
        await QuoteService().price(USDC, BLOCK, 1)


def curve_fixture(monkeypatch: Any, outputs: list[Any]) -> tuple[QuoteService, list[Any]]:
    service, _, _ = graph(monkeypatch, [])
    monkeypatch.setattr(service, "redeem", QuoteService.redeem.__get__(service))
    monkeypatch.setattr(service, "usd", QuoteService.usd.__get__(service))
    module = importlib.import_module("y.prices.stable_swap.curve")
    pool = "0x0000000000000000000000000000000000000900"
    monkeypatch.setattr(module, "curve", SimpleNamespace(get_pool=AsyncMock(return_value=pool)))
    monkeypatch.setattr(_redemptions, "optional_read", AsyncMock(return_value=None))

    async def read(token: str, signature: str, *args: Any) -> int:
        return 6 if signature == "decimals()(uint8)" else 10**20

    monkeypatch.setattr(_redemptions, "read", read)
    coins = (constants.EEE_ADDRESS.lower(), CHILD)
    monkeypatch.setattr(
        _markets, "curve_pool_state", AsyncMock(return_value=SimpleNamespace(tokens=coins))
    )
    calls = []

    async def quote(amount: int, index: int, **kwargs: Any) -> int:
        calls.append((amount, index, kwargs))
        result = outputs[len(calls) - 1]
        if isinstance(result, BaseException):
            raise result
        return int(result)

    monkeypatch.setattr(
        Contract,
        "coroutine",
        AsyncMock(
            return_value=SimpleNamespace(calc_withdraw_one_coin=SimpleNamespace(coroutine=quote))
        ),
    )
    # Nonterminal CHILD is unpriceable; native ETH is valued by the real terminal path.
    import y.prices

    monkeypatch.setattr(
        y.prices, "chainlink", SimpleNamespace(get_price=AsyncMock(return_value=2000))
    )
    return service, calls


@run_async_test
@pytest.mark.parametrize("first", [100, 0, ContractLogicError("execution reverted")])
async def test_curve_tries_later_fully_valued_native_exit(monkeypatch: Any, first: Any) -> None:
    service, calls = curve_fixture(monkeypatch, [first, 2 * 10**18])
    # The child is not an LP. This keeps all routing real, with unavailable discovery.
    module = importlib.import_module("y.prices.stable_swap.curve")
    monkeypatch.setattr(
        module.curve,
        "get_pool",
        AsyncMock(
            side_effect=lambda token, **kw: (
                "0x0000000000000000000000000000000000000900" if token == TOKEN else None
            )
        ),
    )
    result = await service.price(TOKEN, BLOCK, 1)
    assert result is not None and result.quote is not None
    assert result.quote.outputs == (QuoteAsset(constants.EEE_ADDRESS.lower(), 2 * 10**18, 18),)
    assert result.quote.total_usd == 4000
    assert len(result.quote.steps) == 1
    assert result.quote.steps[0].contract == "0x0000000000000000000000000000000000000900"
    assert calls == [(10**6, i, {"block_identifier": BLOCK.identifier}) for i in (1, 0)]


@run_async_test
@pytest.mark.parametrize("unverified", [False, True])
@pytest.mark.parametrize("quoted", [997000, (997000, [], [], 1)])
@pytest.mark.parametrize("protocol,key", [("Uniswap V3", 3000), ("Slipstream", 60)])
async def test_v3_shared_fallback_quotes_exact_amount_and_hash(
    monkeypatch: Any, unverified: bool, quoted: Any, protocol: str, key: int
) -> None:
    quote = AsyncMock(return_value=quoted)
    contract = SimpleNamespace(quoteExactInput=SimpleNamespace(coroutine=quote))
    load = AsyncMock(
        side_effect=ContractNotVerified("quoter") if unverified else None, return_value=contract
    )
    fallback = Mock(return_value=contract)
    monkeypatch.setattr(Contract, "coroutine", load)
    monkeypatch.setattr(Contract, "from_abi", fallback)
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=6))
    pool = replace(market("pool", protocol=protocol), router=CHILD, fee=3000, tick_spacing=60)
    result = await _markets.swap(pool, QuoteAsset(TOKEN, 1000001, 6), USD, BLOCK)
    assert result is not None
    assert result.outputs == (QuoteAsset(USD, 997000, 6),)
    quote.assert_awaited_once_with(
        bytes.fromhex(TOKEN[2:]) + key.to_bytes(3, "big") + bytes.fromhex(USD[2:]),
        1000001,
        block_identifier=BLOCK.identifier,
    )
    assert fallback.call_count == int(unverified)
    if unverified:
        from y.interfaces.uniswap.quoterv3 import UNIV3_QUOTER_ABI

        fallback.assert_called_once_with("Quoter", CHILD, UNIV3_QUOTER_ABI)


@run_async_test
async def test_quoter_unexpected_error_does_not_use_fallback(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        Contract, "coroutine", AsyncMock(side_effect=RuntimeError("RPC disconnected"))
    )
    fallback = Mock()
    monkeypatch.setattr(Contract, "from_abi", fallback)
    with pytest.raises(RuntimeError, match="RPC disconnected"):
        await _markets.swap(
            replace(market("pool", protocol="Uniswap V3"), router=CHILD, fee=3000),
            QuoteAsset(TOKEN, 1, 6),
            USD,
            BLOCK,
        )
    fallback.assert_not_called()


@run_async_test
@pytest.mark.parametrize("outcome", ["success", "exhausted", "error", "cancelled"])
async def test_redemption_candidates_close_and_isolate_state(
    monkeypatch: Any, outcome: str
) -> None:
    from y.datatypes import QuoteStep
    from y.prices._routing import SearchContext

    dead = "0x0000000000000000000000000000000000000104"
    deeper = "0x0000000000000000000000000000000000000105"
    service, seen, _ = graph(
        monkeypatch, [market("sale", first=CHILD), market("dead-sale", first=dead, second=deeper)]
    )
    monkeypatch.setattr(service, "redeem", QuoteService.redeem.__get__(service))
    entered = asyncio.Event()
    closed = []
    candidate_reads = []

    async def candidates(asset: QuoteAsset, *args: Any) -> Any:
        if asset.token != TOKEN:
            return
        try:
            for index in (1, 2, 3):
                candidate_reads.append(index)
                if index == 2 and outcome == "error":
                    raise RuntimeError("candidate RPC failure")
                if index == 2 and outcome == "cancelled":
                    entered.set()
                    await asyncio.Event().wait()
                outputs: tuple[QuoteAsset, ...] = (QuoteAsset(CHILD, 1000000, 6),)
                if index == 1 or outcome == "exhausted":
                    outputs += (QuoteAsset(dead, 1000000, 6),)
                yield QuoteStep(
                    "redemption",
                    "LP",
                    f"exit-{index}",
                    asset,
                    outputs,
                    "withdraw",
                    "included",
                    "unverified",
                ), (f"changed-{index}",)
        finally:
            closed.append(True)

    monkeypatch.setattr(_redemptions, "redeem", candidates)
    search = SearchContext()
    task = asyncio.create_task(
        service.redeem(
            QuoteAsset(TOKEN, 1000000, 6),
            BLOCK,
            frozenset({"original"}),
            frozenset(),
            False,
            11,
            search,
        )
    )
    if outcome == "cancelled":
        await entered.wait()
        task.cancel()
    if outcome in ("error", "cancelled"):
        with pytest.raises(RuntimeError if outcome == "error" else asyncio.CancelledError):
            await task
    else:
        result = await task
        if outcome == "success":
            assert result is not None
            assert result.value == 1
            assert result.outputs == (QuoteAsset(USD, 1000000, 6),)
            assert [step.contract for step in result.steps] == ["exit-2", "sale"]
            assert result.used == frozenset({"original", "exit-2", "changed-2", "sale"})
            assert search.rejected == set()
            assert TOKEN not in search.rejected_redemptions
        else:
            assert result is None
            assert TOKEN in search.rejected_redemptions
    assert closed == [True]
    assert candidate_reads == ([1, 2, 3] if outcome == "exhausted" else [1, 2])
    assert seen == [("sale", CHILD, 1000000, USD), ("dead-sale", dead, 1000000, deeper)]


@run_async_test
async def test_curve_first_success_is_lazy_and_exhaustion_is_unavailable(monkeypatch: Any) -> None:
    from contextlib import aclosing

    service, calls = curve_fixture(monkeypatch, [0, 0])
    async with aclosing(
        _redemptions.redeem(QuoteAsset(TOKEN, 1, 6), BLOCK, frozenset())
    ) as candidates:
        assert [candidate async for candidate in candidates] == []
    assert [call[1] for call in calls] == [1, 0]
    service, calls = curve_fixture(monkeypatch, [100, RuntimeError("must remain lazy")])
    async with aclosing(
        _redemptions.redeem(QuoteAsset(TOKEN, 1, 6), BLOCK, frozenset())
    ) as candidates:
        step, pools = await anext(candidates)
        assert step.outputs[0].token == CHILD and step.outputs[0].amount == 100
        assert pools == ("0x0000000000000000000000000000000000000900",)
    assert [call[1] for call in calls] == [1]


@run_async_test
async def test_adapter_closes_underlying_generator(monkeypatch: Any) -> None:
    from contextlib import aclosing

    from y.datatypes import QuoteStep

    closed = []
    asset = QuoteAsset(TOKEN, 1, 6)
    step = QuoteStep("redemption", "LP", TOKEN, asset, (asset,), "withdraw", "none", "unverified")

    async def candidates(*args: Any) -> Any:
        try:
            yield step, ()
        finally:
            closed.append(True)

    monkeypatch.setattr(_redemptions, "_redeem_candidates", candidates)
    async with aclosing(_redemptions.redeem(asset, BLOCK, frozenset())) as iterator:
        assert await anext(iterator) == (step, ())
    assert closed == [True]


@run_async_test
async def test_band_native_contract_rate_remains_usdc(monkeypatch: Any) -> None:
    from tests.test_pricing_correctness import instance

    module = importlib.import_module("y.prices.band")
    oracle = instance(module.Band)
    oracle.asynchronous = True
    quote = AsyncMock(return_value=(1250000000000000000, BLOCK.timestamp, BLOCK.timestamp))
    monkeypatch.setattr(
        module.Band,
        "__oracle__",
        property(
            lambda self: Ready(SimpleNamespace(getReferenceData=SimpleNamespace(coroutine=quote)))
        ),
    )
    monkeypatch.setattr(module, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("ASSET")))
    assert await oracle.get_price(TOKEN, BLOCK, sync=False) == 1.25
    quote.assert_awaited_once_with("ASSET", "USDC", block_identifier=BLOCK.identifier)


@run_async_test
async def test_configured_usdc_outside_curated_entries(monkeypatch: Any) -> None:
    from y.prices._usdc import fixed_usdc_price

    monkeypatch.setattr(constants, "CHAINID", 100)
    monkeypatch.setattr(constants, "usdc", "0xDDAfbb505ad214D7b80b1f830fcCc89B60fb7A83")
    token = str(constants.usdc).lower()
    result = fixed_usdc_price(token, 100)
    assert result is not None and float(result) == 1
    assert fixed_usdc_price(token, 1) is None
    assert fixed_usdc_price(TOKEN, 100) is None


@run_async_test
@pytest.mark.parametrize("unverified", [False, True])
async def test_existing_v3_property_uses_shared_initializer(
    monkeypatch: Any, unverified: bool
) -> None:
    from tests.test_pricing_correctness import instance
    from y.prices.dex.uniswap.v3 import UniswapV3

    router = instance(UniswapV3)
    router.asynchronous = True
    router._quoter = CHILD
    contract = object()
    monkeypatch.setattr(
        Contract,
        "coroutine",
        AsyncMock(
            return_value=contract, side_effect=ContractNotVerified(CHILD) if unverified else None
        ),
    )
    fallback = Mock(return_value=contract)
    monkeypatch.setattr(Contract, "from_abi", fallback)
    assert await router.__quoter__ is contract
    assert fallback.call_count == int(unverified)


@run_async_test
async def test_curve_first_fully_valued_exit_stops_before_later_rpc(monkeypatch: Any) -> None:
    service, calls = curve_fixture(monkeypatch, [1000000, RuntimeError("must stay lazy")])
    monkeypatch.setattr(_routing, "STABLECOINS", {CHILD: "dai"})
    result = await service.price(TOKEN, BLOCK, 1)
    assert result is not None and result.quote is not None
    assert result.quote.total_usd == 2000
    assert result.quote.outputs == (QuoteAsset(CHILD, 1000000, 6),)
    assert [call[1] for call in calls] == [1]


@run_async_test
@pytest.mark.parametrize("missing", [None, InsufficientDataBytes("empty output decimals")])
async def test_curve_missing_output_decimals_tries_next_exit(
    monkeypatch: Any, missing: Any
) -> None:
    service, calls = curve_fixture(monkeypatch, [1000000, 2 * 10**18])

    async def read(token: str, signature: str, *args: Any) -> Any:
        if signature == "decimals()(uint8)":
            if isinstance(missing, Exception):
                raise missing
            return missing
        return 10**20

    monkeypatch.setattr(_redemptions, "read", read)
    result = await service.price(TOKEN, BLOCK, 1)
    assert result is not None and result.quote is not None
    assert result.quote.total_usd == 4000
    assert result.quote.outputs == (QuoteAsset(constants.EEE_ADDRESS.lower(), 2 * 10**18, 18),)
    assert [call[1] for call in calls] == [1, 0]


@run_async_test
async def test_unavailable_decimals_still_checks_canonical_block(monkeypatch: Any) -> None:
    monkeypatch.setattr(_routing, "state", AsyncMock(side_effect=InsufficientDataBytes("empty")))
    monkeypatch.setattr(BlockRef, "verify", AsyncMock(side_effect=RuntimeError("block changed")))
    with pytest.raises(RuntimeError, match="block changed"):
        await QuoteService().price(USDC, BLOCK, 1)


@run_async_test
@pytest.mark.parametrize("fail", [True, False])
async def test_empty_rpc_decimals_obey_public_failure_policy(monkeypatch: Any, fail: bool) -> None:
    from dank_mids.brownie_patch import dank_web3

    from y.prices import _rpc
    from y.prices._quote import SharedCache

    monkeypatch.setattr(BlockRef, "resolve", AsyncMock(return_value=BLOCK))
    verify = AsyncMock()
    monkeypatch.setattr(BlockRef, "verify", verify)
    monkeypatch.setattr(_routing, "state", _rpc.state)
    cache: SharedCache[Any] = SharedCache(16)
    monkeypatch.setattr(_rpc, "state_cache", lambda: cache)
    call = AsyncMock(return_value=b"")
    monkeypatch.setattr(dank_web3.eth, "call", call)
    monkeypatch.setattr(magic, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("USDC")))
    if fail:
        assert (
            await cast(Any, magic.get_price)(
                USDC, BLOCK.number, amount=1, fail_to_None=True, sync=False
            )
            is None
        )
    else:
        with pytest.raises(yPriceMagicError):
            await cast(Any, magic.get_price)(USDC, BLOCK.number, amount=1, sync=False)
    verify.assert_awaited_once()
    call.assert_awaited_once()
    assert call.call_args.kwargs == {"block_identifier": BLOCK.identifier}


@run_async_test
async def test_empty_swap_output_metadata_is_unavailable(monkeypatch: Any) -> None:
    async def read(token: str, signature: str, *args: Any) -> Any:
        return None if signature == "decimals()(uint8)" else [1000000, 997000]

    monkeypatch.setattr(_markets, "read", read)
    assert await _markets.swap(market("pool"), QuoteAsset(TOKEN, 1000000, 6), USD, BLOCK) is None
