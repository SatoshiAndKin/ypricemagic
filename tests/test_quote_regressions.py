"""Regression cases for request-wide fallback and native quote contracts."""

import asyncio
import importlib
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call

import pytest
from eth_abi.abi import encode
from eth_utils.crypto import keccak
from hexbytes import HexBytes
from web3.exceptions import ContractLogicError

from tests.test_amount_quotes import BLOCK, CHILD, TOKEN, USD, graph, market
from tests.test_pricing_correctness import Ready, run_async_test
from y.datatypes import PriceResult, QuoteAsset, QuoteStep, UsdPrice
from y.prices import _markets, _redemptions, _routing, _rpc
from y.prices._routing import QuoteService


@run_async_test
async def test_factory_restricted_price_does_not_scan_other_protocols(monkeypatch: Any) -> None:
    from y.contracts import Contract
    from y.prices.dex.uniswap import uniswap_multiplexer

    pool_address = "0x0000000000000000000000000000000000007400"
    pool = SimpleNamespace(address=pool_address, token0=TOKEN, token1=USD, fee=3000)

    async def pools_for_token(token: str, block: int) -> AsyncIterator[Any]:
        assert token == TOKEN and block == BLOCK.number
        yield pool

    excluded = AsyncMock(side_effect=AssertionError("excluded pool index must not load"))
    monkeypatch.setattr(
        uniswap_multiplexer,
        "v2_routers",
        {"excluded": SimpleNamespace(address=CHILD, factory=TOKEN, get_pools_for=excluded)},
    )
    monkeypatch.setattr(
        uniswap_multiplexer,
        "v3",
        SimpleNamespace(_quoter=CHILD, _factory=USD, pools_for_token=pools_for_token),
    )
    monkeypatch.setattr(
        uniswap_multiplexer,
        "v3_forks",
        [SimpleNamespace(_quoter=CHILD, _factory=TOKEN, pools_for_token=excluded)],
    )
    monkeypatch.setattr(uniswap_multiplexer, "v1", None)
    monkeypatch.setattr(importlib.import_module("y.prices.stable_swap.curve"), "curve", None)
    monkeypatch.setattr(
        importlib.import_module("y.prices.dex.balancer"),
        "balancer_multiplexer",
        SimpleNamespace(__v1__=Ready(None), __v2__=Ready(None)),
    )
    deployed = AsyncMock(return_value=True)
    monkeypatch.setattr(_markets, "deployed", deployed)
    monkeypatch.setattr(_markets, "state", AsyncMock(return_value=10000000))
    monkeypatch.setattr(_routing, "state", AsyncMock(return_value=6))
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=6))
    native = AsyncMock(return_value=997003)
    monkeypatch.setattr(
        Contract,
        "coroutine",
        AsyncMock(return_value=SimpleNamespace(quoteExactInput=SimpleNamespace(coroutine=native))),
    )
    monkeypatch.setattr(_rpc.BlockRef, "verify", AsyncMock())
    service = QuoteService()
    terminal = AsyncMock(return_value=PriceResult(UsdPrice(1), []))
    monkeypatch.setattr(service, "usd", terminal)
    monkeypatch.setattr(service, "redeem", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "explicit", AsyncMock(return_value=None))
    result = await service.price(TOKEN, BLOCK, Decimal("1.000001"), first_markets=(USD,))
    assert result is not None and result.quote is not None
    assert result.quote.outputs == (QuoteAsset(USD, 997003, 6),)
    assert result.quote.total_usd == Decimal("0.997003")
    assert [step.contract for step in result.quote.steps] == [pool_address]
    native.assert_awaited_once_with(
        bytes.fromhex(TOKEN[2:]) + (3000).to_bytes(3, "big") + bytes.fromhex(USD[2:]),
        1000001,
        block_identifier=BLOCK.identifier,
    )
    terminal.assert_awaited_once_with(USD, BLOCK)
    assert deployed.await_args_list == [call(USD, BLOCK), call(pool_address, BLOCK)]
    excluded.assert_not_called()


