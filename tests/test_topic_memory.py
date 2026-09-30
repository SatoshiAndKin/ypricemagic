"""Topic-ID cache turnover preserves values, reuse, and independent callers."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from threading import Event
from typing import Any
from unittest.mock import patch
from weakref import ref

import pytest
from evmspec.structs.log import Topic

from y._db.entities import LogTopic
from y._db.utils import logs
from y._db.utils.bulk import insert as bulk_insert


class Marker:
    """A weak-reference observer owned only by a cached topic."""


def topic(number: int) -> Topic:
    result: Topic = Topic((2**240 + number).to_bytes(32, "big"))
    return result


async def seed(count: int = 128) -> None:
    # Native a_sync wrappers supply the sync keyword at runtime.
    insert: Any = bulk_insert
    await insert(
        LogTopic,
        ("dbid", "topic"),
        tuple((2**40 + number, topic(number).strip()) for number in range(count)),
        sync=False,
    )


async def release_case(mode: str) -> None:
    await seed()
    lookup: Any = logs.get_topic_dbid
    original = logs._get_log_topic
    reads = 0

    def counted(**kwargs: Any) -> Any:
        nonlocal reads
        reads += 1
        return original(**kwargs)

    async def invoke(item: Topic) -> int:
        result: int = lookup(item, sync=True) if mode == "sync" else await lookup(item)
        return result

    with patch.object(logs, "_get_log_topic", counted):
        item = topic(0)
        marker = Marker()
        setattr(item, "_memory_test_owner", marker)
        reference = ref(marker)
        del marker
        assert await invoke(item) == 2**40
        assert await invoke(topic(0)) == 2**40
        assert reads == 1
        del item
        for number in range(1, 128):
            assert await invoke(topic(number)) == 2**40 + number
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert reference() is None, "an evicted topic still owns its observer"
        warm_reads = reads
        assert await invoke(topic(127)) == 2**40 + 127
        assert reads == warm_reads
        assert lookup(topic(127), sync=True) == 2**40 + 127
        assert await lookup(topic(127)) == 2**40 + 127
        assert reads == warm_reads
        assert await invoke(topic(0)) == 2**40
        assert reads == warm_reads + 1


async def failure_case() -> None:
    await seed(1)
    lookup: Any = logs.get_topic_dbid
    original = logs._get_log_topic
    reads = 0

    def once(**kwargs: Any) -> Any:
        nonlocal reads
        reads += 1
        if reads == 1:
            raise ValueError("topic lookup failed")
        return original(**kwargs)

    with patch.object(logs, "_get_log_topic", once):
        try:
            await lookup(topic(0))
        except ValueError as error:
            assert str(error) == "topic lookup failed"
        else:
            raise AssertionError("the database lookup should fail once")
        assert await lookup(topic(0)) == 2**40
        assert await lookup(topic(0)) == 2**40
        assert reads == 2


async def cancellation_case() -> None:
    await seed(1)
    lookup: Any = logs.get_topic_dbid
    original = logs._get_log_topic
    entered, release = Event(), Event()
    reads = 0

    def blocked(**kwargs: Any) -> Any:
        nonlocal reads
        reads += 1
        entered.set()
        if not release.wait(10):
            raise TimeoutError("topic lookup gate did not open")
        return original(**kwargs)

    with patch.object(logs, "_get_log_topic", blocked):
        first = asyncio.create_task(lookup(topic(0)))
        second = None
        try:
            assert await asyncio.to_thread(entered.wait, 10)
            second = asyncio.create_task(lookup(topic(0)))
            await asyncio.sleep(0)
            first.cancel()
            outcomes = await asyncio.gather(first, return_exceptions=True)
            assert isinstance(outcomes[0], asyncio.CancelledError)
            release.set()
            assert await second == 2**40
            assert await lookup(topic(0)) == 2**40
            assert reads == 1
        finally:
            release.set()
            await asyncio.gather(
                first, *([second] if second is not None else []), return_exceptions=True
            )


@pytest.mark.parametrize("case", ["sync", "async", "failure", "cancellation"])
def test_topic_lookup_releases_state_and_preserves_results(case: str, tmp_path: Path) -> None:
    program = """
import asyncio, sys
from tests.test_topic_memory import release_case, failure_case, cancellation_case
case = sys.argv[1]
coroutine = release_case(case) if case in {'sync', 'async'} else failure_case() if case == 'failure' else cancellation_case()
asyncio.run(coroutine)
print('topic_case_passed', flush=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, case],
        env={
            **os.environ,
            "YPRICEMAGIC_DEFAULT_CACHE_MAXSIZE": "32",
            "YPRICEMAGIC_DB_PROVIDER": "sqlite",
            "YPRICEMAGIC_SQLITE_PATH": str(tmp_path / "topics.sqlite"),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "topic_case_passed" in result.stdout
