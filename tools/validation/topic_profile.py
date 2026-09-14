"""Measure actual topic-ID lookup caches with exact persisted identifiers."""

import argparse
import asyncio
import hashlib
import os
import time
import tracemalloc
from pathlib import Path
from typing import Any

from cache_profile import memory
from common import write_json
from evmspec.structs.log import Topic
from profile_state import capture

from y import ENVIRONMENT_VARIABLES as ENVS
from y._db.entities import LogTopic
from y._db.utils import logs
from y._db.utils.bulk import insert as bulk_insert


def synchronous_cache(function: Any) -> Any:
    seen = set()
    while id(function) not in seen:
        seen.add(id(function))
        if callable(getattr(function, "cache_info", None)):
            return function
        function = getattr(function, "__wrapped__", None)
        if function is None:
            break
    raise RuntimeError("The synchronous topic cache was not found")


def async_cache_info(function: Any) -> dict[str, Any] | None:
    # a_sync forwards cache_info metadata from the synchronous callable too.
    # Only its actual async LRU wrapper owns a separate result/task cache.
    if type(function).__module__ != "async_lru" or type(function).__name__ != "_LRUCacheWrapper":
        return None
    info = getattr(function, "cache_info", None)
    if info is None:
        return None
    result: dict[str, Any] = info()._asdict()
    return result


def topic(number: int) -> Topic:
    result: Topic = Topic((2**240 + number).to_bytes(32, "big"))
    return result


async def main(directory: Path, allocations: bool) -> None:
    # Store exact IDs first, as bulk log persistence does before preparing rows.
    count, batch_size, concurrency = 131072, 1024, 64
    id_start = 2**40
    insert: Any = bulk_insert
    for start in range(0, count, batch_size):
        await insert(
            LogTopic,
            ("dbid", "topic"),
            tuple(
                (id_start + number, topic(number).strip())
                for number in range(start, start + batch_size)
            ),
            sync=False,
        )
    lookup: Any = logs.get_topic_dbid
    inner = synchronous_cache(lookup.__wrapped__)
    outer = lookup._asyncified
    if allocations:
        tracemalloc.start()
    before = memory()
    actual, expected = hashlib.sha256(), hashlib.sha256()
    rounds = []
    elapsed = 0.0
    for start in range(0, count, batch_size):
        started = time.perf_counter()
        for offset in range(start, start + batch_size, concurrency):
            inputs = [topic(number) for number in range(offset, offset + concurrency)]
            values = await asyncio.gather(*(lookup(value) for value in inputs))
            required = list(range(id_start + offset, id_start + offset + concurrency))
            assert values == required
            assert await asyncio.gather(*(lookup(value) for value in inputs)) == required
            for value in values:
                actual.update(value.to_bytes(8, "big"))
            for value in required:
                expected.update(value.to_bytes(8, "big"))
            del inputs, values, required
        # A recurring event signature stays hot throughout historical turnover.
        assert await lookup(topic(0)) == id_start
        elapsed += time.perf_counter() - started
        rounds.append(
            {
                "completed_topics": start + batch_size,
                "sync_cache": inner.cache_info()._asdict(),
                "async_cache": async_cache_info(outer),
                **memory(),
            }
        )
    metrics = memory()
    # Verify an evicted topic reuses its persisted ID. Observe any added lookup.
    before_revisit = inner.cache_info().misses
    assert await lookup(topic(1)) == id_start + 1
    added_lookup = inner.cache_info().misses - before_revisit
    # Both existing public call modes preserve the same immutable database ID.
    assert lookup(topic(count - 1), sync=True) == id_start + count - 1
    assert actual.digest() == expected.digest()
    write_json(
        directory / "topic-turnover.json",
        {
            "complete": True,
            "topics": count,
            "batch_size": batch_size,
            "concurrency": concurrency,
            "configured_default_capacity": int(ENVS.DEFAULT_CACHE_MAXSIZE),
            "elapsed_seconds": elapsed,
            "profiler": "tracemalloc; exclude timings" if allocations else None,
            "results_sha256": actual.hexdigest(),
            "rpc_calls_during_lookup": 0,
            "boundary": "preseeded SQLite topic-ID lookup only; no log download or pricing",
            "sync_cache": inner.cache_info()._asdict(),
            "async_cache": async_cache_info(outer),
            "async_dispatch": {
                "type": f"{type(outer).__module__}.{type(outer).__qualname__}",
                "forwards_sync_cache_info": getattr(outer, "cache_info", None) is inner.cache_info,
            },
            "old_topic_revisit_added_database_lookups": added_lookup,
            "memory_before_lookup": before,
            "rounds": rounds,
            **metrics,
        },
    )
    if allocations:
        capture(directory, "topic-turnover")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allocations", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(Path(os.environ["VALIDATION_REPORT"]), args.allocations))
