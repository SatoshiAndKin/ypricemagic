"""History scans must bound pending work and checkpoint only complete prefixes."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from y._db.common import Filter
from y import ENVIRONMENT_VARIABLES as ENVS


def scanner(fetch: AsyncMock, *, limit: int | None = None) -> Any:
    return SimpleNamespace(
        _chunk_size=10,
        _chunks_per_batch=limit,
        _verbose=False,
        _fetch_range_wrapped=fetch,
        _insert_chunk=Mock(),
        _extend=AsyncMock(),
        _set_lock=AsyncMock(),
    )


@pytest.mark.asyncio_cooperative
async def test_scan_bounds_work_and_keeps_results_in_block_order() -> None:
    window_size = int(ENVS.GETLOGS_DOP)
    release = asyncio.Event()
    later_finished = asyncio.Event()
    calls: list[tuple[int, int]] = []

    async def fetch(i: int, start: int, end: int, debug: bool) -> tuple[int, int, list[int]]:
        calls.append((start, end))
        if i == 0:
            await release.wait()
        elif i == window_size - 1:
            later_finished.set()
        return i, end, [start]

    state = scanner(AsyncMock(side_effect=fetch))
    task = asyncio.ensure_future(Filter._load_range(state, 0, 999))
    try:
        await asyncio.wait_for(later_finished.wait(), 1)
        await asyncio.sleep(0)
        assert calls == [(start, start + 9) for start in range(0, window_size * 10, 10)]
        state._insert_chunk.assert_not_called()
        state._set_lock.assert_not_awaited()
    finally:
        release.set()
        await asyncio.wait_for(task, 1)
    assert calls == [(start, start + 9) for start in range(0, 1000, 10)]
    assert [call.args[0] for call in state._extend.await_args_list] == [
        [start] for start in range(0, 1000, 10)
    ]
    assert [call.args[2] for call in state._insert_chunk.call_args_list] == list(range(9, 1000, 10))
    checkpoints = [call.args[0] for call in state._set_lock.await_args_list]
    assert checkpoints == sorted(set(checkpoints))
    assert checkpoints[-1] == 999


@pytest.mark.asyncio_cooperative
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_or_cancelled_scan_joins_pending_fetches(cancel: bool) -> None:
    window_size = int(ENVS.GETLOGS_DOP)
    started = asyncio.Event()
    release = asyncio.Event()
    pending_cancelled = asyncio.Event()

    async def fetch(i: int, start: int, end: int, debug: bool) -> tuple[int, int, list[int]]:
        if i == 0:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                pending_cancelled.set()
        await release.wait()
        raise ValueError("RPC failed")

    state = scanner(AsyncMock(side_effect=fetch))
    task = asyncio.ensure_future(Filter._load_range(state, 0, 999))
    await asyncio.wait_for(started.wait(), 1)
    expected: type[BaseException]
    if cancel:
        task.cancel()
        expected = asyncio.CancelledError
    else:
        release.set()
        expected = ValueError
    with pytest.raises(expected):
        await asyncio.wait_for(task, 1)
    assert pending_cancelled.is_set()
    state._insert_chunk.assert_not_called()
    state._set_lock.assert_not_awaited()
    assert state._fetch_range_wrapped.await_count == window_size


@pytest.mark.asyncio_cooperative
async def test_explicit_chunk_limit_keeps_exact_scan_boundary() -> None:
    async def fetch(i: int, start: int, end: int, debug: bool) -> tuple[int, int, list[int]]:
        return i, end, []

    state = scanner(AsyncMock(side_effect=fetch), limit=2)
    await Filter._load_range(state, 7, 100)
    assert [call.args[1:3] for call in state._fetch_range_wrapped.await_args_list] == [
        (7, 16),
        (17, 26),
    ]
    assert state._set_lock.await_args.args == (26,)
