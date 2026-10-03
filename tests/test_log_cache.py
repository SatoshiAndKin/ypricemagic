"""Stored events must decode without reading or writing ORM entities."""

import importlib.util
import sqlite3
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import cast
from unittest.mock import Mock

import pytest
from evmspec.data import Address, BlockNumber, LogIndex, TransactionHash
from evmspec.data._main import _decode_hook
from evmspec.structs.log import Topic
from msgspec import ValidationError, json
from msgspec.structs import replace
from pony.orm import Database, db_session

from tests.test_pricing_correctness import run_async_test
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


def test_log_preparation_retries_lock_but_propagates_other_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pony.orm import OperationalError

    lookup = Mock(side_effect=[OperationalError(RuntimeError("database is locked")), {}, {}])
    monkeypatch.setattr(logs, "_get_dbids", lookup)
    assert logs._prepare_logs([], (), ()) == []
    assert lookup.call_count == 3
    lookup.side_effect = OperationalError(RuntimeError("invalid database schema"))
    with pytest.raises(OperationalError, match="invalid database schema"):
        logs._prepare_logs([], (), ())


@run_async_test
async def test_compact_factory_events_reuse_legacy_rows_and_deduplicate(event: Log) -> None:
    from y._db.common import default_filter_threads
    from y._db.entities import FactoryLog

    await logs.bulk_insert([event])
    await logs.bulk_insert_factory([event, event])
    cache = logs.LogCache([event.address], [event.topics[0].hex()])
    assert event.blockNumber is not None
    restored = await default_filter_threads.run(
        cache.select, int(event.blockNumber), int(event.blockNumber)
    )
    assert restored == [event]
    with db_session:
        assert FactoryLog.select(lambda row: row.address == str(event.address).lower()).count() == 1


@run_async_test
async def test_factory_writer_bounds_cache_without_changing_durability(event: Log) -> None:
    from y._db.common import default_filter_threads
    from y._db.entities import FactoryLog

    def settings() -> tuple[int, int, str]:
        with db_session:
            connection = getattr(FactoryLog, "_database_").get_connection()
            return (
                connection.execute("PRAGMA cache_size").fetchone()[0],
                connection.execute("PRAGMA synchronous").fetchone()[0],
                connection.execute("PRAGMA journal_mode").fetchone()[0],
            )

    writer = logs._factory_writer()
    before = await writer.run(settings)
    reader_before = await default_filter_threads.run(settings)
    await logs.bulk_insert_factory([event])
    after = await writer.run(settings)
    assert after[0] == -65536
    assert after[1:] == before[1:]
    assert await default_filter_threads.run(settings) == reader_before
    assert event.blockNumber is not None
    cache = logs.LogCache(event.address, [event.topics[0].hex()])
    assert event in await default_filter_threads.run(
        cache.select, int(event.blockNumber), int(event.blockNumber)
    )


