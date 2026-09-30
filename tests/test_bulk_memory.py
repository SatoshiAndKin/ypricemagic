"""Bulk writes preserve rows without retaining their payloads as SQL text."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import pony.orm.core as pony
import pytest
from pony.orm import Database, db_session

from y._db.utils import bulk

COLUMNS = ("id", "payload", "notes", "amount", "created", "parent")


class BulkMemory:
    """The bulk writer uses the entity's table name."""


@contextmanager
def sqlite_database(path: Path) -> Iterator[Database]:
    database = Database()
    database.bind(provider="sqlite", filename=str(path), create_db=True)
    with db_session:
        database.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        database.execute("INSERT INTO parent VALUES (1)")
        database.execute(
            "CREATE TABLE bulkmemory (id INTEGER PRIMARY KEY, payload BLOB, notes TEXT, "
            "amount NUMERIC, created TEXT, parent INTEGER NOT NULL REFERENCES parent(id))"
        )
    try:
        yield database
    finally:
        database.disconnect()


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    with sqlite_database(tmp_path / "bulk.sqlite") as database:
        yield database


def insert(database: Database, rows: list[tuple[Any, ...]]) -> None:
    # The native a_sync wrapper supplies the sync keyword.
    write: Any = bulk.insert
    write(BulkMemory, COLUMNS, rows, db=database, sync=True)


def rows(database: Database) -> list[tuple[Any, ...]]:
    with db_session:
        # DB-API drivers can return binary buffers with different element formats.
        # Compare their exact bytes while keeping all other column values intact.
        return [
            tuple(bytes(value) if isinstance(value, memoryview) else value for value in row)
            for row in database.execute(f"SELECT {','.join(COLUMNS)} FROM bulkmemory ORDER BY id")
        ]


def cached_sql_characters() -> int:
    # Observe retained SQL strings. Do not clear any application or ORM cache.
    cache: dict[tuple[str, str], Any] = getattr(pony, "adapted_sql_cache")
    return sum(len(sql) for sql, _ in tuple(cache) if "bulkmemory" in sql)


def test_bulk_writes_do_not_retain_each_payload_in_sql_cache(database: Database) -> None:
    before = cached_sql_characters()
    expected = []
    for index in range(128):
        row = (index, index.to_bytes(4, "big") * 1024, "payload", 1, None, 1)
        insert(database, [row])
        expected.append(row)
    assert rows(database) == expected
    assert cached_sql_characters() - before < 8192


def test_bulk_preserves_values_and_ignores_duplicate_keys(database: Database) -> None:
    timestamp = datetime(2023, 3, 11, 8, 30, tzinfo=timezone(timedelta(hours=2)))
    first = (-(2**63), b"\x00\xff'\\", "it's $quoted; \u03bb", Decimal("1.25"), timestamp, 1)
    last = (2**63 - 1, None, "last", Decimal("-2.5"), None, 1)
    insert(database, [first, last, (first[0], b"replacement", "duplicate", 9, None, 1)])
    assert rows(database) == [
        (first[0], first[1], first[2], 1.25, "2023-03-11T06:30:00+00:00", 1),
        last,
    ]


def test_failed_bulk_rolls_back_all_rows_and_allows_reuse(database: Database) -> None:
    with pytest.raises(bulk.SQLError):
        insert(database, [(1, b"valid", "first", 1, None, 1), (2, b"bad", "second", 2, None, 999)])
    assert rows(database) == []
    valid = (3, b"after failure", "third", 3, None, 1)
    insert(database, [valid])
    assert rows(database) == [valid]


def test_empty_bulk_preserves_existing_rows(database: Database) -> None:
    valid = (1, b"existing", "first", 1, None, 1)
    insert(database, [valid])
    insert(database, [])
    assert rows(database) == [valid]
