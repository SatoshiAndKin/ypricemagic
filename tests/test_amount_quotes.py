"""Behavior tests for the public amount API and native liquidity routing."""

import asyncio
from contextlib import aclosing
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from web3.exceptions import ContractLogicError

from tests.test_pricing_correctness import run_async_test
from y.datatypes import PriceResult, PriceStep, QuoteAsset, QuoteStep, UsdPrice
from y.prices import _markets, _redemptions, _routing, magic
from y.prices._markets import Market
from y.prices._quote import SharedCache, bounded_map, to_base_units, validate_amount
from y.prices._routing import QuoteService
from y.prices._rpc import BlockRef

TOKEN = "0x0000000000000000000000000000000000000101"
CHILD = "0x0000000000000000000000000000000000000102"
USD = "0x0000000000000000000000000000000000000103"
BLOCK = BlockRef(1, 15_000_000, "0x" + "ab" * 32, 1_658_000_000)


def market(
    pool: Any,
    first: Any = TOKEN,
    second: Any = USD,
    depth: Any = 1000,
    protocol: Any = "Uniswap V2",
) -> Any:
    return Market(protocol, pool, (first, second), (depth, depth), "router")


def graph(monkeypatch: Any, pools: Any, rates: Any = None) -> Any:
    service = QuoteService()
    rates = rates or {}
    seen = []

    async def discover(token: Any, block: Any) -> Any:
        assert block == BLOCK
        return tuple(
            sorted(
                (p for p in pools if token in p.tokens),
                key=lambda p: (-p.depth(token), p.protocol, p.pool),
            )
        )

    async def swap(pool: Any, asset: Any, output: Any, block: Any) -> Any:
        seen.append((pool.pool, asset.token, asset.amount, output))
        rate = rates.get(pool.pool, 1)
        if isinstance(rate, Exception):
            raise rate
        amount = int(asset.amount * rate)
        if amount <= 0:
            return None
        return QuoteStep(
            "swap",
            pool.protocol,
            pool.pool,
            asset,
            (QuoteAsset(output, amount, 6),),
            "native quote",
            "included",
            "native limits",
        )

    async def usd(token: Any, block: Any) -> Any:
        return (
            PriceResult(UsdPrice(1), [PriceStep(token, UsdPrice(1), "historical USD")])
            if token == USD
            else None
        )

    discovery = AsyncMock(side_effect=discover)
    monkeypatch.setattr(_routing, "discover", discovery)
    monkeypatch.setattr(_routing, "swap", swap)
    monkeypatch.setattr(_routing, "state", AsyncMock(return_value=6))
    monkeypatch.setattr(BlockRef, "verify", AsyncMock())
    monkeypatch.setattr(service, "usd", usd)
    monkeypatch.setattr(service, "redeem", AsyncMock(return_value=None))
    monkeypatch.setattr(service, "explicit", AsyncMock(return_value=None))
    return service, seen, discovery


async def first_redemption(*args: Any) -> Any:
    async with aclosing(_redemptions.redeem(*args)) as candidates:
        return await anext(candidates, None)


