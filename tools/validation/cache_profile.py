"""Measure cache turnover with fixed observer state and separate allocation runs."""

import argparse
import asyncio
import hashlib
import os
import resource
import time
import tracemalloc
from pathlib import Path
from typing import Any

import cachebox
from common import write_json
from profile_state import capture


class Owners:
    def __init__(self) -> None:
        self.live = 0


class Key:
    def __init__(self, number: int, owners: Owners) -> None:
        self.number = number
        self.payload = number.to_bytes(4, "big") * 1024
        self.owners = owners
        owners.live += 1

    def __del__(self) -> None:
        self.owners.live -= 1


def memory() -> dict[str, Any]:
    status = Path("/proc/self/status").read_text().splitlines()
    rss = int(next(line.split()[1] for line in status if line.startswith("VmRSS:"))) * 1024
    current, peak = tracemalloc.get_traced_memory()
    return {
        "rss_current_bytes": rss,
        "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "python_current_bytes": current if tracemalloc.is_tracing() else None,
        "python_peak_bytes": peak if tracemalloc.is_tracing() else None,
    }


async def main(directory: Path, allocations: bool) -> None:
    if allocations:
        tracemalloc.start()
    sync_owners, async_owners = Owners(), Owners()
    sync_calls = async_calls = 0
    capacity, batches, batch_size = 64, 128, 256
    sync_cache: cachebox.LRUCache[tuple[Key], dict[str, int]] = cachebox.LRUCache(capacity)
    async_cache: cachebox.LRUCache[tuple[Key], dict[str, int]] = cachebox.LRUCache(capacity)

    @cachebox.cached(sync_cache)
    def sync_value(key: Key) -> dict[str, int]:
        nonlocal sync_calls
        sync_calls += 1
        return {"value": key.number * key.number}

    @cachebox.cached(async_cache)
    async def async_value(key: Key) -> dict[str, int]:
        nonlocal async_calls
        async_calls += 1
        return {"value": key.number * key.number}

    actual, expected = hashlib.sha256(), hashlib.sha256()
    rounds = []
    elapsed = 0.0
    for batch in range(batches):
        started = time.perf_counter()
        for number in range(batch * batch_size, (batch + 1) * batch_size):
            key = Key(number, sync_owners)
            result = sync_value(key)
            assert result == {"value": number * number}
            actual.update(result["value"].to_bytes(8, "big"))
            result["value"] = -1
            assert sync_value(key) == {"value": number * number}
            key = Key(number, async_owners)
            result = await async_value(key)
            assert result == {"value": number * number}
            actual.update(result["value"].to_bytes(8, "big"))
            result["value"] = -1
            assert await async_value(key) == {"value": number * number}
            expected.update((number * number).to_bytes(8, "big") * 2)
            del key
        elapsed += time.perf_counter() - started
        rounds.append(
            {
                "round": batch + 1,
                "sync_retained_keys": sync_owners.live,
                "async_retained_keys": async_owners.live,
                "sync_entries": len(sync_cache),
                "async_entries": len(async_cache),
                **memory(),
            }
        )
    assert sync_calls == async_calls == batches * batch_size
    assert actual.digest() == expected.digest()
    write_json(
        directory / "cache-turnover.json",
        {
            "complete": True,
            "cachebox_version": cachebox.__version__,
            "capacity_per_cache": capacity,
            "payload_bytes_per_key": 4096,
            "batches": batches,
            "batch_size": batch_size,
            "sync_computations": sync_calls,
            "async_computations": async_calls,
            "cache_hits_per_function": batches * batch_size,
            "rpc_calls": 0,
            "elapsed_seconds": elapsed,
            "results_sha256": actual.hexdigest(),
            "profiler": "tracemalloc; exclude timings" if allocations else None,
            "boundary": "cache ownership and independent result copies; no application or RPC work",
            "rounds": rounds,
            **memory(),
        },
    )
    if allocations:
        capture(directory, "cache-turnover")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allocations", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(Path(os.environ["VALIDATION_REPORT"]), args.allocations))