@run_async_test
async def test_market_restriction_cache_is_separate_and_descendants_are_unrestricted(
    monkeypatch: Any,
) -> None:
    first, second = "factory-a", "factory-b"
    pools = [
        replace(market("root", second=CHILD, depth=1), factory=first),
        replace(market("deeper", depth=10), factory=second),
        replace(market("child", first=CHILD), factory=second),
    ]
    service, seen, discovery = graph(monkeypatch, pools, {"root": 2, "child": 3, "deeper": 9})
    for restriction, expected in [((first,), 6), ((), 9), ((second,), 9), ((first, first), 6)]:
        result = await service.price(TOKEN, BLOCK, 1, first_markets=restriction, skip_cache=True)
        assert result is not None and result.quote is not None
        assert result.quote.total_usd == expected
    assert seen == [
        ("root", TOKEN, 1000000, CHILD),
        ("child", CHILD, 2000000, USD),
        ("deeper", TOKEN, 1000000, USD),
        ("deeper", TOKEN, 1000000, USD),
        ("root", TOKEN, 1000000, CHILD),
        ("child", CHILD, 2000000, USD),
    ]
    assert discovery.await_args_list == [
        call(TOKEN, BLOCK, (first,)),
        call(CHILD, BLOCK),
        call(TOKEN, BLOCK),
        call(TOKEN, BLOCK, (second,)),
    ]


@run_async_test
@pytest.mark.parametrize(
    "error,unavailable",
    [
        (ValueError({"code": -32003, "message": "EVM error: InvalidFEOpcode"}), True),
        (ValueError({"code": -32003, "message": "EVM error: InvalidJump"}), True),
        (ValueError({"code": -32003, "message": "EVM error: NotActivated"}), False),
        (ValueError({"code": -32000, "message": "historical state unavailable"}), False),
        (TypeError("unexpected decoder failure"), False),
        (TypeError("EVM error: InvalidFEOpcode"), False),
        (RuntimeError("EVM error: InvalidFEOpcode"), False),
        (TypeError("EVM error: InvalidJump"), False),
        (RuntimeError("EVM error: InvalidJump"), False),
        (asyncio.CancelledError(), False),
    ],
)
async def test_optional_rpc_recognizes_only_known_contract_execution_failures(
    monkeypatch: Any, error: BaseException, unavailable: bool
) -> None:
    rpc = AsyncMock(side_effect=error)
    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=rpc)))
    if unavailable:
        assert await _rpc.optional_read(TOKEN, "asset()(address)", BLOCK) is None
    else:
        with pytest.raises(type(error)) as raised:
            await _rpc.optional_read(TOKEN, "asset()(address)", BLOCK)
        assert raised.value is error
    rpc.assert_awaited_once()
    assert rpc.await_args is not None
    assert rpc.await_args.kwargs["block_identifier"] == BLOCK.identifier


@run_async_test
@pytest.mark.parametrize("cached", ["synthetix", "yearn or yearn-like", "curve lp"])
@pytest.mark.parametrize("band_supported", [False, True])
async def test_cached_fallback_bucket_respects_oracle_history(
    monkeypatch: Any, cached: str, band_supported: bool
) -> None:
    from y._db.utils import token as db
    from y.prices.utils import buckets

    index = ("synthetix", "yearn or yearn-like", "curve lp").index(cached)
    token = f"0x{0x7100 + 2 * index + band_supported:040x}"
    monkeypatch.setattr(db, "get_bucket", AsyncMock(return_value=cached))
    persisted = AsyncMock()
    monkeypatch.setattr(db, "set_bucket", persisted)
    feed = AsyncMock(side_effect=lambda token, *, block: block == 200)
    monkeypatch.setattr(buckets, "chainlink", SimpleNamespace(has_feed=feed))
    monkeypatch.setattr(buckets, "band", {token} if band_supported else set())
    for block in (100, 200, 300):
        expected = cached
        if block == 200:
            expected = "chainlink and band" if band_supported else "chainlink feed"
        assert await buckets.check_bucket(token, block, sync=False) == expected
    assert feed.await_args_list == [call(token, block=block) for block in (100, 200, 300)]
    persisted.assert_not_called()


@run_async_test
@pytest.mark.parametrize("error", [RuntimeError, TypeError, asyncio.CancelledError])
async def test_cached_bucket_oracle_errors_propagate(monkeypatch: Any, error: Any) -> None:
    from y._db.utils import token as db
    from y.prices.utils import buckets

    monkeypatch.setattr(db, "get_bucket", AsyncMock(return_value="curve lp"))
    monkeypatch.setattr(
        buckets, "chainlink", SimpleNamespace(has_feed=AsyncMock(side_effect=error))
    )
    token = f"0x{0x7300 + (RuntimeError, TypeError, asyncio.CancelledError).index(error):040x}"
    with pytest.raises(error):
        await buckets.check_bucket(token, 100, sync=False)


