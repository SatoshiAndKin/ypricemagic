import asyncio

import pytest

import a_sync


class CallerInterrupted(BaseException):
    pass


class InterruptingLoop(asyncio.SelectorEventLoop):
    """Inject a caller error outside the request task on every supported OS."""

    def __init__(self):
        super().__init__()
        self.interruption = None

    def _run_once(self):
        super()._run_once()
        if self.interruption is not None:
            error, self.interruption = self.interruption, None
            raise error


@pytest.fixture
def interrupting_loop():
    previous = asyncio.get_event_loop()
    loop = InterruptingLoop()
    asyncio.set_event_loop(loop)
    try:
        yield loop
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        asyncio.set_event_loop(previous)


@pytest.mark.parametrize("cleanup_fails", [False, True])
@pytest.mark.parametrize("interruption_type", [CallerInterrupted, RuntimeError])
def test_sync_interruption_releases_request_and_preserves_original_error(
    cleanup_fails, interruption_type, interrupting_loop
):
    loop = interrupting_loop
    existing = asyncio.all_tasks(loop)
    events = []
    error = interruption_type("This event loop is already running")

    @a_sync.a_sync(default="sync")
    async def request():
        events.append("entered")
        loop.interruption = error
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

    with pytest.raises(interruption_type) as raised:
        request()
    assert raised.value is error
    assert events == ["entered", "released"]
    assert asyncio.all_tasks(loop) == existing
    assert next_request() == 17


def test_sync_interruption_preserves_independent_shared_request(interrupting_loop):
    loop = interrupting_loop
    existing = asyncio.all_tasks(loop)
    ready = asyncio.Event()
    events = []
    error = CallerInterrupted("only this waiter was interrupted")

    async def shared_request():
        await ready.wait()
        return 73

    shared = loop.create_task(shared_request())

    @a_sync.a_sync(default="sync")
    async def waiter():
        loop.interruption = error
        try:
            return await asyncio.shield(shared)
        finally:
            events.append("waiter released")

    with pytest.raises(CallerInterrupted) as raised:
        waiter()
    assert raised.value is error
    assert events == ["waiter released"]
    assert not shared.done()
    assert asyncio.all_tasks(loop) == existing | {shared}
    ready.set()
    assert loop.run_until_complete(shared) == 73
