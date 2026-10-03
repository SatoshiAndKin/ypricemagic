"""Factory discovery must register LP tokens for each supported factory interface."""

from collections import defaultdict
from collections.abc import Callable, Generator
from importlib import import_module
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, call

import pytest

from tests.test_pricing_correctness import run_async_test

module = import_module("y.prices.stable_swap.curve")

FACTORY = "0x2db0E83599a91b508Ac268a6197b8B14F5e72840"
POOL = "0x0000000000000000000000000000000000000001"
TOKEN = "0x0000000000000000000000000000000000000002"


@run_async_test
@pytest.mark.parametrize("interface", ["get_token", "get_lp_token", "stable"])
async def test_factory_registers_the_actual_lp_token(
    monkeypatch: pytest.MonkeyPatch, interface: str
) -> None:
    contract = SimpleNamespace(address=FACTORY)
    expected = TOKEN
    if interface == "stable":
        contract.is_meta = object()
        contract.get_implementation_address = object()
        expected = POOL
    else:
        setattr(contract, interface, SimpleNamespace(coroutine=AsyncMock(return_value=TOKEN)))
    registry = SimpleNamespace(token_to_pool={}, factories=defaultdict(set))
    monkeypatch.setattr(
        module, "Contract", SimpleNamespace(coroutine=AsyncMock(return_value=contract))
    )
    monkeypatch.setattr(module, "curve", registry)
    factory = object.__new__(module.Factory)
    factory.address = FACTORY
    factory.asynchronous = True
    await factory._Factory__load_pool(POOL, False)
    assert registry.token_to_pool == {expected: POOL}
    assert registry.factories == {FACTORY: {POOL}}