@run_async_test
async def test_xpremia_detection_normalizes_addresses(monkeypatch: Any) -> None:
    from y.prices import exotic_tokens

    address = "0x16f9D564Df80376C61AC914205D3fDfF7057d610"
    methods = AsyncMock(return_value=True)
    monkeypatch.setattr(exotic_tokens, "has_methods", methods)
    for token in (address, address.lower(), bytes.fromhex(address[2:]), HexBytes(address)):
        assert await exotic_tokens.is_xpremia(token, sync=False) is True
    methods.assert_awaited_with(address, ("premia()(address)",), all, sync=False)
    calls = methods.await_count
    assert await exotic_tokens.is_xpremia(TOKEN, sync=False) is False
    assert methods.await_count == calls


@run_async_test
@pytest.mark.parametrize("cash", [0, 999999, 1000000])
async def test_gauge_exit_requires_lp_backing(monkeypatch: Any, cash: int) -> None:
    from y.contracts import Contract

    async def read(token: str, signature: str, block: Any, *args: Any) -> Any:
        assert block == BLOCK
        if signature == "lp_token()(address)":
            assert token == TOKEN
            return USD
        if signature == "balanceOf(address)(uint256)":
            assert token == USD and args == (TOKEN,)
            return cash
        if signature == "decimals()(uint8)":
            assert token == USD
            return 6
        return None

    monkeypatch.setattr(_rpc, "read", read)
    monkeypatch.setattr(_redemptions, "read", read)
    monkeypatch.setattr(
        Contract,
        "coroutine",
        AsyncMock(
            return_value=SimpleNamespace(
                _build={"contractName": "LiquidityGaugeV2"}, withdraw=object()
            )
        ),
    )
    results = [
        result
        async for result in _redemptions.redeem(QuoteAsset(TOKEN, 1000000, 6), BLOCK, frozenset())
    ]
    if cash < 1000000:
        assert results == []
    else:
        assert len(results) == 1
        assert results[0][0].outputs == (QuoteAsset(USD, 1000000, 6),)


@run_async_test
@pytest.mark.parametrize("empty", ["latestTimestamp()", "latestAnswer()", "decimals()"])
async def test_empty_feed_rpc_response_is_unavailable(monkeypatch: Any, empty: str) -> None:
    module = importlib.import_module("y.prices.chainlink")
    values = {"latestTimestamp()": BLOCK.timestamp, "latestAnswer()": 100000000, "decimals()": 8}

    async def call(transaction: Any, block_identifier: Any) -> bytes:
        assert block_identifier == BLOCK.identifier
        selector = bytes(transaction["data"])[:4]
        signature = next(name for name in values if keccak(text=name)[:4] == selector)
        return b"" if signature == empty else encode(["uint256"], [values[signature]])

    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=call)))
    feed = module.Feed(TOKEN, USD, asynchronous=True)
    assert await feed.get_price(BLOCK) is None


@run_async_test
@pytest.mark.parametrize(
    "error", [TypeError("decoder bug"), RuntimeError("RPC failed"), asyncio.CancelledError()]
)
async def test_feed_unexpected_errors_and_cancellation_propagate(
    monkeypatch: Any, error: Any
) -> None:
    module = importlib.import_module("y.prices.chainlink")
    monkeypatch.setattr(module, "read", AsyncMock(side_effect=error))
    feed = module.Feed(TOKEN, USD, asynchronous=True)
    with pytest.raises(type(error)):
        await feed.get_price(BLOCK)


