"""Factory history reuse requires complete compatible disk coverage."""

from collections.abc import Iterator, Sequence
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from tests.test_pricing_correctness import run_async_test
from y import convert
from y._db.typing import db_session
from y._db.utils.logs import LogCache
from y.contracts import Contract
from y.prices import magic, one_to_one

FACTORY = "0x0000000000000000000000000000000000228899"
TOPIC = "0x" + "11" * 32
TOKEN = "0x" + "22" * 32
OTHER = "0x" + "33" * 32


_TEST_FACTORIES = (
    FACTORY,
    "0x0000000000000000000000000000000000229900",
    "0x0000000000000000000000000000000000550099",
)


def _clear_test_metadata() -> None:
    from y._db.entities import LogCacheInfo, LogCacheRange

    with db_session:
        for entity in (LogCacheInfo, LogCacheRange):
            for row in entity.select(lambda row: row.address in _TEST_FACTORIES):
                row.delete()


@pytest.fixture(autouse=True)
def isolated_discovery_metadata() -> Iterator[None]:
    # These tests share the native database with live pricing cases. Only remove
    # metadata owned by this module, including remnants from an earlier run.
    _clear_test_metadata()
    try:
        yield
    finally:
        _clear_test_metadata()


def test_metadata_cleanup_preserves_unrelated_factory() -> None:
    from y._db.entities import LogCacheRange

    unrelated = "0x0000000000000000000000000000000000660099"
    try:
        with db_session:
            LogCache([FACTORY], [TOPIC])._set_metadata(10, 20)
            LogCache([unrelated], [TOPIC])._set_metadata(10, 20)
        _clear_test_metadata()
        with db_session:
            assert LogCache([FACTORY], [TOPIC])._is_cached_thru(10) == 0
            assert LogCache([unrelated], [TOPIC])._is_cached_thru(10) == 20
    finally:
        with db_session:
            for row in LogCacheRange.select(lambda row: row.address == unrelated):
                row.delete()


@pytest.mark.parametrize(
    "requested", [[TOPIC, TOKEN], [TOPIC, None, TOKEN], [[TOPIC], [TOKEN, OTHER]]]
)
def test_broad_factory_cache_covers_token_positions(requested: object) -> None:
    broad = LogCache([FACTORY], [TOPIC])
    with db_session:
        broad._set_metadata(10, 20)
        assert LogCache([FACTORY], requested)._is_cached_thru(10) == 20


def test_metadata_must_not_invent_coverage_across_a_gap() -> None:
    cache = LogCache([FACTORY], [OTHER])
    with db_session:
        cache._set_metadata(10, 20)
        cache._set_metadata(30, 40)
        assert cache._is_cached_thru(10) == 20
        assert cache._is_cached_thru(21) == 0
        assert cache._is_cached_thru(30) == 40
        cache._set_metadata(21, 29)
        assert cache._is_cached_thru(10) == 40


