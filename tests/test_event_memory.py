"""Historical readers retain only the work that their consumers can accept."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from weakref import ReferenceType, ref

import pytest
from dank_mids import BlockSemaphore

from tests.test_pricing_correctness import run_async_test
from y._db import common


@dataclass
class Entry:
    blockNumber: int


class Reader(common.Filter[Entry, Any]):
    def __init__(self, capacity: int = 4, chunks: int | None = None) -> None:
        super().__init__(
            1, chunk_size=1, chunks_per_batch=chunks, semaphore=BlockSemaphore(capacity)
        )
        self.fetched: list[int] = []
        self.processed: list[int] = []
        self.written: list[int] = []
        self.metadata: list[tuple[int, int]] = []
        self.references: list[ReferenceType[Entry]] = []
        self.fetch_gate = asyncio.Event()
        self.process_gate = asyncio.Event()
        self.write_gate = asyncio.Event()
        self.fetch_gate.set()
        self.process_gate.set()
        self.write_gate.set()
        self.entered = asyncio.Event()
        self.active = 0
        self.peak_active = 0
        self.fail_block: int | None = None

    @property
    def cache(self) -> Any:
        return SimpleNamespace(set_metadata=lambda start, end: self.metadata.append((start, end)))

    @property
    def insert_to_db(self) -> Callable[[Entry], None]:
        raise AssertionError("The reader must use bulk writes")

    @property
    def bulk_insert(self) -> Callable[[list[Entry]], Awaitable[None]]:
        return self.write

    async def write(self, entries: list[Entry]) -> None:
        await self.write_gate.wait()
        self.written.extend(entry.blockNumber for entry in entries)

    async def _fetch_range(self, from_block: int, to_block: int) -> list[Entry]:
        assert from_block == to_block
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        self.fetched.append(from_block)
        self.entered.set()
        try:
            await self.fetch_gate.wait()
            if from_block == self.fail_block:
                raise ValueError("historical chunk failed")
            entry = Entry(from_block)
            self.references.append(ref(entry))
            return [entry]
        finally:
            self.active -= 1

    async def _extend(self, entries: list[Entry]) -> None:
        await self.process_gate.wait()
        self.processed.extend(entry.blockNumber for entry in entries)


@pytest.fixture
def metadata_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run(function: Callable[..., None], *args: Any) -> None:
        function(*args)

    monkeypatch.setattr(common, "_metadata_write_executor", SimpleNamespace(run=run))


async def settle() -> None:
    # Let fetch, consumer, and database tasks reach their explicit gates.
    for _ in range(40):
        await asyncio.sleep(0)


@run_async_test
@pytest.mark.parametrize("blocked,committed", [("process", [(1, 1)]), ("write", [])])
async def test_history_backlog_respects_existing_fetch_capacity(
    metadata_writer: None, blocked: str, committed: list[tuple[int, int]]
) -> None:
    reader = Reader()
    gate = reader.process_gate if blocked == "process" else reader.write_gate
    gate.clear()
    task = asyncio.create_task(reader._load_range(1, 128))
    try:
        await reader.entered.wait()
        await settle()
        assert sorted(reader.fetched) == [1, 2, 3, 4]
        assert sum(reference() is not None for reference in reader.references) <= 4
        # Raw logs may commit while event processing waits. Metadata cannot
        # advance before the corresponding raw write finishes.
        assert reader.metadata == committed
    finally:
        gate.set()
        await task
        if reader._db_task is not None:
            await reader._db_task
    expected = list(range(1, 129))
    assert sorted(reader.fetched) == expected
    assert reader.processed == expected
    assert reader.written == expected
    assert reader.metadata == [(1, block) for block in expected]
    assert reader._lock.value == 128
    assert all(reference() is None for reference in reader.references)


@run_async_test
@pytest.mark.parametrize("outcome", ["cancel", "failure"])
async def test_history_closes_owned_fetches_and_preserves_other_readers(
    metadata_writer: None, outcome: str
) -> None:
    reader, neighbor = Reader(), Reader()
    reader.fetch_gate.clear()
    neighbor.fetch_gate.clear()
    if outcome == "failure":
        reader.fail_block = 2
    task = asyncio.create_task(reader._load_range(1, 128))
    other = asyncio.create_task(neighbor._load_range(1, 4))
    try:
        await reader.entered.wait()
        await neighbor.entered.wait()
        await settle()
        assert reader.active == reader.peak_active == 4
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            reader.fetch_gate.set()
            with pytest.raises(ValueError, match="historical chunk failed"):
                await task
        assert reader.active == 0
        assert not other.done()
        assert neighbor.active == 4
    finally:
        reader.fetch_gate.set()
        neighbor.fetch_gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, other, return_exceptions=True)
        await settle()
        for owner in (reader, neighbor):
            if owner._db_task is not None:
                await owner._db_task
    assert neighbor.processed == neighbor.written == [1, 2, 3, 4]


@run_async_test
@pytest.mark.parametrize("chunks", [-1, 0, 1, 3, None])
async def test_history_preserves_chunk_selection(metadata_writer: None, chunks: int | None) -> None:
    reader = Reader(chunks=chunks)
    await reader._load_range(1, 5)
    if reader._db_task is not None:
        await reader._db_task
    expected = list(range(1, (5 if chunks is None else chunks) + 1))
    assert sorted(reader.fetched) == reader.processed == reader.written == expected
    assert reader.metadata == [(1, block) for block in expected]


@run_async_test
@pytest.mark.parametrize("failure", [False, True])
async def test_history_handles_out_of_order_completion(
    metadata_writer: None, failure: bool
) -> None:
    gate = asyncio.Event()
    entered = asyncio.Event()
    running: set[int] = set()

    class OrderedReader(Reader):
        async def _fetch_range(self, from_block: int, to_block: int) -> list[Entry]:
            # Observe identity without making the cancelled coroutine own its
            # task through the exception traceback.
            current = id(asyncio.current_task())
            running.add(current)
            try:
                entries = await super()._fetch_range(from_block, to_block)
                if from_block == 1:
                    entered.set()
                    await gate.wait()
                return entries
            finally:
                running.remove(current)

    reader = OrderedReader()
    if failure:
        reader.fail_block = 2
    task = asyncio.create_task(reader._load_range(1, 8))
    try:
        await entered.wait()
        await settle()
        assert reader.processed == []
        assert reader.metadata == []
        if failure:
            with pytest.raises(ValueError, match="historical chunk failed"):
                await asyncio.wait_for(task, 5)
            assert not running
        else:
            gate.set()
            await task
            assert reader.processed == reader.written == list(range(1, 9))
            assert reader.metadata == [(1, block) for block in range(1, 9)]
    finally:
        gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await settle()
        if reader._db_task is not None:
            await reader._db_task
    assert not running
    assert all(reference() is None for reference in reader.references)


@run_async_test
async def test_history_preserves_pending_write_during_cancellation_and_reuse(
    metadata_writer: None,
) -> None:
    reader = Reader()
    reader.write_gate.clear()
    task = asyncio.create_task(reader._load_range(1, 8))
    retry = None
    try:
        await reader.entered.wait()
        await settle()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert reader._db_task is not None and not reader._db_task.done()
        assert reader.processed == [1]
        assert reader.written == []
        assert reader.metadata == []
        retry = asyncio.create_task(reader._load_range(2, 8))
        await settle()
        assert sorted(reader.fetched) == [1, 2, 3, 4]
        reader.write_gate.set()
        await retry
        assert reader.processed == reader.written == list(range(1, 9))
        assert reader.metadata == [(1, 1), *((2, block) for block in range(2, 9))]
    finally:
        reader.write_gate.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, *([retry] if retry is not None else []), return_exceptions=True)
        if reader._db_task is not None:
            await reader._db_task
    assert all(reference() is None for reference in reader.references)


@run_async_test
async def test_history_waits_for_a_closed_fetch_semaphore(metadata_writer: None) -> None:
    reader = Reader(capacity=0)
    task = asyncio.create_task(reader._load_range(1, 1))
    try:
        await settle()
        assert not task.done()
        assert reader.fetched == []
        reader.semaphore.release()
        await task
        assert reader.fetched == reader.processed == reader.written == [1]
        assert reader.metadata == [(1, 1)]
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