@run_async_test
async def test_wrapper_dead_ends_do_not_retry_edges_in_other_prefixes(monkeypatch: Any) -> None:
    tokens = [f"0x{i:040x}" for i in range(100, 109)]
    wrappers = [f"0x{i:040x}" for i in range(200, 208)]
    pools = [
        market(f"pool-{level}-{choice}", first=token, second=wrapper)
        for level, (token, wrapper) in enumerate(zip(tokens, wrappers))
        for choice in range(2)
    ]
    service, seen, _ = graph(monkeypatch, pools)
    monkeypatch.setattr(service, "redeem", QuoteService.redeem.__get__(service))
    redemptions: Counter[str] = Counter()

    async def redeem(asset: QuoteAsset, *args: Any) -> Any:
        if asset.token not in wrappers:
            return
        redemptions[asset.token] += 1
        output = replace(asset, token=tokens[wrappers.index(asset.token) + 1])
        yield (
            QuoteStep(
                "redemption",
                "ERC4626",
                asset.token,
                asset,
                (output,),
                "previewRedeem",
                "included",
                "unverified",
            ),
            (),
        )

    monkeypatch.setattr(_redemptions, "redeem", redeem)
    assert await service.price(tokens[0], BLOCK, 1) is None
    attempts = Counter((pool, token, output) for pool, token, _, output in seen)
    assert len(attempts) == 16
    assert set(attempts.values()) == {1}
    assert redemptions == Counter({wrapper: 1 for wrapper in wrappers})


@run_async_test
@pytest.mark.parametrize("sale,redemption,expected", [(2, 1, 2), (1, 2, 2), (2, 2, 2)])
async def test_intermediate_wrapper_compares_both_exits(
    monkeypatch: Any, sale: int, redemption: int, expected: int
) -> None:
    service, seen, _ = graph(
        monkeypatch,
        [market("input", second=CHILD), market("sale", first=CHILD)],
        {"sale": sale},
    )
    monkeypatch.setattr(service, "redeem", QuoteService.redeem.__get__(service))

    async def redeem(asset: QuoteAsset, *args: Any) -> Any:
        if asset.token != CHILD:
            return
        yield (
            QuoteStep(
                "redemption",
                "ERC4626",
                CHILD,
                asset,
                (replace(asset, token=USD, amount=asset.amount * redemption),),
                "previewRedeem",
                "included",
                "unverified",
            ),
            (),
        )

    monkeypatch.setattr(_redemptions, "redeem", redeem)
    result = await service.price(TOKEN, BLOCK, 100)
    assert result is not None and result.quote is not None
    assert result.quote.total_usd == 100 * expected
    assert [row[0] for row in seen] == ["input", "sale"]
    assert result.quote.steps[-1].kind == ("redemption" if redemption > sale else "swap")


@run_async_test
@pytest.mark.parametrize(
    "protocol,fee,spacing", [("Uniswap V3", 3000, None), ("Slipstream", 0, 60)]
)
async def test_v3_quote_encodes_the_protocol_pool_key(
    monkeypatch: Any, protocol: str, fee: int, spacing: int | None
) -> None:
    from y.contracts import Contract

    quote = AsyncMock(return_value=(997000, [], [], 1))
    monkeypatch.setattr(
        Contract,
        "coroutine",
        AsyncMock(return_value=SimpleNamespace(quoteExactInput=SimpleNamespace(coroutine=quote))),
    )
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=6))
    pool = _markets.Market(
        protocol=protocol,
        pool="pool",
        router="quoter",
        fee=fee,
        tick_spacing=spacing,
        tokens=(TOKEN, USD),
        balances=(0, 0),
    )
    result = await _markets.swap(pool, QuoteAsset(TOKEN, 1000000, 6), USD, BLOCK)
    assert result is not None and result.outputs == (QuoteAsset(USD, 997000, 6),)
    path, amount = quote.call_args.args
    assert amount == 1000000
    assert path == bytes.fromhex(TOKEN[2:]) + (fee if spacing is None else spacing).to_bytes(
        3, "big", signed=spacing is not None
    ) + bytes.fromhex(USD[2:])
    assert quote.call_args.kwargs["block_identifier"] == {
        "blockHash": BLOCK.hash,
        "requireCanonical": True,
    }


