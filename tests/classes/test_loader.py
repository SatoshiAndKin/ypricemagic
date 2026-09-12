"""Readiness must preserve loading failures and isolate cancelled callers."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from y.classes.common import _EventsLoader, _Loader


class ControlledLoader(_Loader):
    operation: AsyncMock

    async def _load(self) -> None:
        await self.operation()


def loader_instance(cls: type[_Loader], operation: Any) -> Any:
    loader: Any = object.__new__(cls)
    loader.address = "0x0000000000000000000000000000000000000001"
    loader.asynchronous = True
    loader._Loader__task = None
    loader._init_block = 123
    loader.operation = operation
    return loader


@pytest.mark.asyncio_cooperative
async def test_failure_reaches_current_and_later_callers() -> None:
    release = asyncio.Event()
    failure = RuntimeError("factory load failed")

    async def fail() -> None:
        await release.wait()
        raise failure

    loader = loader_instance(ControlledLoader, AsyncMock(side_effect=fail))
    first, second = loader.loaded, loader.loaded
    release.set()
    results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 1)
    assert results == [failure, failure]
    with pytest.raises(RuntimeError, match="factory load failed"):
        await loader.loaded
    loader.operation.assert_awaited_once()


@pytest.mark.asyncio_cooperative
async def test_cancelled_caller_does_not_cancel_shared_load() -> None:
    release = asyncio.Event()
    loader = loader_instance(ControlledLoader, AsyncMock(side_effect=release.wait))
    first, second = loader.loaded, loader.loaded
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not loader._task.cancelled()
    release.set()
    assert await asyncio.wait_for(second, 1) is True
    assert await loader.loaded is True
    loader.operation.assert_awaited_once()


@pytest.mark.asyncio_cooperative
async def test_cancelled_loader_reaches_all_callers() -> None:
    loader = loader_instance(ControlledLoader, AsyncMock(side_effect=asyncio.Event().wait))
    first, second = loader.loaded, loader.loaded
    loader._task.cancel()
    results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 1)
    assert all(isinstance(result, asyncio.CancelledError) for result in results)


class EventLoader(_EventsLoader):
    stream: Any

    @property
    def _events(self) -> Any:
        return self.stream


@pytest.mark.asyncio_cooperative
async def test_event_loader_waits_for_event_processing() -> None:
    release = asyncio.Event()
    blocks = []

    async def events(block: int) -> AsyncIterator[str]:
        blocks.append(block)
        yield "pool added"

    async def processed(block: int) -> None:
        await release.wait()

    loader = loader_instance(EventLoader, None)
    loader.stream = SimpleNamespace(
        events=events, _lock=SimpleNamespace(wait_for=AsyncMock(side_effect=processed))
    )
    waiting = loader.loaded
    await asyncio.sleep(0)
    assert not waiting.done()
    release.set()
    assert await asyncio.wait_for(waiting, 1) is True
    assert blocks == [123]
    loader.stream._lock.wait_for.assert_awaited_once_with(123)


@pytest.mark.asyncio_cooperative
async def test_event_loader_propagates_stream_failure() -> None:
    async def events(block: int) -> AsyncIterator[str]:
        raise ValueError("event decode failed")
        yield

    loader = loader_instance(EventLoader, None)
    loader.stream = SimpleNamespace(events=events)
    with pytest.raises(ValueError, match="event decode failed"):
        await asyncio.wait_for(loader.loaded, 1)
