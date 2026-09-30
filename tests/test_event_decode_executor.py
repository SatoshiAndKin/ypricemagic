"""Database writes must not block event decoding and delivery."""

import asyncio
import threading
from types import SimpleNamespace
from typing import Any, cast

import pytest
from a_sync.executor import AsyncThreadPoolExecutor
from brownie.network.event import _deployment_topics
from eth_typing import ABIElement

from tests.test_pricing_correctness import run_async_test
from y.utils import events


class Processed(events.ProcessedEvents[int]):
    def _process_event(self, event: Any) -> int:
        return int(event.value)


@run_async_test
@pytest.mark.parametrize("processed", [False, True])
async def test_decode_does_not_wait_for_database_writer(
    monkeypatch: pytest.MonkeyPatch, processed: bool
) -> None:
    executor = AsyncThreadPoolExecutor(1)
    started = threading.Event()
    release = threading.Event()

    def write() -> None:
        started.set()
        assert release.wait(10)

    writer = executor.submit(write)
    try:
        assert await asyncio.to_thread(started.wait, 5)
        loader = (Processed if processed else events.Events)(
            addresses=[], topics=[], from_block=1, executor=executor
        )
        decoded: list[Any] = [SimpleNamespace(value=7), SimpleNamespace(value=9)]
        logs: list[Any] = [object(), object()]

        def decode(actual: list[Any]) -> list[Any]:
            assert actual is logs
            return decoded

        monkeypatch.setattr(events, "decode_logs", decode)
        await asyncio.wait_for(loader._extend(logs), timeout=1)
        assert loader._objects == ([7, 9] if processed else decoded)
        assert not writer.done()
    finally:
        release.set()
        await writer
        executor.shutdown()


def test_decode_empty_iterator() -> None:
    assert len(events.decode_logs(iter(()))) == 0


@pytest.mark.parametrize("struct", [False, True])
def test_decode_transfer_preserves_metadata_and_topics(
    monkeypatch: pytest.MonkeyPatch,
    struct: bool,
) -> None:
    import eth_event
    from evmspec import Log
    from evmspec.data._main import _decode_hook
    from msgspec import json

    from y.convert import to_address

    address = to_address("0x0000000000000000000000000000000000000001")
    sender = "0x0000000000000000000000000000000000000002"
    receiver = "0x0000000000000000000000000000000000000003"
    abi = [
        {
            "type": "event",
            "name": "Transfer",
            "anonymous": False,
            "inputs": [
                {"name": "from", "type": "address", "indexed": True},
                {"name": "to", "type": "address", "indexed": True},
                {"name": "value", "type": "uint256", "indexed": False},
            ],
        }
    ]
    topic_map = eth_event.get_topic_map(cast(list[ABIElement], abi))
    monkeypatch.setitem(_deployment_topics, address, topic_map)
    payload = {
        "address": address,
        "topics": [
            next(iter(topic_map)),
            "0x" + sender[2:].zfill(64),
            "0x" + receiver[2:].zfill(64),
        ],
        "data": "0x" + hex(1234567)[2:].zfill(64),
        "blockNumber": "0x1234",
        "blockHash": "0x" + "ab" * 32,
        "transactionHash": "0x" + "cd" * 32,
        "logIndex": "0x2",
        "transactionIndex": "0x3",
        "removed": False,
    }
    entry: Any = (
        json.decode(json.encode(payload), type=Log, dec_hook=_decode_hook) if struct else payload
    )
    original = entry.topics if struct else list(entry["topics"])
    decoded = events.decode_logs(iter([entry]))
    assert len(decoded) == 1
    assert list(decoded[0].values()) == [sender, receiver, 1234567]
    assert getattr(decoded[0], "block_number") == (0x1234 if struct else "0x1234")
    assert getattr(decoded[0], "transaction_hash") == entry["transactionHash"]
    assert getattr(decoded[0], "log_index") == (2 if struct else "0x2")
    assert (entry.topics if struct else entry["topics"]) == original


def test_decode_failure_restores_shared_log_topics(monkeypatch: pytest.MonkeyPatch) -> None:
    from evmspec import Log
    from evmspec.data._main import _decode_hook
    from msgspec import json

    from y.convert import to_address

    address = to_address("0x0000000000000000000000000000000000000001")
    entry = json.decode(
        json.encode(
            {
                "address": address,
                "topics": ["0x" + "ab" * 32],
                "data": "0x",
                "blockNumber": "0x1",
                "blockHash": "0x" + "ab" * 32,
                "transactionHash": "0x" + "cd" * 32,
                "logIndex": "0x0",
                "transactionIndex": "0x0",
                "removed": False,
            }
        ),
        type=Log,
        dec_hook=_decode_hook,
    )
    monkeypatch.setitem(_deployment_topics, address, {})
    topics = entry.topics
    failure = ValueError("decoder failed")

    def fail(logs: Any) -> Any:
        assert isinstance(logs[0].topics, list)
        raise failure

    monkeypatch.setattr(events, "_decode_logs", fail)
    with pytest.raises(ValueError, match="decoder failed") as caught:
        events.decode_logs([entry])
    assert caught.value is failure
    assert entry.topics is topics