@run_async_test
async def test_reorg_cannot_cache_number_based_state_under_another_hash(monkeypatch: Any) -> None:
    other = replace(BLOCK, hash="0x" + "cd" * 32)
    current = other
    calls = []

    async def call(transaction: Any, *, block_identifier: Any) -> bytes:
        block_id = block_identifier
        calls.append(block_id)
        if isinstance(block_id, dict):
            assert block_id == {"blockHash": BLOCK.hash, "requireCanonical": True}
            if current != BLOCK:
                raise RuntimeError("block is not canonical")
            return (111).to_bytes(32, "big")
        return (222 if current == other else 111).to_bytes(32, "big")

    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=call)))
    monkeypatch.setattr(_rpc, "state_cache", lambda: cache)
    from y.prices._quote import SharedCache

    cache: SharedCache[Any] = SharedCache(10)
    with pytest.raises(RuntimeError, match="not canonical"):
        await _rpc.state(TOKEN, "totalSupply()(uint256)", BLOCK)
    assert not cache.values
    current = BLOCK
    assert await _rpc.state(TOKEN, "totalSupply()(uint256)", BLOCK) == 111
    assert await _rpc.state(TOKEN, "totalSupply()(uint256)", BLOCK) == 111
    assert len(calls) == 2


@run_async_test
@pytest.mark.parametrize("coin_type", ["uint256", "int128"])
@pytest.mark.parametrize("balance_type", ["uint256", "int128"])
async def test_curve_getter_versions_share_the_same_hash_snapshot(
    monkeypatch: Any, coin_type: str, balance_type: str
) -> None:
    from y.prices._quote import SharedCache

    calls = []
    cache: SharedCache[Any] = SharedCache(10)
    monkeypatch.setattr(_markets, "state_cache", lambda: cache)

    async def read(pool: str, signature: str, block: Any, index: int) -> Any:
        assert block == BLOCK
        calls.append((signature, index))
        if index >= 2:
            raise ContractLogicError("execution reverted")
        if signature == f"coins({coin_type})(address)":
            return (TOKEN, USD)[index]
        if signature == f"balances({balance_type})(uint256)":
            return (1000000, 2000000)[index]
        raise ContractLogicError("execution reverted")

    monkeypatch.setattr(_rpc, "read", read)
    monkeypatch.setattr(_markets, "read", read)
    snapshot = await _markets.curve_pool_state(CHILD, BLOCK)
    assert snapshot is not None
    assert snapshot.tokens == (TOKEN, USD)
    assert snapshot.depth(TOKEN) == 1000000
    assert snapshot.depth(USD) == 2000000
    count = len(calls)
    assert await _markets.curve_pool_state(CHILD, BLOCK) == snapshot
    assert len(calls) == count


@run_async_test
async def test_curve_getter_detection_propagates_rpc_failure(monkeypatch: Any) -> None:
    from y.prices._quote import SharedCache

    cache: SharedCache[Any] = SharedCache(10)
    monkeypatch.setattr(_markets, "state_cache", lambda: cache)
    monkeypatch.setattr(_rpc, "read", AsyncMock(side_effect=RuntimeError("RPC failed")))
    with pytest.raises(RuntimeError, match="RPC failed"):
        await _markets.curve_pool_state(CHILD, BLOCK)
    assert not cache.values


@run_async_test
async def test_terminal_feed_and_values_use_the_same_fork_hash(monkeypatch: Any) -> None:
    import importlib

    from tests.test_pricing_correctness import instance

    module = importlib.import_module("y.prices.chainlink")
    oracle = instance(module.Chainlink)
    oracle.asynchronous = True
    oracle.registry = "0x0000000000000000000000000000000000000200"
    oracle._feeds = []
    oracle._feeds_from_events = None
    other = replace(BLOCK, hash="0x" + "cd" * 32)
    calls = []
    monkeypatch.setattr(module, "deployed", AsyncMock(return_value=True))

    async def read(contract: str, signature: str, block: Any, *args: Any) -> Any:
        calls.append((contract.lower(), signature, block.hash))
        if signature.startswith("getFeed"):
            return TOKEN if block == BLOCK else CHILD
        if signature.startswith("latestTimestamp"):
            return BLOCK.timestamp
        if signature.startswith("latestAnswer"):
            return 100000000 if block == BLOCK else 200000000
        assert signature == "decimals()(uint256)"
        return 8

    monkeypatch.setattr(module, "read", read)
    monkeypatch.setattr(_rpc, "read", read)
    assert await oracle.get_price(USD, BLOCK, sync=False) == 1
    assert await oracle.get_price(USD, other, sync=False) == 2
    count = len(calls)
    assert await oracle.get_price(USD, BLOCK, sync=False) == 1
    assert len(calls) == count
    for contract, signature, block_hash in calls:
        if not signature.startswith("getFeed"):
            assert contract == (TOKEN if block_hash == BLOCK.hash else CHILD)
    assert {block_hash for _, _, block_hash in calls} == {BLOCK.hash, other.hash}


