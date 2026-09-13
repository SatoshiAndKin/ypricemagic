"""Request diagnostics and cached results have bounded ownership."""

import asyncio
from dataclasses import dataclass
import gc
import logging
import subprocess
import sys
from typing import Any
from weakref import ref

import pytest

from tests.test_pricing_correctness import BLOCK, TOKEN, run_async_test
from y.utils.logging import get_price_logger


@pytest.mark.parametrize("loop_mode", ["open", "asyncio_run", "closed_default"])
def test_database_worker_reuses_connection_and_allows_process_exit(loop_mode: str) -> None:
    program = """
import asyncio
import importlib
from importlib.machinery import EXTENSION_SUFFIXES
import sys

database = importlib.import_module('y._db.brownie')
assert any(database.__file__.endswith(suffix) for suffix in EXTENSION_SUFFIXES)

async def query():
    assert await database.cur.fetchone('SELECT 1') == (1,)
    connection = database.cur._db
    assert await database.cur.fetchone('SELECT 2') == (2,)
    assert database.cur._db is connection

if sys.argv[1] == 'asyncio_run':
    asyncio.run(query())
else:
    loop = asyncio.get_event_loop()
    loop.run_until_complete(query())
    if sys.argv[1] == 'closed_default':
        loop.close()
print('query_complete', flush=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", program, loop_mode],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert "query_complete" in result.stdout
    assert "Exception in thread" not in result.stderr


def test_normalized_addresses_share_strings_without_retaining_discovery_owners() -> None:
    from y.prices._markets import address

    @dataclass
    class Owner:
        address: str

    first_owner = Owner("0xAbCd000000000000000000000000000000001234")
    second_owner = Owner(first_owner.address.encode().decode())
    references = ref(first_owner), ref(second_owner)
    normalized = address(first_owner)
    assert normalized == "0xabcd000000000000000000000000000000001234"
    assert address(second_owner) is normalized
    second_owner.address = "0xBcDe000000000000000000000000000000005678"
    assert address(second_owner) == "0xbcde000000000000000000000000000000005678"
    del first_owner, second_owner
    gc.collect()
    assert all(reference() is None for reference in references)


@run_async_test
async def test_price_logger_close_releases_task_and_logger() -> None:
    parent = logging.getLogger("y.prices")
    level = parent.level
    parent.setLevel(logging.DEBUG)
    try:
        logger = get_price_logger(TOKEN, BLOCK, start_task=True)
        task = logger.debug_task
        assert task is not None
        reference = ref(logger)
        await asyncio.sleep(0)
        logger.close()
        logger.close()
        await asyncio.sleep(0)
        assert task.done()
        assert task.cancelled()
        del task, logger
        gc.collect()
        assert reference() is None
    finally:
        parent.setLevel(level)


@run_async_test
async def test_same_price_has_independent_diagnostic_owners() -> None:
    parent = logging.getLogger("y.prices")
    level = parent.level
    parent.setLevel(logging.DEBUG)
    try:
        first = get_price_logger(TOKEN, BLOCK, start_task=True)
        second = get_price_logger(TOKEN, BLOCK, start_task=True)
        try:
            assert first is not second
            assert first.debug_task is not second.debug_task
            first.close()
            await asyncio.sleep(0)
            assert second.debug_task is not None and not second.debug_task.done()
        finally:
            first.close()
            second.close()
            await asyncio.sleep(0)
    finally:
        parent.setLevel(level)


def test_disabled_price_logging_creates_no_task_or_registry_entries() -> None:
    parent = logging.getLogger("y.prices")
    level = parent.level
    parent.setLevel(logging.INFO)
    registry = set(logging.Logger.manager.loggerDict)
    refs = []
    try:
        for block in range(1000):
            logger = get_price_logger(TOKEN, block, start_task=True)
            refs.append(ref(logger))
            assert logger.debug_task is None
        del logger
        gc.collect()
        assert all(reference() is None for reference in refs)
        assert set(logging.Logger.manager.loggerDict) == registry
    finally:
        parent.setLevel(level)


@run_async_test
@pytest.mark.parametrize("outcome", ["success", "failure", "logging_failure", "cancel"])
async def test_public_price_request_closes_diagnostics(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    from tests.test_pricing_correctness import Ready
    from y.classes.common import ERC20
    from y.prices import magic

    # ez-a-sync supplies the sync keyword at runtime.
    lookup: Any = magic.get_price
    from y.datatypes import UsdPrice

    loggers = []
    entered = asyncio.Event()

    class FailingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            raise RuntimeError("failed price log")

    def capture(*args: Any, **kwargs: Any) -> Any:
        logger = get_price_logger(*args, **kwargs)
        if outcome == "logging_failure":
            logger.addHandler(FailingHandler())
        loggers.append(logger)
        return logger

    async def api(*args: Any, **kwargs: Any) -> UsdPrice:
        entered.set()
        if outcome == "failure":
            raise RuntimeError("failed price request")
        if outcome == "cancel":
            await asyncio.Event().wait()
        return UsdPrice(2)

    async def check(*args: Any) -> None:
        return None

    monkeypatch.setattr(magic, "get_price_logger", capture)
    monkeypatch.setattr(ERC20, "symbol", property(lambda _: Ready("TOKEN")))
    monkeypatch.setattr(magic, "_get_price_from_api", api)
    from y.prices import utils

    monkeypatch.setattr(utils, "sense_check", check)
    parent = logging.getLogger("y.prices")
    level = parent.level
    parent.setLevel(logging.DEBUG)
    try:
        task = asyncio.create_task(lookup(TOKEN, BLOCK, skip_cache=True, sync=False))
        if outcome != "logging_failure":
            await entered.wait()
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif outcome == "failure":
            with pytest.raises(RuntimeError, match="failed price request"):
                await task
        elif outcome == "logging_failure":
            with pytest.raises(RuntimeError, match="failed price log"):
                await task
        else:
            result = await task
            assert result is not None and float(result) == 2
        await asyncio.sleep(0)
        assert len(loggers) == 1
        assert loggers[0].debug_task is None
    finally:
        for logger in loggers:
            logger.close()
        await asyncio.sleep(0)
        parent.setLevel(level)


@run_async_test
async def test_cache_eviction_releases_values_and_preserves_recent_reuse() -> None:
    from y.prices._quote import SharedCache

    class Payload:
        pass

    cache: SharedCache[Payload] = SharedCache(2, immutable=True)
    references = []
    calls = 0

    async def create() -> Payload:
        nonlocal calls
        calls += 1
        value = Payload()
        references.append(ref(value))
        return value

    first = await cache.get(1, create)
    assert await cache.get(1, create) is first
    del first
    await cache.get(2, create)
    await cache.get(1, create)  # Keep 1; evict 2 next.
    await cache.get(3, create)
    gc.collect()
    assert [r() is not None for r in references] == [True, False, True]
    await cache.get(2, create)
    gc.collect()
    assert [r() is not None for r in references] == [False, False, True, True]
    assert calls == 4
    assert not cache.flights


@run_async_test
@pytest.mark.parametrize("cancel", [False, True])
async def test_cache_failed_request_releases_factory_state(cancel: bool) -> None:
    from y.prices._quote import SharedCache

    class Payload:
        pass

    cache: SharedCache[None] = SharedCache(2)
    references = []
    entered = asyncio.Event()

    async def create() -> None:
        value = Payload()
        references.append(ref(value))
        entered.set()
        if cancel:
            await asyncio.Event().wait()
        raise RuntimeError("failed load")

    task = asyncio.create_task(cache.get("key", create))
    await entered.wait()
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError, match="failed load"):
            await task
    del task
    await asyncio.sleep(0)
    gc.collect()
    assert [r() for r in references] == [None]
    assert not cache.values and not cache.flights


@run_async_test
@pytest.mark.parametrize("fail_to_none", [False, True])
async def test_zero_address_request_closes_diagnostic(
    monkeypatch: pytest.MonkeyPatch, fail_to_none: bool
) -> None:
    from brownie import ZERO_ADDRESS
    from y.prices import magic

    # ez-a-sync supplies the sync keyword at runtime.
    lookup: Any = magic.get_price

    loggers = []

    def capture(*args: Any, **kwargs: Any) -> Any:
        logger = get_price_logger(*args, **kwargs)
        loggers.append(logger)
        return logger

    monkeypatch.setattr(magic, "get_price_logger", capture)
    parent = logging.getLogger("y.prices")
    level = parent.level
    parent.setLevel(logging.DEBUG)
    try:
        if fail_to_none:
            assert (
                await lookup(ZERO_ADDRESS, BLOCK, skip_cache=True, fail_to_None=True, sync=False)
                is None
            )
        else:
            from y.exceptions import yPriceMagicError

            with pytest.raises(yPriceMagicError, match="PriceError while fetching"):
                await lookup(ZERO_ADDRESS, BLOCK, skip_cache=True, sync=False)
        await asyncio.sleep(0)
        assert len(loggers) == 1 and loggers[0].debug_task is None
    finally:
        parent.setLevel(level)


def test_price_logger_keeps_configured_parents_and_level_changes() -> None:
    from y.networks import Network

    name = f"y.prices.{Network.label()}.{TOKEN}.{BLOCK}.configured"
    parent = logging.getLogger(name)
    level = parent.level
    try:
        parent.setLevel(logging.DEBUG)
        logger = get_price_logger(TOKEN, BLOCK, extra="configured")
        assert logger.parent is parent
        assert logger.isEnabledFor(logging.DEBUG)
        parent.setLevel(logging.WARNING)
        assert not logger.isEnabledFor(logging.DEBUG)
        assert logger.isEnabledFor(logging.WARNING)
        logger.close()
        assert logging.getLogger(name) is parent
    finally:
        parent.setLevel(level)


@run_async_test
async def test_diagnostic_releases_weak_owner_between_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from y.utils import logging as price_logging

    waiting = asyncio.Event()
    ticks = 0

    async def sleep(interval: int) -> None:
        nonlocal ticks
        assert interval == 60
        ticks += 1
        if ticks > 1:
            waiting.set()
            await asyncio.Event().wait()

    monkeypatch.setattr(price_logging, "sleep", sleep)
    parent = logging.getLogger("y.prices")
    level = parent.level
    parent.setLevel(logging.DEBUG)
    try:
        logger = get_price_logger(TOKEN, BLOCK, start_task=True)
        task = logger.debug_task
        assert task is not None
        reference = ref(logger)
        try:
            await waiting.wait()
            del logger
            gc.collect()
            assert reference() is None
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    finally:
        parent.setLevel(level)