@run_async_test
@pytest.mark.parametrize("limit", [512, 2048, 4096])
async def test_paged_factory_history_is_bounded_ordered_and_complete(
    event: Log, limit: int
) -> None:
    from y._db.common import default_filter_threads

    assert event.blockNumber is not None
    address = Address(f"0x{limit + 2:040x}")
    events = [
        replace(
            event,
            address=address,
            transactionHash=TransactionHash(f"0x{(limit << 32) + i // 256:064x}"),
            blockNumber=BlockNumber(int(event.blockNumber) + i // 256),
            logIndex=LogIndex(i % 256),
        )
        for i in range(8201)
    ]
    from evmspec import Log as RpcLog

    await logs.bulk_insert(cast(list[RpcLog], events[:4500]))
    await logs.bulk_insert_factory(cast(list[RpcLog], events[3700:]))
    cache = logs.LogCache([address], [event.topics[0].hex()])
    pages = []
    after = None
    while page := await default_filter_threads.run(
        cache.select_page, int(event.blockNumber), int(event.blockNumber) + 40, after, limit
    ):
        assert len(page) <= limit
        pages.extend(page)
        last = page[-1]
        after = (int(last.blockNumber), int(last.logIndex), last.transactionHash.hex())
    assert pages == events
    historical = await default_filter_threads.run(
        cache.select_page, int(event.blockNumber), int(event.blockNumber), None
    )
    assert historical == events[:256]


def test_large_token_filter_uses_selective_index_without_changing_events(
    event: Log, event_database: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from y._db.utils import utils

    assert event.blockNumber is not None
    address = Address("0x0000000000000000000000000000000000afA123")
    rows = [
        replace(
            event,
            address=address,
            transactionHash=TransactionHash(f"0x{0xABA00000 + i // 256:064x}"),
            blockNumber=BlockNumber(int(event.blockNumber) + i // 256),
            logIndex=LogIndex(i % 256),
            topics=(*event.topics, Topic(f"0x{0x123000 + i:064x}")),
        )
        for i in range(8201)
    ]
    database = event_database.db
    with db_session:
        chain = event_database.Chain(id=CHAINID)
        for row in rows:
            event_database.FactoryLog(
                chain=CHAINID,
                address=str(address).lower(),
                block=int(cast(BlockNumber, row.blockNumber)),
                log_index=int(row.logIndex),
                txhash=row.transactionHash.hex(),
                topic0=row.topics[0].strip(),
                topic1=row.topics[1].strip(),
                raw=logs._encode_log(row),
            )
    monkeypatch.setattr(logs, "FactoryLog", event_database.FactoryLog)
    monkeypatch.setattr(logs, "DbLog", event_database.Log)
    monkeypatch.setattr(utils, "get_chain", lambda **kwargs: chain)
    target = rows[4100]
    cache = logs.LogCache([address], [event.topics[0].hex(), target.topics[1].hex()])
    restored = cache.select_page(int(event.blockNumber), int(event.blockNumber) + 40, None, 4096)
    assert restored == [target]
    with db_session:
        # The native SQLite optimizer must use the token index, rather than
        # scanning an entire factory for an uncommon or absent token.
        query = (
            'EXPLAIN QUERY PLAN SELECT block,log_index,txhash,raw FROM "FactoryLog" '
            "WHERE chain=? AND address IN (?) AND topic0 IN (?) AND topic1 IN (?) "
            "AND block>=? AND block<=? ORDER BY block,log_index,txhash LIMIT 4096"
        )
        parameters = (
            CHAINID,
            str(address).lower(),
            event.topics[0].strip(),
            target.topics[1].strip(),
            int(event.blockNumber),
            int(event.blockNumber) + 40,
        )
        plan = database.get_connection().execute(query, parameters).fetchall()
    assert any("topic1" in row[3] for row in plan), plan


def test_statistics_refresh_reaches_existing_reader_connections(tmp_path: Path) -> None:
    filename = tmp_path / "factory.sqlite"
    writer = sqlite3.connect(filename)
    reader = sqlite3.connect(filename)

    class ConnectionDatabase:
        provider_name = "sqlite"

        def __init__(self, connection: sqlite3.Connection) -> None:
            self.connection = connection

        def get_connection(self) -> sqlite3.Connection:
            return self.connection

        def execute(self, sql: str) -> sqlite3.Cursor:
            return self.connection.execute(sql)

    statistics = logs._FactoryStatistics()
    writer_database = cast(Database, ConnectionDatabase(writer))
    reader_database = cast(Database, ConnectionDatabase(reader))
    query = (
        "EXPLAIN QUERY PLAN SELECT block,log_index,txhash,raw FROM FactoryLog "
        "WHERE chain=? AND address IN (?) AND topic0 IN (?) AND topic1 IN (?) "
        "AND block>=? AND block<=? ORDER BY block,log_index,txhash LIMIT 4096"
    )
    parameters = (CHAINID, "factory", "event", "target", 1, 100000)
    try:
        writer.execute(
            "CREATE TABLE FactoryLog(chain INTEGER,address TEXT,block INTEGER,log_index INTEGER,"
            "txhash TEXT,topic0 TEXT,topic1 TEXT,raw BLOB,"
            "PRIMARY KEY(chain,address,block,log_index,txhash))"
        )
        writer.execute(
            "CREATE INDEX token_index ON FactoryLog(chain,address,topic0,topic1,block,log_index)"
        )
        statistics.ensure(writer_database)
        writer.commit()
        statistics.ensure(reader_database)
        initial = reader.execute(query, parameters).fetchall()
        assert not any("token_index" in row[3] for row in initial), initial
        writer.executemany(
            "INSERT INTO FactoryLog VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    CHAINID,
                    "factory",
                    i,
                    0,
                    str(i),
                    "event",
                    "target" if i == 4000 else str(i),
                    b"[]",
                )
                for i in range(1, 8202)
            ],
        )
        writer.commit()
        statistics.ensure(writer_database, added_rows=8201)
        writer.commit()
        analyzed = writer.execute(query, parameters).fetchall()
        assert any("token_index" in row[3] for row in analyzed), analyzed
        statistics.ensure(reader_database)
        refreshed = reader.execute(query, parameters).fetchall()
        assert any("token_index" in row[3] for row in refreshed), refreshed
        assert reader.execute("SELECT block FROM FactoryLog WHERE topic1='target'").fetchall() == [
            (4000,)
        ]
    finally:
        writer.close()
        reader.close()


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
        assert result == [events[1], events[2], events[0], events[3]]
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


@pytest.mark.parametrize("limit", [0, -1, 4097])
def test_event_pages_reject_unbounded_sizes(limit: int) -> None:
    cache = logs.LogCache(None, None)
    with pytest.raises(ValueError, match="event page limit"):
        cache.select_page(1, 2, limit=limit)