@run_async_test
async def test_cached_quote_still_requires_a_canonical_block(monkeypatch: Any) -> None:
    service, seen, _ = graph(monkeypatch, [market("sale")])
    assert await service.price(TOKEN, BLOCK, 100) is not None
    monkeypatch.setattr(type(BLOCK), "verify", AsyncMock(side_effect=RuntimeError("block changed")))
    with pytest.raises(RuntimeError, match="block changed"):
        await service.price(TOKEN, BLOCK, 100)
    assert len(seen) == 1


@run_async_test
@pytest.mark.parametrize("response", ["empty", "invalid_jump"])
@pytest.mark.parametrize("viable,fail_to_none", [(True, False), (False, True), (False, False)])
async def test_unavailable_v1_rpc_quote_uses_normal_fallback(
    monkeypatch: Any, viable: bool, fail_to_none: bool, response: str
) -> None:
    from y.constants import EEE_ADDRESS
    from y.exceptions import yPriceMagicError
    from y.prices import magic

    exchange = "0x0000000000000000000000000000000000007500"
    router = "0x0000000000000000000000000000000000007501"
    pools = [market(exchange, second=EEE_ADDRESS.lower(), depth=2, protocol="Uniswap V1")]
    if viable:
        pools.append(replace(market("later", depth=1), router=router))
    service, _, _ = graph(monkeypatch, pools)
    monkeypatch.setattr(_routing, "swap", _markets.swap)
    monkeypatch.setattr(_routing, "quote_service", lambda: service)
    monkeypatch.setattr(_rpc.BlockRef, "resolve", AsyncMock(return_value=BLOCK))
    monkeypatch.setattr(magic, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("TOKEN")))
    seen = []

    async def rpc(transaction: dict[str, Any], *, block_identifier: Any) -> bytes:
        assert block_identifier == BLOCK.identifier
        target = transaction["to"].lower()
        if target == USD:
            return encode(["uint8"], [6])
        seen.append(target)
        if target == exchange:
            assert transaction["data"] == keccak(text="getTokenToEthInputPrice(uint256)")[
                :4
            ] + encode(["uint256"], [1000001])
            if response == "invalid_jump":
                raise ValueError({"code": -32003, "message": "EVM error: InvalidJump"})
            return b""
        assert target == router
        assert transaction["data"] == keccak(text="getAmountsOut(uint256,address[])")[:4] + encode(
            ["uint256", "address[]"], [1000001, [TOKEN, USD]]
        )
        return encode(["uint256[]"], [[1000001, 997003]])

    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=rpc)))
    lookup: Any = magic.get_price
    if not viable and not fail_to_none:
        with pytest.raises(yPriceMagicError):
            await lookup(TOKEN, BLOCK.number, amount=Decimal("1.000001"), sync=False)
    else:
        result = await lookup(
            TOKEN,
            BLOCK.number,
            amount=Decimal("1.000001"),
            fail_to_None=fail_to_none,
            sync=False,
        )
        if viable:
            assert result is not None and result.quote is not None
            assert result.quote.outputs == (QuoteAsset(USD, 997003, 6),)
            assert result.quote.total_usd == Decimal("0.997003")
            assert [step.contract for step in result.quote.steps] == ["later"]
            assert result.quote.steps[0].fees == "DEX fees included in native quote"
        else:
            assert result is None
    assert seen == ([exchange, router] if viable else [exchange])


@run_async_test
@pytest.mark.parametrize(
    "error", [TypeError("bad decoder"), RuntimeError("RPC failed"), asyncio.CancelledError()]
)
async def test_v1_unexpected_rpc_errors_propagate(monkeypatch: Any, error: BaseException) -> None:
    from y.constants import EEE_ADDRESS

    rpc = AsyncMock(side_effect=error)
    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=rpc)))
    pool = market(TOKEN, second=EEE_ADDRESS.lower(), protocol="Uniswap V1")
    with pytest.raises(type(error)) as raised:
        await _markets.swap(pool, QuoteAsset(TOKEN, 1000001, 6), EEE_ADDRESS.lower(), BLOCK)
    assert raised.value is error
