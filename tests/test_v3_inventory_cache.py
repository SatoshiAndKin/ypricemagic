"""Incremental pool history stays complete and unique across cached queries."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from eth_typing import BlockNumber

from tests.test_amount_quotes import CHILD, TOKEN, USD
from tests.test_pricing_correctness import Ready, run_async_test
from y.prices.dex.uniswap.v3 import UniswapV3, UniswapV3Pool, UniV3Pools


class BufferedPools(UniV3Pools):
    """Supply completed factory events without starting an RPC loader."""

    def _ensure_task(self) -> None:
        pass

    def _wakeup(self) -> None:
        pass


def history(*, loaded: bool = True, checkpoints: bool = False) -> tuple[Any, list[Any]]:
    factory: Any = SimpleNamespace(
        address="0x0000000000000000000000000000000000123450",
        topics={"PoolCreated": "0x" + "11" * 32},
    )
    registry: Any = BufferedPools(factory, asynchronous=True)
    rows = [
        UniswapV3Pool(
            f"0x{0x123460 + index:040x}",
            TOKEN if matching else CHILD,
            USD,
            60,
            3000,
            BlockNumber(block),
            asynchronous=True,
        )
        for index, (block, matching) in enumerate(
            [(10, True), (10, True), (11, False), (12, True), (13, False), (20, True)]
        )
    ]
    if loaded:
        registry._objects = list(rows)
        registry._lock.set(30)
    if checkpoints:
        registry._checkpoints = {10: 2, 12: 4}
    return registry, rows


async def pools_at(registry: Any, block: int) -> list[UniswapV3Pool]:
    router: Any = SimpleNamespace(__pools__=Ready(registry), asynchronous=True)
    return [pool async for pool in UniswapV3.pools_for_token(router, TOKEN, block)]


@run_async_test
@pytest.mark.parametrize("public", [False, True])
@pytest.mark.parametrize("checkpoints", [False, True])
@pytest.mark.parametrize(
    "start,end,indices", [(None, 12, [0, 1, 2, 3]), (11, 12, [2, 3]), (14, 19, [])]
)
async def test_cached_event_ranges_honor_both_inclusive_bounds(
    public: bool, checkpoints: bool, start: int | None, end: int, indices: list[int]
) -> None:
    registry, rows = history(checkpoints=checkpoints)
    iterator = (
        registry.objects(to_block=end, from_block=start)
        if public
        else registry._objects_thru(block=end, from_block=start)
    )
    assert [pool async for pool in iterator] == [rows[index] for index in indices]
    assert registry._objects == rows


@run_async_test
@pytest.mark.parametrize("first,second", [(10, 11), (13, 12)])
async def test_v3_index_handles_adjacent_and_older_blocks(first: int, second: int) -> None:
    registry, rows = history()
    for block in [first, second, 13, 10, 12, 13]:
        expected = [pool for pool in rows if TOKEN in pool and pool._deploy_block <= block]
        assert await pools_at(registry, block) == expected
    assert {
        block: list(pools)
        for block, pools in registry._pools_by_token_cache[TOKEN].items()
        if pools
    } == {10: rows[:2], 12: [rows[3]]}


@run_async_test
async def test_v3_partial_iterator_does_not_hide_other_pools_in_the_same_block() -> None:
    registry, rows = history()
    router: Any = SimpleNamespace(__pools__=Ready(registry), asynchronous=True)
    iterator = UniswapV3.pools_for_token(router, TOKEN, 10)
    assert await anext(iterator) == rows[0]
    try:
        assert await pools_at(registry, 10) == rows[:2]
        assert await pools_at(registry, 13) == [rows[0], rows[1], rows[3]]
    finally:
        # Drain the paused public iterator after observing its partial cache.
        async for _ in iterator:
            pass


@run_async_test
async def test_v3_concurrent_loads_do_not_duplicate_cached_pools() -> None:
    registry, rows = history(loaded=False)
    first = asyncio.create_task(pools_at(registry, 10))
    second = asyncio.create_task(pools_at(registry, 13))
    await asyncio.sleep(0)
    registry._objects = list(rows)
    registry._lock.set(30)
    assert await first == rows[:2]
    assert await second == [rows[0], rows[1], rows[3]]
    assert await pools_at(registry, 10) == rows[:2]
    assert registry._pools_by_token_cache[TOKEN][10] == rows[:2]


@run_async_test
async def test_v3_cancelled_load_can_be_retried_without_missing_pools() -> None:
    registry, rows = history(loaded=False)
    task = asyncio.create_task(pools_at(registry, 13))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    registry._objects = list(rows)
    registry._lock.set(30)
    assert await pools_at(registry, 13) == [rows[0], rows[1], rows[3]]
