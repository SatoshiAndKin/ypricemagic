"""Historical inventories are bounded by pool count as well as cache keys."""

import asyncio
import gc
from collections import Counter
from dataclasses import replace
from typing import Any
from weakref import ref

import pytest

from tests.test_amount_quotes import BLOCK
from tests.test_pricing_correctness import TOKEN, run_async_test
from y.prices import _routing
from y.prices._markets import Market
from y.prices._routing import QuoteService


@run_async_test
async def test_large_inventories_evict_least_recent_block(monkeypatch: Any) -> None:
    service = QuoteService()
    blocks = [replace(BLOCK, hash=f"0x{index:064x}") for index in range(1, 4)]
    sizes = dict(zip((block.hash for block in blocks), (400_000, 400_000, 300_000)))
    calls: Counter[str] = Counter()

    class TrackedMarket(Market):
        """Allow weak references without changing production Market storage."""

    market = TrackedMarket("Uniswap V2", "pool", (TOKEN, "output"), (123, 456))
    references = []

    async def discover(token: str, block: Any) -> tuple[Market, ...]:
        assert token == TOKEN
        calls[block.hash] += 1
        value = replace(market)
        references.append(ref(value))
        return (value,) * sizes[block.hash]

    monkeypatch.setattr(_routing, "discover", discover)
    first = await service.markets(TOKEN, blocks[0], False)
    second = await service.markets(TOKEN, blocks[1], False)
    assert first == (market,) * 400_000
    assert second == (market,) * 400_000
    assert await service.markets(TOKEN, blocks[0], False) is first
    third = await service.markets(TOKEN, blocks[2], False)
    assert third == (market,) * 300_000
    assert sum(map(len, service.market_cache.values.values())) == 700_000
    assert await service.markets(TOKEN, blocks[0], False) is first
    reloaded = await service.markets(TOKEN, blocks[1], False)
    assert reloaded == second and reloaded is not second
    assert calls == {blocks[0].hash: 1, blocks[1].hash: 2, blocks[2].hash: 1}
    assert sum(map(len, service.market_cache.values.values())) == 800_000
    assert not service.market_cache.flights
    del second, third
    gc.collect()
    assert [reference() is not None for reference in references] == [True, False, False, True]


@run_async_test
async def test_oversized_inventory_is_shared_but_not_retained(monkeypatch: Any) -> None:
    service = QuoteService()
    large_block = replace(BLOCK, hash="0x" + "cd" * 32)
    market = Market("Uniswap V2", "pool", (TOKEN, "output"), (123, 456))
    entered, release = asyncio.Event(), asyncio.Event()
    calls: Counter[str] = Counter()

    async def discover(token: str, block: Any) -> tuple[Market, ...]:
        assert token == TOKEN
        calls[block.hash] += 1
        if block == large_block:
            entered.set()
            await release.wait()
            return (market,) * 1_000_001
        return (market,)

    monkeypatch.setattr(_routing, "discover", discover)
    warm = await service.markets(TOKEN, BLOCK, False)
    abandoned = asyncio.create_task(service.markets(TOKEN, large_block, False))
    await entered.wait()
    surviving = asyncio.create_task(service.markets(TOKEN, large_block, False))
    # Both callers enter the actual shared flight before one cancels.
    await asyncio.sleep(0)
    abandoned.cancel()
    with pytest.raises(asyncio.CancelledError):
        await abandoned
    release.set()
    result = await surviving
    assert result == (market,) * 1_000_001
    assert await service.markets(TOKEN, BLOCK, False) is warm
    assert sum(map(len, service.market_cache.values.values())) == 1
    assert tuple(service.market_cache.values.values()) == (warm,)
    again = await service.markets(TOKEN, large_block, False)
    assert again == result and again is not result
    assert calls == {BLOCK.hash: 1, large_block.hash: 2}
    assert not service.market_cache.flights


@run_async_test
async def test_empty_inventories_keep_the_existing_entry_bound(monkeypatch: Any) -> None:
    service = QuoteService()
    calls: Counter[str] = Counter()

    async def discover(token: str, block: Any) -> tuple[Market, ...]:
        calls[block.hash] += 1
        return ()

    monkeypatch.setattr(_routing, "discover", discover)
    blocks = [replace(BLOCK, hash=f"0x{index:064x}") for index in range(4097)]
    for block in blocks:
        assert await service.markets(TOKEN, block, False) == ()
    assert len(service.market_cache.values) == 4096
    assert await service.markets(TOKEN, blocks[-1], False) == ()
    assert await service.markets(TOKEN, blocks[0], False) == ()
    assert calls[blocks[0].hash] == 2
    assert calls[blocks[-1].hash] == 1
    assert sum(calls.values()) == 4098
    assert not service.market_cache.flights
