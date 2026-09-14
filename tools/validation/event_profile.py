"""Measure ordered historical chunk ownership with controlled fetch and write delays."""

import argparse
import asyncio
import hashlib
import json
import os
import resource
import time
import tracemalloc
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from weakref import ref

from pytest import MonkeyPatch

from tests.test_event_memory import Entry, Reader
from y._db import common


@dataclass
class Chunk(Entry):
    data: bytes


class Workload(Reader):
    def __init__(self) -> None:
        super().__init__(capacity=32)
        self.peak_retained_chunks = 0
        self.digest = hashlib.sha256()

    async def _fetch_range(self, from_block: int, to_block: int) -> list[Entry]:
        self.active += 1
        self.peak_active = max(self.peak_active, self.active)
        self.fetched.append(from_block)
        try:
            await asyncio.sleep(0.001)
            entry = Chunk(from_block, from_block.to_bytes(4, "big") * (262144 // 4))
            self.references.append(ref(entry))
            self.peak_retained_chunks = max(
                self.peak_retained_chunks,
                sum(reference() is not None for reference in self.references),
            )
            return [entry]
        finally:
            self.active -= 1

    async def _extend(self, entries: list[Entry]) -> None:
        await asyncio.sleep(0.001)
        await super()._extend(entries)

    async def write(self, entries: list[Entry]) -> None:
        await asyncio.sleep(0.002)
        for entry in entries:
            assert isinstance(entry, Chunk)
            self.digest.update(entry.data)
        await super().write(entries)


async def workload() -> dict[str, Any]:
    async def metadata(function: Any, *args: Any) -> None:
        function(*args)

    reader = Workload()
    started = time.perf_counter()
    with MonkeyPatch.context() as patch:
        patch.setattr(common, "_metadata_write_executor", SimpleNamespace(run=metadata))
        await reader._load_range(1, 512)
        if reader._db_task is not None:
            await reader._db_task
    elapsed = time.perf_counter() - started
    current, peak = tracemalloc.get_traced_memory()
    expected = list(range(1, 513))
    assert sorted(reader.fetched) == reader.processed == reader.written == expected
    assert reader.metadata == [(1, block) for block in expected]
    assert reader.peak_active == 32
    assert reader.active == 0
    assert all(reference() is None for reference in reader.references)
    expected_digest = hashlib.sha256()
    for block in expected:
        expected_digest.update(block.to_bytes(4, "big") * (262144 // 4))
    assert reader.digest.digest() == expected_digest.digest()
    return {
        "chunks": 512,
        "bytes_per_chunk": 262144,
        "peak_fetch_operations": reader.peak_active,
        "peak_retained_chunks": reader.peak_retained_chunks,
        "retained_chunks_after": 0,
        "persisted_sha256": reader.digest.hexdigest(),
        "final_block": reader._lock.value,
        "elapsed_seconds": elapsed,
        "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "python_current_bytes": current if tracemalloc.is_tracing() else None,
        "python_peak_bytes": peak if tracemalloc.is_tracing() else None,
        "profiler": "tracemalloc; exclude timings" if tracemalloc.is_tracing() else None,
        "boundary": "controlled in-process fetch and write delays; no real RPC timing",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allocations", action="store_true")
    args = parser.parse_args()
    if args.allocations:
        tracemalloc.start()
    result = asyncio.get_event_loop().run_until_complete(workload())
    Path(os.environ["VALIDATION_REPORT"], "events.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
