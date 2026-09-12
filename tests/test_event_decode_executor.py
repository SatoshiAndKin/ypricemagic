"""Database writes must not block event decoding and delivery."""

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from a_sync.executor import AsyncThreadPoolExecutor

from y.utils import events


class Processed(events.ProcessedEvents[int]):
    def _process_event(self, event: Any) -> int:
        return int(event.value)


@pytest.mark.asyncio_cooperative
@pytest.mark.parametrize("processed", [False, True])
async def test_decode_does_not_wait_for_database_writer(
    monkeypatch: pytest.MonkeyPatch, processed: bool
) -> None:
    executor = AsyncThreadPoolExecutor(1)
    started = threading.Event()
    release = threading.Event()

    def write() -> None:
        started.set()
        assert release.wait(10)

    writer = executor.submit(write)
    try:
        assert await asyncio.to_thread(started.wait, 5)
        loader = (Processed if processed else events.Events)(
            addresses=[], topics=[], from_block=1, executor=executor
        )
        decoded: list[Any] = [SimpleNamespace(value=7), SimpleNamespace(value=9)]
        logs: list[Any] = [object(), object()]

        def decode(actual: list[Any]) -> list[Any]:
            assert actual is logs
            return decoded

        monkeypatch.setattr(events, "decode_logs", decode)
        await asyncio.wait_for(loader._extend(logs), timeout=1)
        assert loader._objects == ([7, 9] if processed else decoded)
        assert not writer.done()
    finally:
        release.set()
        await writer
        executor.shutdown()
