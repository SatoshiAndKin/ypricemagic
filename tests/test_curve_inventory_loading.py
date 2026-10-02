"""Curve readiness batches coin reads without losing mapping or error boundaries."""

import asyncio
import importlib
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.test_pricing_correctness import instance, run_async_test

module = importlib.import_module("y.prices.stable_swap.curve")


@dataclass(eq=False)
class Pool:
    address: str
    reader: Any

    @property
    def __coins__(self) -> Any:
        return self.reader(self.address)


def registry(monkeypatch: Any, pools: dict[str, Pool]) -> Any:
    obj = instance(module.CurveRegistry)
    obj.factories = {"first": set(pools), "duplicate": set(pools)}
    monkeypatch.setattr(module, "CurvePool", pools.__getitem__)
    monkeypatch.setattr(module.CurveRegistry, "load_all", AsyncMock())
    return obj


@run_async_test
async def test_curve_coin_index_batches_reads_and_deduplicates(monkeypatch: Any) -> None:
    active = peak = 0
    calls: list[str] = []
    concurrent = asyncio.Event()

    async def read(address: str) -> list[Any]:
        nonlocal active, peak
        calls.append(address)
        active += 1
        peak = max(peak, active)
        if active >= 2:
            concurrent.set()
        try:
            await asyncio.wait_for(concurrent.wait(), 1)
            await asyncio.sleep(0)
            return [SimpleNamespace(address="shared"), SimpleNamespace(address=address)]
        finally:
            active -= 1

    pools = {str(i): Pool(str(i), read) for i in range(97)}
    obj = registry(monkeypatch, pools)
    result = await obj.__coin_to_pools__
    assert 1 < peak <= 32
    assert active == 0
    assert sorted(calls) == sorted(pools)
    assert set(result["shared"]) == set(pools.values())
    for address, pool in pools.items():
        assert result[address] == [pool]


@run_async_test
async def test_curve_coin_index_propagates_read_errors(monkeypatch: Any) -> None:
    failure = RuntimeError("coin metadata unavailable")

    async def read(address: str) -> list[Any]:
        raise failure

    obj = registry(monkeypatch, {"first": Pool("first", read)})
    with pytest.raises(RuntimeError, match="coin metadata unavailable"):
        await obj.__coin_to_pools__


@run_async_test
async def test_curve_coin_index_cancels_pending_reads(monkeypatch: Any) -> None:
    entered = asyncio.Event()
    cancelled: list[str] = []

    async def read(address: str) -> list[Any]:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(address)
            raise
        return []

    pools = {str(i): Pool(str(i), read) for i in range(4)}
    obj = registry(monkeypatch, pools)

    async def load() -> Any:
        return await module.CurveRegistry.__dict__["coin_to_pools"].__wrapped__(obj)

    task = asyncio.create_task(load())
    await asyncio.wait_for(entered.wait(), 1)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert set(cancelled) == set(pools)
