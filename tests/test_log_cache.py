"""Stored events must decode without reading or writing ORM entities."""

import importlib.util
import sys
from collections.abc import Iterator
from types import ModuleType
from unittest.mock import Mock

import pytest
from evmspec.data._main import _decode_hook
from evmspec.data import Address, BlockNumber, LogIndex, TransactionHash
from evmspec.structs.log import Topic
from msgspec import ValidationError, json
from msgspec.structs import replace
from pony.orm import db_session

from y._db.log import Log
from y._db.utils import logs
from y.constants import CHAINID


@pytest.fixture
def event() -> Log:
    return json.decode(
        json.encode(
            [
                ["0x" + "ab" * 32],
                "0x0000000000000000000000000000000000000001",
                "0x0001",
                False,
                "0x1234",
                "0x" + "ef" * 32,
                "0x2",
                "0x3",
            ]
        ),
        type=Log,
        dec_hook=_decode_hook,
    )


def test_cached_json_round_trip_needs_no_database(
    event: Log, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbidden = Mock(side_effect=AssertionError("cache decoding must not access the database"))
    monkeypatch.setattr(logs, "_get_hash", forbidden)
    monkeypatch.setattr(logs, "commit", forbidden)
    encoded = logs._encode_log(event)
    assert encoded.startswith(b"[")
    for _ in range(2):
        restored = logs._decode_log(encoded)
        assert restored == event
        assert restored.address == "0x0000000000000000000000000000000000000001"
        assert restored.blockNumber == 0x1234
        assert restored.logIndex == 2
        assert restored.transactionIndex == 3
    forbidden.assert_not_called()


def test_invalid_cached_event_keeps_validation_error() -> None:
    with pytest.raises(ValidationError):
        logs._decode_log(b'["invalid topics"]')


@pytest.fixture
def event_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    from y._db import entities

    # Use the real schema with an isolated SQLite database.
    spec = importlib.util.spec_from_file_location("event_cache_test_entities", entities.__file__)
    assert spec is not None and spec.loader is not None
    isolated = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, isolated)
    spec.loader.exec_module(isolated)
    database = isolated.db
    database.bind(provider="sqlite", filename=":memory:")
    database.generate_mapping(create_tables=True)
    try:
        yield isolated
    finally:
        database.disconnect()


def test_event_cache_reads_bodies_in_one_query(
    event: Log, event_database: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from y._db.utils import utils

    isolated = event_database
    database = isolated.db
    tx_low = TransactionHash("0x" + "11" * 32)
    tx_high = TransactionHash("0x" + "22" * 32)
    events = [
        replace(event, blockNumber=BlockNumber(10), transactionHash=tx_high, logIndex=LogIndex(3)),
        replace(event, blockNumber=BlockNumber(10), transactionHash=tx_high, logIndex=LogIndex(1)),
        replace(event, blockNumber=BlockNumber(10), transactionHash=tx_low, logIndex=LogIndex(2)),
        replace(event, blockNumber=BlockNumber(11), transactionHash=tx_high, logIndex=LogIndex(0)),
        replace(event, blockNumber=BlockNumber(12), transactionHash=tx_high, logIndex=LogIndex(0)),
        replace(
            event,
            blockNumber=BlockNumber(10),
            transactionHash=tx_high,
            logIndex=LogIndex(4),
            address=Address("0x0000000000000000000000000000000000000002"),
        ),
        replace(
            event,
            blockNumber=BlockNumber(10),
            transactionHash=tx_high,
            logIndex=LogIndex(5),
            topics=(Topic("0x" + "cd" * 32),),
        ),
    ]
    with db_session:
        chain = isolated.Chain(id=1)
        for item in events:
            assert item.address is not None
            block = isolated.Block.get(chain=chain, number=item.blockNumber)
            if block is None:
                block = isolated.Block(chain=chain, number=item.blockNumber)
            tx = isolated.Hashes.get(hash=item.transactionHash.hex()[2:])
            if tx is None:
                tx = isolated.Hashes(hash=item.transactionHash.hex()[2:])
            address = isolated.Hashes.get(hash=item.address[2:])
            if address is None:
                address = isolated.Hashes(hash=item.address[2:])
            topic = isolated.LogTopic.get(topic=item.topics[0].hex()[2:])
            if topic is None:
                topic = isolated.LogTopic(topic=item.topics[0].hex()[2:])
            isolated.Log(
                block=block,
                tx=tx,
                log_index=item.logIndex,
                address=address,
                topic0=topic,
                raw=logs._encode_log(item),
            )

    monkeypatch.setattr(logs, "DbLog", isolated.Log)
    statements: list[str] = []
    try:
        with db_session:
            chain = isolated.Chain[1]
            monkeypatch.setattr(utils, "get_chain", Mock(return_value=chain))
            connection = database.get_connection()
            connection.set_trace_callback(statements.append)
            try:
                cache = logs.LogCache([event.address], [[event.topics[0]]])
                result = cache._select(10, 11)
            finally:
                connection.set_trace_callback(None)
        assert result == [events[2], events[1], events[0], events[3]]
        reads = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
        assert len(reads) == 1, reads
    finally:
        database.disconnect()


def test_batch_reference_lookup_respects_sql_limit_and_preserves_rows(
    event: Log, event_database: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated = event_database
    database = isolated.db
    hashes = tuple((f"{index:064x}",) for index in range(database.provider.max_params_count + 2))
    assert event.address is not None
    address = event.address[2:]
    event_topics = (
        event.topics[0],
        Topic("0x" + "00" * 32),
        Topic("0x" + "00" * 31 + "01"),
        Topic("0x" + "cd" * 32),
    )
    topics = tuple((logs._remove_0x_prefix(topic.strip()),) for topic in event_topics)
    with db_session:
        for index, (value,) in enumerate(hashes):
            isolated.Hashes(dbid=1000 + index, hash=value)
        isolated.Hashes(dbid=9000, hash=address)
        for index, (value,) in enumerate(topics):
            isolated.LogTopic(dbid=9010 + index, topic=value)
    monkeypatch.setattr(logs, "Hashes", isolated.Hashes)
    monkeypatch.setattr(logs, "LogTopic", isolated.LogTopic)
    events = [
        replace(event, transactionHash=TransactionHash("0x" + hashes[-1][0]), topics=event_topics),
        replace(
            event,
            transactionHash=TransactionHash("0x" + hashes[0][0]),
            topics=(),
            logIndex=LogIndex(3),
        ),
    ]
    statements: list[str] = []
    with db_session:
        connection = database.get_connection()
        connection.set_trace_callback(statements.append)
        try:
            rows = logs._prepare_logs(events, hashes + ((address,),), topics)
        finally:
            connection.set_trace_callback(None)
    assert rows == [
        (
            CHAINID,
            event.blockNumber,
            1000 + len(hashes) - 1,
            event.logIndex,
            9000,
            9010,
            9011,
            9012,
            9013,
            logs._encode_log(events[0]),
        ),
        (
            CHAINID,
            event.blockNumber,
            1000,
            3,
            9000,
            None,
            None,
            None,
            None,
            logs._encode_log(events[1]),
        ),
    ]
    reads = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    assert len(reads) == 3, reads