@run_async_test
@pytest.mark.parametrize(
    "token,underlying",
    [
        (
            "0x49d716DFe60b37379010A75329ae09428f17118d",
            "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        ),
        (
            "0xBD87447F48ad729C5c4b8bcb503e1395F62e8B98",
            "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        ),
    ],
)
async def test_pooltogether_prices_follow_verified_underlying(
    monkeypatch: pytest.MonkeyPatch, token: str, underlying: str
) -> None:
    lookup = AsyncMock(return_value=1.0123)
    monkeypatch.setattr(magic, "get_price", lookup)
    assert one_to_one.is_one_to_one_token(convert.to_address(token))
    result = await one_to_one.get_price(token, block=18000000, sync=False)
    assert result is not None and float(result) == 1.0123
    lookup.assert_awaited_once_with(underlying, block=18000000, skip_cache=False, sync=False)


@pytest.mark.parametrize(
    "cached,requested,expected",
    [
        (None, [TOPIC, TOKEN], True),
        ([TOPIC], [TOPIC, None, TOKEN], True),
        ([[TOPIC, OTHER], None], [TOPIC, TOKEN], True),
        ([TOPIC, TOKEN], [TOPIC, [TOKEN, OTHER]], False),
        ([TOPIC, TOKEN], [TOPIC, None, TOKEN], False),
        ([TOPIC, None, None], [TOPIC, TOKEN], False),
        ([OTHER], [TOPIC], False),
    ],
)
def test_topic_constraints_are_containment_not_just_topic_zero(
    cached: Sequence[Any] | None, requested: Sequence[Any] | None, expected: bool
) -> None:
    from y._db.log_coverage import topics_cover

    assert topics_cover(cached, requested) is expected


def test_multiple_addresses_require_coverage_for_each() -> None:
    other_factory = "0x0000000000000000000000000000000000229900"
    with db_session:
        LogCache([FACTORY], [TOPIC])._set_metadata(10, 30)
        LogCache([other_factory], [TOPIC])._set_metadata(10, 15)
        requested = LogCache([FACTORY, other_factory], [TOPIC, TOKEN])
        assert requested._is_cached_thru(10) == 15
        assert requested._is_cached_thru(16) == 0


def test_other_chain_address_and_topic_coverage_cannot_be_reused() -> None:
    from y._db.entities import Chain, LogCacheRange

    unique = "0x0000000000000000000000000000000000550099"
    with db_session:
        other_chain = Chain.get(id=999999) or Chain(id=999999)
        LogCacheRange(
            chain=other_chain, address=unique, topics=b"null", cached_from=10, cached_thru=100
        )
        assert LogCache([unique], [TOPIC])._is_cached_thru(10) == 0
        LogCache([FACTORY], [OTHER])._set_metadata(50, 100)
        assert LogCache([unique], [OTHER])._is_cached_thru(50) == 0
        assert LogCache([FACTORY], [TOPIC])._is_cached_thru(50) == 0


@run_async_test
@pytest.mark.parametrize("owner", ["filtered", "broad-v2", "broad-v3"])
async def test_factory_scan_shared_across_tokens_cancellation_and_restart(
    monkeypatch: pytest.MonkeyPatch,
    owner: str,
) -> None:
    import asyncio

    from y.utils import _factory_history as history

    entered, released = asyncio.Event(), asyncio.Event()
    persisted: list[object] = []
    coverage: list[tuple[int, int]] = []
    event = SimpleNamespace(
        topics=[bytes.fromhex(TOPIC[2:]), bytes.fromhex(TOKEN[2:]), bytes.fromhex(OTHER[2:])]
    )

    class Cache:
        def __init__(self, *args: object) -> None:
            pass

        def is_cached_thru(self, start: int) -> int:
            from y._db.log_coverage import completed_thru

            return completed_thru(start, coverage)

        def select(self, start: int, end: int) -> list[object]:
            return persisted.copy()

        def set_metadata(self, start: int, end: int) -> None:
            coverage.append((start, end))

    async def run(function: Any, *args: Any) -> Any:
        return function(*args)

    async def fetch(*args: object) -> list[object]:
        entered.set()
        await released.wait()
        return [event]

    async def insert(rows: list[object]) -> None:
        persisted.extend(rows)

    from dank_mids import brownie_patch

    from tests.test_pricing_correctness import Ready

    monkeypatch.setattr(brownie_patch, "dank_eth", SimpleNamespace(block_number=Ready(20)))
    history.scans.cache_clear()
    monkeypatch.setattr(history, "LogCache", Cache)
    monkeypatch.setattr(history, "default_filter_threads", SimpleNamespace(run=run))
    rpc = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(history, "adaptive_logs", rpc)
    monkeypatch.setattr(history, "bulk_insert", insert)
    if owner == "filtered":
        initial = history.factory_logs([FACTORY], [TOPIC, TOKEN], 10, 20)
    else:
        from y.prices.dex.uniswap.v2 import PoolsFromEvents
        from y.prices.dex.uniswap.v3 import UniV3Pools
        from y.utils import _log_ranges

        monkeypatch.setattr(
            _log_ranges, "adaptive_logs", AsyncMock(side_effect=AssertionError("duplicate scan"))
        )
        if owner == "broad-v2":
            monkeypatch.setattr(PoolsFromEvents, "PairCreated", TOPIC)
            pool_filter: Any = PoolsFromEvents(FACTORY, "shared", True)
        else:
            pool_filter = UniV3Pools(
                cast(Contract, SimpleNamespace(address=FACTORY, topics={"PoolCreated": TOPIC})),
                True,
            )
        initial = pool_filter._fetch_range(10, 20)
    first = asyncio.create_task(initial)
    await asyncio.wait_for(entered.wait(), 1)
    second = asyncio.create_task(history.factory_logs(FACTORY, [[TOPIC], None, OTHER], 10, 20))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    released.set()
    assert await second == [event]
    assert rpc.await_count == 1
    assert coverage == [(10, 20)]
    history.scans.cache_clear()  # New process ownership, same persisted history.
    assert await history.factory_logs([FACTORY], [TOPIC, TOKEN], 10, 20) == [event]
    assert await history.factory_logs([FACTORY], [TOPIC, OTHER], 10, 20) == []
    assert rpc.await_count == 1


@run_async_test
async def test_stale_mapping_bucket_reclassified(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_amount_quotes import TOKEN as unknown
    from y._db.utils import token as token_db
    from y.prices.utils import buckets

    monkeypatch.setattr(token_db, "get_bucket", AsyncMock(return_value="one to one"))
    monkeypatch.setattr(token_db, "set_bucket", lambda *args: None)
    monkeypatch.setattr(buckets, "string_matchers", {"corrected": lambda token: token == unknown})
    assert await buckets.check_bucket(unknown, sync=False) == "corrected"


@run_async_test
@pytest.mark.parametrize("failure", ["empty", "error", "cancel"])
async def test_factory_scan_only_publishes_completed_ranges(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import asyncio

    from dank_mids import brownie_patch

    from tests.test_pricing_correctness import Ready
    from y.utils import _factory_history as history

    coverage: list[tuple[int, int]] = []
    entered = asyncio.Event()

    class Cache:
        def __init__(self, *args: object) -> None:
            pass

        def is_cached_thru(self, start: int) -> int:
            from y._db.log_coverage import completed_thru

            return completed_thru(start, coverage)

        def select(self, start: int, end: int) -> list[object]:
            return []

        def set_metadata(self, start: int, end: int) -> None:
            coverage.append((start, end))

    async def run(function: Any, *args: Any) -> Any:
        return function(*args)

    async def fetch(*args: object) -> list[object]:
        entered.set()
        if failure == "error":
            raise ConnectionError("provider unavailable")
        if failure == "cancel":
            await asyncio.Event().wait()
        return []

    history.scans.cache_clear()
    monkeypatch.setattr(brownie_patch, "dank_eth", SimpleNamespace(block_number=Ready(20)))
    monkeypatch.setattr(history, "LogCache", Cache)
    monkeypatch.setattr(history, "default_filter_threads", SimpleNamespace(run=run))
    rpc = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(history, "adaptive_logs", rpc)
    monkeypatch.setattr(history, "bulk_insert", AsyncMock())
    task = asyncio.create_task(history.factory_logs([FACTORY], [TOPIC, TOKEN], 10, 20))
    await entered.wait()
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    elif failure == "error":
        with pytest.raises(ConnectionError):
            await task
    else:
        assert await task == []
        history.scans.cache_clear()
        assert await history.factory_logs([FACTORY], [TOPIC, TOKEN], 10, 20) == []
        assert rpc.await_count == 1
    assert coverage == ([(10, 20)] if failure == "empty" else [])
    assert not history.scans().flights


@run_async_test
@pytest.mark.parametrize("cancel", [False, True])
async def test_factory_window_failure_retains_prior_coverage_and_restarts_missing_only(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    import asyncio

    from dank_mids import brownie_patch

    from tests.test_pricing_correctness import Ready
    from y._db.log_coverage import completed_thru
    from y.utils import _factory_history as history
    from y.utils import _log_ranges

    coverage: list[tuple[int, int]] = []
    requested: list[tuple[int, int]] = []
    entered = asyncio.Event()
    failing = True

    class Cache:
        def __init__(self, *args: object) -> None:
            pass

        def is_cached_thru(self, start: int) -> int:
            return completed_thru(start, coverage)

        def set_metadata(self, start: int, end: int) -> None:
            coverage.append((start, end))

        def select(self, start: int, end: int) -> list[object]:
            return []

    async def run(function: Any, *args: Any) -> Any:
        return function(*args)

    async def fetch(addresses: Any, topics: Any, start: int, end: int) -> list[Any]:
        requested.append((start, end))
        if failing and start > 80:
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise ConnectionError("second window unavailable")
        return []

    history.scans.cache_clear()
    monkeypatch.setattr(brownie_patch, "dank_eth", SimpleNamespace(block_number=Ready(160)))
    monkeypatch.setattr(history, "LogCache", Cache)
    monkeypatch.setattr(history, "default_filter_threads", SimpleNamespace(run=run))
    monkeypatch.setattr(history, "adaptive_logs", fetch)
    monkeypatch.setattr(history, "bulk_insert", AsyncMock())
    monkeypatch.setattr(_log_ranges, "indexed_chunk_size", lambda: 10)
    monkeypatch.setattr(_log_ranges, "sparse_chunk_ceiling", lambda: 10)
    task = asyncio.create_task(history.factory_logs(FACTORY, [TOPIC, TOKEN], 1, 160))
    await entered.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ConnectionError, match="second window unavailable"):
            await task
    assert completed_thru(1, coverage) == 80
    assert not history.scans().flights
    failing = False
    requested.clear()
    assert await history.factory_logs(FACTORY, [TOPIC, TOKEN], 1, 160) == []
    assert requested and all(start > 80 for start, _ in requested)
    assert completed_thru(1, coverage) == 160


@run_async_test
@pytest.mark.parametrize(
    "event_counts,ceiling,slow_seconds,expected,third",
    [
        ((0, 0, 0), 40, 0, 20, 40),
        ((1025, 1025, 1025), 40, 0, 20, 40),
        ((4096, 4096, 4096), 40, 0, 20, 40),
        ((4097, 4097, 4097), 40, 0, 10, 10),
        ((8192, 8192, 8192), 40, 0, 10, 10),
        ((0, 8193, 0), 40, 0, 20, 10),
        ((0, 0, 0), 10, 0, 10, 10),
        ((8193, 8193, 8193), 40, 0, 10, 10),
        ((0, 0, 0), 40, 6, 20, 20),
        ((0, 0, 0), 40, 11, 20, 10),
    ],
)
async def test_factory_windows_grow_after_sparse_success_and_bound_dense_history(
    monkeypatch: Any,
    event_counts: tuple[int, int, int],
    ceiling: int,
    slow_seconds: float,
    expected: int,
    third: int,
) -> None:
    from dank_mids import brownie_patch

    from tests.test_pricing_correctness import Ready
    from y._db.log_coverage import completed_thru
    from y.utils import _factory_history as history
    from y.utils import _log_ranges

    ranges: list[tuple[int, int]] = []
    coverage: list[tuple[int, int]] = []
    clock = [0.0]

    class Cache:
        def __init__(self, *args: Any) -> None:
            pass

        def is_cached_thru(self, start: int) -> int:
            return completed_thru(start, coverage)

        def set_metadata(self, start: int, end: int) -> None:
            coverage.append((start, end))

        def select(self, start: int, end: int) -> list[Any]:
            return []

    async def run(function: Any, *args: Any) -> Any:
        return function(*args)

    async def fetch(addresses: Any, topics: Any, start: int, end: int) -> list[Any]:
        ranges.append((start, end))
        if len(ranges) > 8:
            clock[0] += slow_seconds
        return [SimpleNamespace()] * event_counts[min((len(ranges) - 1) // 8, 2)]

    history.scans.cache_clear()
    monkeypatch.setattr(history, "monotonic", lambda: clock[0], raising=False)
    monkeypatch.setattr(brownie_patch, "dank_eth", SimpleNamespace(block_number=Ready(10000)))
    monkeypatch.setattr(history, "LogCache", Cache)
    monkeypatch.setattr(history, "default_filter_threads", SimpleNamespace(run=run))
    monkeypatch.setattr(history, "adaptive_logs", fetch)
    monkeypatch.setattr(history, "bulk_insert", AsyncMock())
    monkeypatch.setattr(_log_ranges, "indexed_chunk_size", lambda: 10)
    monkeypatch.setattr(_log_ranges, "sparse_chunk_ceiling", lambda: ceiling, raising=False)
    assert await history.factory_logs(FACTORY, [TOPIC], 1, 10) == []
    assert max(last - first + 1 for first, last in ranges) == 10
    first_count = len(ranges)
    assert first_count == 8
    assert completed_thru(1, coverage) == 80
    assert await history.factory_logs(FACTORY, [TOPIC], 81, 90) == []
    assert max(last - first + 1 for first, last in ranges[first_count:]) == expected
    assert len(ranges) - first_count <= 8
    second_count = len(ranges)
    next_start = completed_thru(1, coverage) + 1
    assert await history.factory_logs(FACTORY, [TOPIC], next_start, next_start + 9) == []
    assert max(last - first + 1 for first, last in ranges[second_count:]) == third
    assert len(ranges) - second_count <= 8


@run_async_test
@pytest.mark.parametrize("cached,empty", [(True, False), (False, False), (True, True)])
async def test_factory_event_batches_are_bounded_and_reuse_completed_history(
    monkeypatch: pytest.MonkeyPatch, cached: bool, empty: bool
) -> None:
    from y.utils import _factory_history as history

    rows = (
        []
        if empty
        else [
            SimpleNamespace(
                blockNumber=10 + index // 1000,
                logIndex=index,
                transactionHash=SimpleNamespace(hex=lambda: "0x" + "aa" * 32),
            )
            for index in range(8201)
        ]
    )
    reads: list[Any] = []
    fetches: list[Any] = []

    class Cache:
        def __init__(self, addresses: Any, topics: Any) -> None:
            assert addresses == [FACTORY] and topics == [TOPIC]

        def is_cached_thru(self, first: int) -> int:
            return 20 if cached else 0

        def select_page(self, first: int, last: int, after: Any, limit: int) -> list[Any]:
            reads.append((first, last, limit))
            assert last == 20 and limit == 4096
            index = after[1] + 1 if after else 0
            return rows[index : index + limit]

    async def run(function: Any, *args: Any) -> Any:
        return function(*args)

    async def fetch(addresses: Any, topics: Any, first: int, last: int) -> list[Any]:
        fetches.append((addresses, topics, first, last))
        assert last == 20
        return rows

    monkeypatch.setattr(history, "LogCache", Cache)
    monkeypatch.setattr(history, "default_filter_threads", SimpleNamespace(run=run))
    monkeypatch.setattr(history, "factory_logs", fetch)
    batches = [batch async for batch in history.factory_log_batches([FACTORY], [TOPIC], 10, 20)]
    assert [row for batch in batches for row in batch] == rows
    assert all(len(batch) <= 4096 for batch in batches)
    if cached:
        assert fetches == []
        assert len(reads) == (1 if empty else 4)
        assert all(len(batch) <= 4096 for batch in batches)
    else:
        assert reads == []
        assert fetches == [([FACTORY], [TOPIC], 10, 20)]
