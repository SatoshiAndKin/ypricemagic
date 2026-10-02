"""Canonical registry state must not wait for unrelated feed-history backfills."""

import asyncio
import importlib
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_amount_quotes import BLOCK, CHILD, TOKEN, USD
from tests.test_pricing_correctness import instance, run_async_test

module = importlib.import_module("y.prices.chainlink")
REGISTRY = "0x0000000000000000000000000000000000000301"


def oracle(monkeypatch: Any) -> Any:
    service = instance(module.Chainlink)
    service.asynchronous = True
    service.registry = REGISTRY
    service._feeds = [SimpleNamespace(address=USD, asset=TOKEN, start_block=0)]
    service._feeds_from_events = SimpleNamespace(
        objects=Mock(side_effect=AssertionError("quote must not await the full catalog"))
    )
    monkeypatch.setattr(module, "deployed", AsyncMock(return_value=True))
    return service


@run_async_test
async def test_active_registry_feed_skips_unrelated_backfill(monkeypatch: Any) -> None:
    service = oracle(monkeypatch)
    read = AsyncMock(return_value=CHILD)
    monkeypatch.setattr(module, "optional_read", read)
    feed = await service._get_feed(TOKEN, BLOCK)
    assert feed is not None and feed.address.lower() == CHILD
    read.assert_awaited_once_with(
        REGISTRY, "getFeed(address,address)(address)", BLOCK, TOKEN, module.DENOMINATIONS["USD"]
    )
    module.deployed.assert_any_await(CHILD, BLOCK)
    service._feeds_from_events.objects.assert_not_called()


@run_async_test
@pytest.mark.parametrize("registered", [None, module.ZERO_ADDRESS])
@pytest.mark.parametrize("phase", [0, 7])
@pytest.mark.parametrize("static", [True, False])
async def test_registry_phase_preserves_static_aliases_and_removals(
    monkeypatch: Any, registered: str | None, phase: int, static: bool
) -> None:
    service = oracle(monkeypatch)
    if not static:
        service._feeds = []
    read = AsyncMock(side_effect=[registered, phase])
    monkeypatch.setattr(module, "optional_read", read)
    feed = await service._get_feed(TOKEN, BLOCK)
    assert (feed.address if feed else None) == (USD if static and phase == 0 else None)
    assert read.await_args_list[1].args == (
        REGISTRY,
        "getCurrentPhaseId(address,address)(uint16)",
        BLOCK,
        TOKEN,
        module.DENOMINATIONS["USD"],
    )
    service._feeds_from_events.objects.assert_not_called()


@run_async_test
@pytest.mark.parametrize("removed", [True, False])
async def test_unavailable_phase_preserves_event_history_fallback(
    monkeypatch: Any, removed: bool
) -> None:
    service = oracle(monkeypatch)
    seen: list[int] = []

    async def events(to_block: int) -> AsyncIterator[Any]:
        seen.append(to_block)
        if removed:
            yield SimpleNamespace(asset=TOKEN, address=module.ZERO_ADDRESS, start_block=100)

    service._feeds_from_events = SimpleNamespace(objects=events)
    monkeypatch.setattr(module, "optional_read", AsyncMock(return_value=None))
    feed = await service._get_feed(TOKEN, BLOCK)
    assert (feed.address if feed else None) == (None if removed else USD)
    assert seen == [BLOCK.number]


@run_async_test
@pytest.mark.parametrize("stage", ["feed", "phase"])
@pytest.mark.parametrize(
    "error", [TimeoutError("RPC timed out"), ConnectionError("offline"), asyncio.CancelledError()]
)
async def test_registry_errors_propagate_without_catalog_fallback(
    monkeypatch: Any, stage: str, error: BaseException
) -> None:
    service = oracle(monkeypatch)
    read = AsyncMock(side_effect=[error] if stage == "feed" else [None, error])
    monkeypatch.setattr(module, "optional_read", read)
    with pytest.raises(type(error), match=str(error)):
        await service._get_feed(TOKEN, BLOCK)
    attempts = read.await_count
    read.side_effect = [CHILD]
    feed = await service._get_feed(TOKEN, BLOCK)
    assert feed is not None and feed.address.lower() == CHILD
    assert read.await_count == attempts + 1
    service._feeds_from_events.objects.assert_not_called()