@run_async_test
async def test_unknown_factory_does_not_invent_an_lp_token(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = SimpleNamespace(address=FACTORY)
    registry = SimpleNamespace(token_to_pool={}, factories=defaultdict(set))
    monkeypatch.setattr(
        module, "Contract", SimpleNamespace(coroutine=AsyncMock(return_value=contract))
    )
    monkeypatch.setattr(module, "curve", registry)
    factory = object.__new__(module.Factory)
    factory.address = FACTORY
    factory.asynchronous = True
    with pytest.raises(NotImplementedError, match=FACTORY):
        await factory._Factory__load_pool(POOL, False)
    assert not registry.token_to_pool
    assert not registry.factories


@run_async_test
async def test_registry_initialization_shares_backfill_before_loading_each_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    class StopLoading(Exception):
        pass

    class Provider:
        address = TOKEN
        identifiers = defaultdict(
            list, {module.Ids.Main_Registry: [FACTORY], module.Ids.CryptoSwap_Registry: [POOL]}
        )

        def __await__(self) -> Generator[Any, None, None]:
            return asyncio.sleep(0).__await__()

        async def _load_factories(self) -> None:
            return None

    provider = Provider()
    registry = SimpleNamespace(
        address_provider=provider,
        identifiers=provider.identifiers,
        asynchronous=True,
        _done=asyncio.Event(),
        token_to_pool={},
        registries={},
        factories={},
    )
    prefill = AsyncMock()
    monkeypatch.setattr(module, "_prefill_registry_logs", prefill, raising=False)
    loaded: list[str] = []

    async def load(address: str, **kwargs: Any) -> None:
        loaded.append(address)

    async def stop(seconds: int) -> None:
        raise StopLoading

    monkeypatch.setattr(module, "Registry", load)
    monkeypatch.setattr(module, "sleep", stop)
    with pytest.raises(StopLoading):
        await module.CurveRegistry._load_all(registry)
    assert prefill.await_args_list == [call([TOKEN]), call([FACTORY, POOL])]
    assert loaded == [FACTORY, POOL]
    assert registry._done.is_set()


@run_async_test
@pytest.mark.parametrize(
    "coverage, expected_start", [((100, 200), 101), ((0, 0), 10), ((500, 600), None)]
)
async def test_registry_prefill_reuses_and_commits_shared_coverage(
    monkeypatch: pytest.MonkeyPatch, coverage: tuple[int, int], expected_start: int | None
) -> None:
    import asyncio

    import dank_mids.brownie_patch

    import y._db.common
    import y._db.utils.logs
    import y.utils._factory_history

    addresses = [FACTORY, POOL]
    caches: dict[str, object] = {}
    completed = list(coverage)

    class Cache:
        def __init__(self, address: str, topics: object) -> None:
            self.address = address
            caches[address] = topics

        def is_cached_thru(self, start: int) -> int:
            assert start == (10 if self.address == FACTORY else 30)
            return completed[addresses.index(self.address)]

    async def run(function: Callable[..., Any], *args: Any) -> Any:
        return function(*args)

    async def scan(
        requested: list[str], topics: object, first: int, last: int, *, chunk_size: int
    ) -> list[object]:
        assert requested == addresses and topics is None
        assert first == expected_start and last == 500
        assert chunk_size >= 500
        completed[:] = [max(value, 500) for value in completed]
        return []

    owner = AsyncMock(side_effect=scan)
    future = asyncio.get_running_loop().create_future()
    future.set_result(500)
    monkeypatch.setattr(dank_mids.brownie_patch, "dank_eth", SimpleNamespace(block_number=future))
    monkeypatch.setattr(y._db.utils.logs, "LogCache", Cache)
    monkeypatch.setattr(y._db.common, "default_filter_threads", SimpleNamespace(run=run))
    monkeypatch.setattr(y.utils._factory_history, "factory_logs", owner)
    monkeypatch.setattr(
        module,
        "contract_creation_block_async",
        AsyncMock(side_effect=lambda address, **kwargs: 10 if address == FACTORY else 30),
    )
    await module._prefill_registry_logs(addresses)
    assert caches == {FACTORY: None, POOL: None}
    assert completed == [max(value, 500) for value in coverage]
    if expected_start is None:
        owner.assert_not_awaited()
    else:
        owner.assert_awaited_once()


@run_async_test
@pytest.mark.parametrize("cancel", [False, True])
async def test_registry_prefill_propagates_failure_and_releases_loader(
    monkeypatch: pytest.MonkeyPatch, cancel: bool
) -> None:
    import asyncio

    import dank_mids.brownie_patch

    import y._db.common
    import y._db.utils.logs
    import y.utils._factory_history

    async def run(function: Callable[..., Any], *args: Any) -> Any:
        return function(*args)

    entered = asyncio.Event()
    released = asyncio.Event()
    exited = asyncio.Event()

    async def scan(*args: Any, **kwargs: Any) -> list[object]:
        entered.set()
        try:
            if cancel:
                await released.wait()
            raise ConnectionError("registry scan unavailable")
        finally:
            exited.set()

    future = asyncio.get_running_loop().create_future()
    future.set_result(500)
    monkeypatch.setattr(dank_mids.brownie_patch, "dank_eth", SimpleNamespace(block_number=future))
    monkeypatch.setattr(
        y._db.utils.logs, "LogCache", lambda *args: SimpleNamespace(is_cached_thru=lambda start: 0)
    )
    monkeypatch.setattr(y._db.common, "default_filter_threads", SimpleNamespace(run=run))
    monkeypatch.setattr(y.utils._factory_history, "factory_logs", scan)
    monkeypatch.setattr(module, "contract_creation_block_async", AsyncMock(return_value=10))
    work = asyncio.create_task(module._prefill_registry_logs([FACTORY, POOL]))
    await asyncio.wait_for(entered.wait(), 1)
    if cancel:
        work.cancel()
    try:
        with pytest.raises(asyncio.CancelledError if cancel else ConnectionError):
            await work
        assert exited.is_set()
    finally:
        released.set()
        await asyncio.gather(work, return_exceptions=True)
