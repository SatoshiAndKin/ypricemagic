import asyncio
import signal

import pytest

import a_sync


class CallerInterrupted(BaseException):
    pass


@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("interruption_type", [CallerInterrupted, RuntimeError])
def test_sync_interruption_releases_request_and_preserves_original_error(
    cleanup_fails, interruption_type
):
    loop = asyncio.get_event_loop()
    existing = asyncio.all_tasks(loop)
    events = []
    error = interruption_type("This event loop is already running")

    def interrupt(signum, frame):
        raise error

    @a_sync.a_sync(default="sync")
    async def request():
        events.append("entered")
        signal.setitimer(signal.ITIMER_REAL, 0.1)
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            events.append("released")
            if cleanup_fails:
                raise ValueError("cleanup failed")

    @a_sync.a_sync(default="sync")
    async def next_request():
        return 17

    previous = signal.signal(signal.SIGALRM, interrupt)
    try:
        with pytest.raises(interruption_type) as raised:
            request()
        assert raised.value is error
        assert events == ["entered", "released"]
        assert asyncio.all_tasks(loop) == existing
        assert next_request() == 17
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        # Keep a failing baseline test from leaving work in the shared loop.
        pending = asyncio.all_tasks(loop) - existing
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))


def test_sync_interruption_preserves_independent_shared_request():
    loop = asyncio.get_event_loop()
    existing = asyncio.all_tasks(loop)
    ready = asyncio.Event()
    events = []
    error = CallerInterrupted("only this waiter was interrupted")

    async def shared_request():
        await ready.wait()
        return 73

    shared = loop.create_task(shared_request())

    def interrupt(signum, frame):
        raise error

    @a_sync.a_sync(default="sync")
    async def waiter():
        signal.setitimer(signal.ITIMER_REAL, 0.1)
        try:
            return await asyncio.shield(shared)
        finally:
            events.append("waiter released")

    previous = signal.signal(signal.SIGALRM, interrupt)
    try:
        with pytest.raises(CallerInterrupted) as raised:
            waiter()
        assert raised.value is error
        assert events == ["waiter released"]
        assert not shared.done()
        assert asyncio.all_tasks(loop) == existing | {shared}
        ready.set()
        assert loop.run_until_complete(shared) == 73
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        pending = asyncio.all_tasks(loop) - existing
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