@pytest.mark.parametrize(
    "amount", [0, -1, Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_amount_rejects_invalid_values(amount: Any) -> None:
    with pytest.raises(ValueError):
        validate_amount(amount)


@pytest.mark.parametrize("amount", [1.0, True, "1000", None])
def test_amount_rejects_inexact_or_wrong_types(amount: Any) -> None:
    with pytest.raises(TypeError):
        validate_amount(amount)


def test_base_units_preserve_large_exact_decimal_and_integer_tokens() -> None:
    assert to_base_units(1000, 6) == 1_000_000_000
    assert to_base_units(Decimal("1.000001"), 6) == 1_000_001
    amount = Decimal("123456789012345678901234567890.123456789012345678")
    raw = 123456789012345678901234567890123456789012345678
    assert to_base_units(amount, 18) == raw
    assert QuoteAsset(TOKEN, raw, 18).readable == amount
    with pytest.raises(ValueError, match="exactly"):
        to_base_units(Decimal("0.0000001"), 6)
    with pytest.raises(ValueError, match="uint256"):
        to_base_units(2**256, 0)


@run_async_test
async def test_deepest_pool_wins_even_when_shallow_quote_is_higher(monkeypatch: Any) -> None:
    service, seen, _ = graph(
        monkeypatch,
        [market("shallow", depth=1), market("deep", depth=2)],
        {"shallow": 9, "deep": 2},
    )
    result = await service.price(TOKEN, BLOCK, 1000)
    assert float(result) == 2
    assert result.quote.input.amount == 10**9
    assert result.quote.outputs == (QuoteAsset(USD, 2 * 10**9, 6),)
    assert result.quote.total_usd == 2000
    assert seen == [("deep", TOKEN, 10**9, USD)]


@run_async_test
async def test_stable_protocol_and_pool_ties(monkeypatch: Any) -> None:
    service, seen, _ = graph(
        monkeypatch,
        [
            market("b", protocol="Curve"),
            market("c", protocol="Balancer V2"),
            market("a", protocol="Balancer V2"),
        ],
    )
    await service.price(TOKEN, BLOCK, 1)
    assert seen == [("a", TOKEN, 10**6, USD)]


@run_async_test
@pytest.mark.parametrize("failure", [0, ContractLogicError("execution reverted")])
async def test_expected_failure_falls_back_without_revisiting_edges(
    monkeypatch: Any, failure: Any
) -> None:
    service, seen, _ = graph(
        monkeypatch, [market("bad", depth=5), market("good", depth=1)], {"bad": failure, "good": 3}
    )
    result = await service.price(TOKEN, BLOCK, 2)
    assert float(result) == 3
    assert [item[0] for item in seen] == ["bad", "good"]


@run_async_test
async def test_dead_end_falls_back_mixes_dexes_and_forwards_exact_output(monkeypatch: Any) -> None:
    dead = "0x0000000000000000000000000000000000000104"
    service, seen, discovery = graph(
        monkeypatch,
        [
            market("dead", second=dead, depth=100),
            market("first", second=CHILD, depth=90),
            market("second", first=CHILD, protocol="Curve"),
        ],
        {"first": Decimal("0.997"), "second": 2},
    )
    result = await service.price(TOKEN, BLOCK, Decimal("1.000001"))
    assert seen == [
        ("dead", TOKEN, 1000001, dead),
        ("first", TOKEN, 1000001, CHILD),
        ("second", CHILD, 997000, USD),
    ]
    assert result.quote.total_usd == Decimal("1.994")
    assert [s.protocol for s in result.quote.steps] == ["Uniswap V2", "Curve"]
    assert discovery.await_count == 3


@run_async_test
async def test_exclusions_and_cycles_apply_at_every_hop(monkeypatch: Any) -> None:
    service, seen, _ = graph(
        monkeypatch,
        [
            market("first", second=CHILD),
            market("cycle", first=CHILD, second=TOKEN, depth=2000),
            market("excluded", first=CHILD),
            market("last", first=CHILD, depth=1),
        ],
    )
    result = await service.price(TOKEN, BLOCK, 1, ignored=frozenset({"excluded", "cycle"}))
    assert [s.contract for s in result.quote.steps] == ["first", "last"]
    assert len({s.contract for s in result.quote.steps}) == 2
    assert [s.input.token for s in result.quote.steps] == [TOKEN, CHILD]


@run_async_test
@pytest.mark.parametrize("swaps,available", [(11, True), (12, False)])
async def test_eleven_swap_ceiling(monkeypatch: Any, swaps: Any, available: Any) -> None:
    tokens = [TOKEN, *[f"0x{i:040x}" for i in range(1000, 1000 + swaps - 1)], USD]
    service, seen, _ = graph(
        monkeypatch,
        [market(f"pool{i}", first=a, second=b) for i, (a, b) in enumerate(zip(tokens, tokens[1:]))],
    )
    result = await service.price(TOKEN, BLOCK, 1)
    assert (result is not None) is available
    assert len(seen) == 11


@run_async_test
async def test_unexpected_error_is_not_fallback(monkeypatch: Any) -> None:
    service, seen, _ = graph(
        monkeypatch,
        [market("bad", depth=2000), market("fallback")],
        {"bad": RuntimeError("RPC failure")},
    )
    with pytest.raises(RuntimeError, match="RPC failure"):
        await service.price(TOKEN, BLOCK, 1)
    assert len(seen) == 1


@run_async_test
async def test_cache_keys_amount_hash_mode_exclusions_and_dependencies(monkeypatch: Any) -> None:
    service, seen, discovery = graph(monkeypatch, [market("pool")])
    first = await service.price(TOKEN, BLOCK, 1)
    first.path[0].source = "caller edit"
    copy = await service.price(TOKEN, BLOCK, Decimal(1))
    assert copy.path[0].source == "Liquidity-based sale estimate"
    await service.price(TOKEN, BLOCK, 2)
    await service.price(TOKEN, BLOCK, None)
    await service.price(TOKEN, BLOCK, 1, ignored=frozenset({"unrelated"}))
    await service.price(TOKEN, BLOCK, 1, dependencies=((CHILD, BLOCK.number),))
    await service.price(TOKEN, BLOCK, 1, skip_cache=True)
    assert len(seen) == 6
    assert discovery.await_count == 1
    assert len(service.result_cache.values) == 5


@run_async_test
async def test_shared_caller_cancellation_and_last_waiter_cleanup() -> None:
    cache: SharedCache[int] = SharedCache(2)
    entered, release, cleaned = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def factory() -> Any:
        nonlocal calls
        calls += 1
        entered.set()
        try:
            await release.wait()
            return 42
        finally:
            cleaned.set()

    first = asyncio.create_task(cache.get("key", factory))
    second = asyncio.create_task(cache.get("key", factory))
    await entered.wait()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not cleaned.is_set()
    release.set()
    assert await second == 42
    assert calls == 1 and not cache.flights
    entered.clear()
    release.clear()
    cleaned.clear()
    only = asyncio.create_task(cache.get("other", factory))
    await entered.wait()
    only.cancel()
    with pytest.raises(asyncio.CancelledError):
        await only
    assert cleaned.is_set() and not cache.flights


@run_async_test
async def test_bounded_worker_pool_drains_on_cancellation() -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    active = 0
    peak = 0

    async def work(item: Any) -> Any:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 64:
            entered.set()
        try:
            await release.wait()
            return item
        finally:
            active -= 1

    task = asyncio.create_task(bounded_map(work, range(10000)))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert peak == 64 and active == 0


@run_async_test
async def test_public_amount_bypasses_oracles_and_numeric_database(monkeypatch: Any) -> None:
    service, _, _ = graph(monkeypatch, [market("pool")])
    monkeypatch.setattr(_routing, "quote_service", lambda: service)
    monkeypatch.setattr(BlockRef, "resolve", AsyncMock(return_value=BLOCK))
    spot = AsyncMock(side_effect=AssertionError("spot lookup used for amount"))
    monkeypatch.setattr(magic, "_get_price", spot)
    from y._db.utils import price as db

    monkeypatch.setattr(db, "set_price", lambda *a: pytest.fail("amount written to spot DB"))
    result = await cast(Any, magic.get_price)(TOKEN, BLOCK.number, amount=1000, sync=False)
    assert result.quote.input.amount == 10**9
    spot.assert_not_awaited()


@run_async_test
async def test_public_batch_preserves_duplicate_tokens_and_checks_lengths_before_rpc(
    monkeypatch: Any,
) -> None:
    rpc = SimpleNamespace(eth=SimpleNamespace(block_number=None))
    monkeypatch.setattr(magic, "dank_mids", rpc)
    with pytest.raises(ValueError, match="same length"):
        await cast(Any, magic.get_prices)([TOKEN, TOKEN], amounts=[1], sync=False)
    lookup = AsyncMock(side_effect=lambda token, block, **kw: kw["amount"])
    monkeypatch.setattr(magic, "get_price", lookup)
    assert await cast(Any, magic.get_prices)(
        [TOKEN, TOKEN], BLOCK.number, amounts=[1, 2], sync=False
    ) == [
        1,
        2,
    ]


@run_async_test
@pytest.mark.parametrize("quoted,expected", [(900000, 900000), (None, None), (0, None)])
async def test_erc4626_uses_full_preview_and_never_convert_to_assets(
    monkeypatch: Any, quoted: Any, expected: Any
) -> None:
    async def optional(token: Any, signature: Any, block: Any, *args: Any) -> Any:
        if signature == "asset()(address)":
            return USD
        assert signature == "previewRedeem(uint256)(uint256)"
        assert args == (1000000,)
        return quoted

    monkeypatch.setattr(_redemptions, "optional_read", optional)
    monkeypatch.setattr(_redemptions, "read", AsyncMock(return_value=6))
    result = await first_redemption(QuoteAsset(TOKEN, 1000000, 6), BLOCK, frozenset())
    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert result[0].outputs == (QuoteAsset(USD, expected, 6),)
        assert "fees included" in result[0].fees
        assert "limits" in result[0].limits


@run_async_test
@pytest.mark.parametrize("redemption_value,expected", [(900000, 1), (2000000, 2)])
async def test_compare_direct_sale_with_complete_redemption(
    monkeypatch: Any, redemption_value: Any, expected: Any
) -> None:
    service, _, _ = graph(monkeypatch, [market("pool")])
    monkeypatch.setattr(service, "redeem", QuoteService.redeem.__get__(service))
    step = QuoteStep(
        "redemption",
        "ERC4626",
        TOKEN,
        QuoteAsset(TOKEN, 10**6, 6),
        (QuoteAsset(USD, redemption_value, 6),),
        "previewRedeem",
        "included",
        "unverified",
    )

    async def redeem(*args: Any) -> Any:
        yield step, ()

    monkeypatch.setattr(_redemptions, "redeem", redeem)
    result = await service.price(TOKEN, BLOCK, 1)
    assert float(result) == expected
    assert result.quote.holder_eligibility == "unverified"


@run_async_test
async def test_redemption_aggregates_outputs_and_excludes_withdrawn_pool(monkeypatch: Any) -> None:
    service, seen, _ = graph(
        monkeypatch, [market("withdrawn", first=CHILD, depth=10000), market("other", first=CHILD)]
    )
    monkeypatch.setattr(service, "redeem", QuoteService.redeem.__get__(service))
    step = QuoteStep(
        "redemption",
        "LP",
        "withdrawn",
        QuoteAsset(TOKEN, 10**6, 6),
        (QuoteAsset(CHILD, 500000, 6), QuoteAsset(CHILD, 500000, 6), QuoteAsset(USD, 10**6, 6)),
        "withdraw",
        "included",
        "unverified",
    )

    async def redeem(asset: Any, *args: Any) -> Any:
        if asset.token == TOKEN:
            yield step, ("withdrawn",)

    monkeypatch.setattr(_redemptions, "redeem", redeem)
    result = await service.price(TOKEN, BLOCK, 1)
    assert result.quote.total_usd == 2
    assert result.quote.outputs == (QuoteAsset(USD, 2000000, 6),)
    assert seen == [("other", CHILD, 1000000, USD)]
    child_prices = [float(step.price) for step in result.path if step.token == CHILD]
    assert child_prices == [1.0]


@run_async_test
async def test_balancer_v2_native_query_includes_full_amount_and_signed_deltas(
    monkeypatch: Any,
) -> None:
    pool = replace(market("pool", protocol="Balancer V2"), pool_id=b"a" * 32, router="vault")
    calls = []

    async def read(target: Any, signature: Any, block: Any, *args: Any) -> Any:
        calls.append((target, signature, args))
        if target == USD:
            return 6
        assert args[0] == 0 and args[1] == [(b"a" * 32, 0, 1, 123456789, b"")]
        return [123456789, -123000000]

    monkeypatch.setattr(_markets, "read", read)
    result = await _markets.swap(pool, QuoteAsset(TOKEN, 123456789, 6), USD, BLOCK)
    assert result is not None
    assert result.outputs == (QuoteAsset(USD, 123000000, 6),)
    assert calls[0][1].startswith("queryBatchSwap")


@run_async_test
@pytest.mark.parametrize("cash,available", [(1000000, True), (999999, False)])
async def test_compound_redemption_checks_full_withdrawal_cash(
    monkeypatch: Any, cash: Any, available: Any
) -> None:
    async def optional(token: Any, signature: Any, block: Any, *args: Any) -> Any:
        return {"isCToken()(bool)": True, "underlying()(address)": USD}.get(signature)

    async def read(token: Any, signature: Any, block: Any, *args: Any) -> Any:
        return {
            "comptroller()(address)": "0x3d9819210a31b4961b30ef54be2aed79b9c9cd3b",
            "exchangeRateCurrent()(uint256)": 2 * 10**18,
            "getCash()(uint256)": cash,
            "decimals()(uint8)": 6,
        }[signature]

    monkeypatch.setattr(_redemptions, "optional_read", optional)
    monkeypatch.setattr(_redemptions, "read", read)
    result = await first_redemption(QuoteAsset(TOKEN, 500000, 6), BLOCK, frozenset())
    if available:
        assert result is not None
        assert result[0].outputs == (QuoteAsset(USD, 1000000, 6),)
    else:
        assert result is None


@run_async_test
async def test_public_stablecoin_cached_classification_uses_historical_feed(
    monkeypatch: Any,
) -> None:
    from tests.test_pricing_correctness import Ready
    from y._db.utils import token as db
    from y.prices import utils
    from y.prices.utils import buckets

    monkeypatch.setattr(db, "get_bucket", AsyncMock(return_value="stable usd"))
    check = buckets.check_bucket.__wrapped__
    monkeypatch.setattr(utils, "check_bucket", lambda token, block, **kw: check(token, block))
    monkeypatch.setattr(magic, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("USDC")))
    monkeypatch.setattr(magic, "_get_price_from_api", AsyncMock(return_value=None))
    monkeypatch.setattr(utils, "sense_check", AsyncMock())
    lookup = AsyncMock(side_effect=[Decimal("0.88"), Decimal("1.001")])
    monkeypatch.setattr(magic, "chainlink", SimpleNamespace(get_price=lookup))
    prices = [
        await cast(Any, magic.get_price)(TOKEN, block, skip_cache=True, sync=False)
        for block in (16785000, 16795000)
    ]
    assert [float(price) for price in prices] == [0.88, 1.001]
    assert [call.args[1] for call in lookup.await_args_list] == [16785000, 16795000]


@run_async_test
async def test_native_v2_router_amount_retains_fees(monkeypatch: Any) -> None:
    async def read(target: Any, signature: Any, block: Any, *args: Any) -> Any:
        if signature == "decimals()(uint8)":
            return 6
        assert target == "router" and args == (1000001, [TOKEN, USD])
        return [1000001, 996006]

    monkeypatch.setattr(_markets, "read", read)
    result = await _markets.swap(market("pool"), QuoteAsset(TOKEN, 1000001, 6), USD, BLOCK)
    assert result is not None
    assert result.outputs[0].amount == 996006


@run_async_test
async def test_block_hash_partitions_shared_state_and_results(monkeypatch: Any) -> None:
    service, _, _ = graph(monkeypatch, [market("pool")])
    discovery = AsyncMock(return_value=(market("pool"),))
    monkeypatch.setattr(_routing, "discover", discovery)
    await service.price(TOKEN, BLOCK, 1)
    other = replace(BLOCK, hash="0x" + "cd" * 32)
    await service.price(TOKEN, other, 1)
    assert discovery.await_count == 2
    assert len(service.result_cache.values) == 2


@run_async_test
@pytest.mark.parametrize("idle,available", [(900, True), (899, False)])
async def test_yearn_exit_deducts_locked_profit_and_requires_idle_cash(
    monkeypatch: Any, idle: int, available: bool
) -> None:
    async def optional(token: Any, signature: str, block: Any, *args: Any) -> Any:
        return {"apiVersion()(string)": "0.4.6", "totalIdle()(uint256)": idle}.get(signature)

    async def read(token: Any, signature: str, block: Any, *args: Any) -> Any:
        return {
            "token()(address)": USD,
            "totalSupply()(uint256)": 1000,
            "totalAssets()(uint256)": 2000,
            "lockedProfit()(uint256)": 400,
            "lockedProfitDegradation()(uint256)": 10**16,
            "lastReport()(uint256)": BLOCK.timestamp - 50,
            "decimals()(uint8)": 6,
        }[signature]

    monkeypatch.setattr(_redemptions, "optional_read", optional)
    monkeypatch.setattr(_redemptions, "read", read)
    result = await first_redemption(QuoteAsset(TOKEN, 500, 6), BLOCK, frozenset())
    if available:
        assert result is not None and result[0].outputs == (QuoteAsset(USD, 900, 6),)
    else:
        assert result is None


@run_async_test
@pytest.mark.parametrize("shutdown", [False, True])
async def test_convex_checks_staker_backing_and_shutdown_custody(
    monkeypatch: Any, shutdown: bool
) -> None:
    booster = "0xf403c135812408bfbe8713b5a23a04b3d48aae31"
    staker, gauge = "staker", "gauge"
    balances = []

    async def optional(token: Any, signature: str, block: Any, *args: Any) -> Any:
        return booster if signature == "operator()(address)" else None

    async def read(token: Any, signature: str, block: Any, *args: Any) -> Any:
        if signature == "poolLength()(uint256)":
            return 1
        if signature.startswith("poolInfo("):
            return USD, TOKEN, gauge, "rewards", "stash", shutdown
        if signature == "staker()(address)":
            return staker
        if signature == "decimals()(uint8)":
            return 6
        assert signature == "balanceOf(address)(uint256)"
        balances.append((token, args[0]))
        return 1000 if token == gauge or args[0] == booster else 0

    monkeypatch.setattr(_redemptions, "optional_read", optional)
    monkeypatch.setattr(_redemptions, "read", read)
    result = await first_redemption(QuoteAsset(TOKEN, 1000, 6), BLOCK, frozenset())
    assert result is not None and result[0].outputs == (QuoteAsset(USD, 1000, 6),)
    assert (
        balances == [(USD, booster)] if shutdown else balances == [(gauge, staker), (USD, staker)]
    )
    assert await first_redemption(QuoteAsset(TOKEN, 1000, 6), BLOCK, frozenset([staker])) is None


@run_async_test
@pytest.mark.parametrize("value", ["1e-400", "1e400", "NaN"])
async def test_sale_result_rejects_unrepresentable_usd_price(monkeypatch: Any, value: str) -> None:
    service, _, _ = graph(monkeypatch, [market("pool")])
    estimate = _routing.Estimate((), Decimal(value), (), (), frozenset())
    monkeypatch.setattr(service, "estimate", AsyncMock(return_value=estimate))
    assert await service.price(TOKEN, BLOCK, 1) is None
