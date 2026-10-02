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


@run_async_test
async def test_curve_prefills_provider_history_before_replay(monkeypatch: Any) -> None:
    prefill = AsyncMock()
    monkeypatch.setattr(module, "_prefill_registry_logs", prefill)

    class StopReplay(Exception):
        pass

    class Provider:
        address = module.ADDRESS_PROVIDER

        def __await__(self) -> Any:
            async def replay() -> None:
                prefill.assert_awaited_once_with([module.ADDRESS_PROVIDER])
                raise StopReplay

            return replay().__await__()

    obj = instance(module.CurveRegistry)
    obj.address_provider = Provider()
    with pytest.raises(StopReplay):
        await obj._load_all()


@run_async_test
@pytest.mark.parametrize(
    "dense,cached,expected",
    [(False, 0, [10, 20, 40, 40, 40]), (True, 0, [10] * 13), (False, 1000, [])],
)
async def test_curve_sparse_prefill_grows_and_reuses_completed_disk_coverage(
    monkeypatch: Any, dense: bool, cached: int, expected: list[int]
) -> None:
    from dank_mids import brownie_patch

    from tests.test_pricing_correctness import Ready
    from y._db import common
    from y._db.utils import logs
    from y.utils import _factory_history, _log_ranges

    scopes = [module.ADDRESS_PROVIDER, "0x0000000000000000000000000000000000000101"]
    coverage = {address: cached for address in scopes}
    calls: list[tuple[int, int, int]] = []
    monkeypatch.setattr(brownie_patch, "dank_eth", SimpleNamespace(block_number=Ready(1000)))
    monkeypatch.setattr(module, "contract_creation_block_async", AsyncMock(return_value=1))
    monkeypatch.setattr(_log_ranges, "indexed_chunk_size", lambda: 10)
    monkeypatch.setattr(_log_ranges, "sparse_chunk_ceiling", lambda: 40, raising=False)
    monkeypatch.setattr(
        logs,
        "LogCache",
        lambda address, topics: SimpleNamespace(is_cached_thru=lambda start: coverage[address]),
    )

    async def run(function: Any, *args: Any) -> Any:
        return function(*args)

    monkeypatch.setattr(common, "default_filter_threads", SimpleNamespace(run=run))

    async def scan(
        addresses: Any, topics: Any, start: int, end: int, *, chunk_size: int
    ) -> list[Any]:
        assert addresses == scopes and topics is None
        assert start == min(coverage.values()) + 1
        calls.append((start, end, chunk_size))
        for address in addresses:
            coverage[address] = min(1000, end + 7 * chunk_size)
        return [object()] * (65 if dense else 0)

    monkeypatch.setattr(_factory_history, "factory_logs", scan)
    await module._prefill_registry_logs(scopes)
    assert [c[2] for c in calls] == expected
    assert all(last - first + 1 <= chunk for first, last, chunk in calls)
    assert set(coverage.values()) == {1000}
    await module._prefill_registry_logs(scopes)
    assert len(calls) == len(expected)


@run_async_test
@pytest.mark.parametrize("failure", [TimeoutError("RPC unavailable"), asyncio.CancelledError()])
async def test_curve_sparse_prefill_propagates_failure_without_claiming_coverage(
    monkeypatch: Any, failure: BaseException
) -> None:
    from dank_mids import brownie_patch

    from tests.test_pricing_correctness import Ready
    from y._db import common
    from y._db.utils import logs
    from y.utils import _factory_history

    monkeypatch.setattr(brownie_patch, "dank_eth", SimpleNamespace(block_number=Ready(1000)))
    monkeypatch.setattr(module, "contract_creation_block_async", AsyncMock(return_value=1))
    monkeypatch.setattr(
        logs, "LogCache", lambda *args: SimpleNamespace(is_cached_thru=lambda start: 0)
    )

    async def run(function: Any, *args: Any) -> Any:
        return function(*args)

    monkeypatch.setattr(common, "default_filter_threads", SimpleNamespace(run=run))
    scan = AsyncMock(side_effect=failure)
    monkeypatch.setattr(_factory_history, "factory_logs", scan)
    with pytest.raises(type(failure)) as raised:
        await module._prefill_registry_logs([module.ADDRESS_PROVIDER])
    assert raised.value is failure
    scan.assert_awaited_once()
