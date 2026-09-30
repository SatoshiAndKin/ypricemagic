"""Reproduce cache ownership after eviction without application or RPC work."""

import asyncio
import os
import tracemalloc
import weakref
from pathlib import Path

import cachebox
from async_lru import alru_cache
from common import write_json
from profile_state import capture


class Key:
    def __init__(self, number: int) -> None:
        self.number = number
        self.payload = bytes([number % 256]) * 16384


async def main() -> None:
    directory = Path(os.environ["VALIDATION_REPORT"])
    tracemalloc.start()
    sync_calls = async_calls = 0
    sync_cache: cachebox.LRUCache[tuple[Key], int] = cachebox.LRUCache(32)
    async_cache: cachebox.LRUCache[tuple[Key], int] = cachebox.LRUCache(32)

    @cachebox.cached(sync_cache)
    def sync_value(key: Key) -> int:
        nonlocal sync_calls
        sync_calls += 1
        return key.number * key.number

    @cachebox.cached(async_cache)
    async def async_value(key: Key) -> int:
        nonlocal async_calls
        async_calls += 1
        return key.number * key.number

    @alru_cache(maxsize=None)
    async def cached_integer(number: int) -> int:
        return number * number

    sync_keys: list[weakref.ReferenceType[Key]] = []
    async_keys: list[weakref.ReferenceType[Key]] = []
    rounds = []
    for batch in range(8):
        for number in range(batch * 64, (batch + 1) * 64):
            key = Key(number)
            sync_keys.append(weakref.ref(key))
            assert sync_value(key) == sync_value(key) == number * number
            key = Key(number)
            async_keys.append(weakref.ref(key))
            assert await async_value(key) == await async_value(key) == number * number
            del key
            assert await cached_integer(number) == await cached_integer(number) == number * number
        rounds.append(
            {
                "calls_per_function": (batch + 1) * 128,
                "sync_retained_keys": sum(ref() is not None for ref in sync_keys),
                "async_retained_keys": sum(ref() is not None for ref in async_keys),
                "sync_entries": len(sync_cache),
                "async_entries": len(async_cache),
            }
        )
    assert sync_calls == async_calls == 512
    capture(directory, "cache-owner-probe")
    write_json(
        directory / "cache-owner-probe.json",
        {
            "complete": True,
            "cachebox_version": cachebox.__version__,
            "cache_capacity": 32,
            "payload_bytes_per_key": 16384,
            "sync_computations": sync_calls,
            "async_computations": async_calls,
            "rounds": rounds,
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
