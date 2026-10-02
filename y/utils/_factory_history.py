"""Share raw factory backfills; instantiate only token-matching pool events."""

from asyncio import Lock, get_running_loop
from functools import lru_cache
from logging import getLogger
from time import monotonic
from typing import Any
from weakref import WeakKeyDictionary

import cachebox
from evmspec import Log

from y._db.common import default_filter_threads
from y._db.log_coverage import topics_cover
from y._db.utils.logs import LogCache
from y._db.utils.logs import bulk_insert_factory as bulk_insert
from y._decorators import stuck_coro_debugger
from y.prices._quote import SharedCache
from y.utils._log_ranges import adaptive_logs


class FactoryScans(SharedCache[list[Log]]):
    def __init__(self) -> None:
        super().__init__(0, immutable=True)
        self.locks: WeakKeyDictionary[Any, dict[Any, Lock]] = WeakKeyDictionary()
        self.write_locks: WeakKeyDictionary[Any, Lock] = WeakKeyDictionary()
        self.chunk_sizes: cachebox.LRUCache[Any, int] = cachebox.LRUCache(256)

    def lock(self, key: Any) -> Lock:
        locks = self.locks.setdefault(get_running_loop(), {})
        return locks.setdefault(key, Lock())

    def write_lock(self) -> Lock:
        return self.write_locks.setdefault(get_running_loop(), Lock())


@lru_cache(maxsize=1)
def scans() -> FactoryScans:
    # Only active scans retain raw logs. Completed history belongs on disk.
    return FactoryScans()


@stuck_coro_debugger
async def factory_logs(
    addresses: Any, topics: Any, start: int, end: int, *, chunk_size: int | None = None
) -> list[Log]:
    from y.constants import CHAINID

    factory_topics = [topics[0]] if topics else None
    broad = LogCache(addresses, factory_topics)

    async def read_range() -> list[Log]:
        from dank_mids.brownie_patch import dank_eth

        from y.prices._quote import bounded_map
        from y.utils._log_ranges import indexed_chunk_size, sparse_chunk_ceiling
        from y.utils.events import get_logs_semaphore

        cached = await default_filter_threads.run(broad.is_cached_thru, start)
        if cached < end:
            # Scan one bounded eight-range window per factory. Narrow consumers
            # do not occupy RPC slots while waiting for this shared owner.
            initial = indexed_chunk_size()
            ceiling = sparse_chunk_ceiling()
            chunk = min(ceiling, chunk_size or scans().chunk_sizes.get(factory_key) or initial)
            missing = max(start, cached + 1)
            horizon = min(end + 7 * chunk, await dank_eth.block_number)
            ranges = [
                (first, min(first + chunk - 1, horizon))
                for first in range(missing, horizon + 1, chunk)
            ]

            async def scan(blocks: tuple[int, int]) -> tuple[int, float]:
                first, last = blocks
                async with get_logs_semaphore[get_running_loop()][last]:
                    covered = await default_filter_threads.run(broad.is_cached_thru, first)
                    if covered >= last:
                        return 0, 0.0
                    first = max(first, covered + 1)
                    started = monotonic()
                    fetched = await adaptive_logs(addresses, factory_topics, first, last)
                    seconds = monotonic() - started
                    # SQLite has one writer. Keep RPCs concurrent while avoiding
                    # competing reference-ID reads and event commits here.
                    async with scans().write_lock():
                        await bulk_insert(fetched)
                        await default_filter_threads.run(broad.set_metadata, first, last)
                    return len(fetched), seconds

            counts = await bounded_map(scan, ranges, workers=8)
            if chunk_size is None:
                # Grow only after every range committed. Dense event histories
                # return to the initial range to retain a small raw-log window.
                largest = max((count for count, _ in counts), default=0)
                slowest = max((seconds for _, seconds in counts), default=0.0)
                if largest > 1024:
                    next_chunk = initial
                elif slowest > 10:
                    next_chunk = max(initial, chunk // 2)
                elif slowest < 5:
                    next_chunk = min(ceiling, chunk * 2)
                else:
                    next_chunk = chunk
                scans().chunk_sizes[factory_key] = next_chunk
        else:
            getLogger(__name__).debug(
                "factory cache reuse addresses=%s from=%s thru=%s", addresses, start, end
            )
        rows: list[Log] = await default_filter_threads.run(broad.select, start, end)
        return rows

    factories = (addresses,) if isinstance(addresses, str) else (addresses or ())
    constraint = factory_topics[0] if factory_topics else None
    alternatives = (constraint,) if isinstance(constraint, (str, bytes)) else constraint
    factory_key = (
        CHAINID,
        tuple(sorted({str(address).lower() for address in factories})),
        tuple(sorted({str(topic).lower().removeprefix("0x") for topic in alternatives or ()})),
    )

    async def load() -> list[Log]:
        # Different token scans can have different checkpoint boundaries. One
        # factory owner checks disk again after its predecessor finishes.
        async with scans().lock(factory_key):
            return await read_range()

    key = (*factory_key, start, end)
    rows = await scans().get(key, load)
    return [row for row in rows if topics_cover(topics, [topic.hex() for topic in row.topics])]
