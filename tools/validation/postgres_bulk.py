"""Run the bulk persistence regressions against an isolated PostgreSQL server."""

import json
import os
import traceback
from pathlib import Path

from pony.orm import Database, db_session

from tests import test_bulk_memory as cases


def main() -> int:
    results = []
    for case in (
        cases.test_bulk_writes_do_not_retain_each_payload_in_sql_cache,
        cases.test_bulk_preserves_values_and_ignores_duplicate_keys,
        cases.test_failed_bulk_rolls_back_all_rows_and_allows_reuse,
        cases.test_empty_bulk_preserves_existing_rows,
    ):
        database = Database()
        database.bind(provider="postgres", user="postgres", database="postgres", host="/data")
        try:
            with db_session:
                database.execute("DROP TABLE IF EXISTS bulkmemory")
                database.execute("DROP TABLE IF EXISTS parent")
                database.execute("CREATE TABLE parent (id BIGINT PRIMARY KEY)")
                database.execute("INSERT INTO parent VALUES (1)")
                database.execute(
                    "CREATE TABLE bulkmemory (id BIGINT PRIMARY KEY, payload BYTEA, notes TEXT, "
                    "amount NUMERIC, created TEXT, parent BIGINT NOT NULL REFERENCES parent(id))"
                )
            case(database)
        except Exception:
            error = traceback.format_exc()
            with db_session:
                first = database.execute(
                    f"SELECT {','.join(cases.COLUMNS)} FROM bulkmemory ORDER BY id LIMIT 1"
                ).fetchone()
            values = []
            for value in first or ():
                detail = {"type": type(value).__name__, "value": repr(value)[:256]}
                if isinstance(value, memoryview):
                    detail.update(
                        format=value.format,
                        bytes_equal=str(value == bytes(value)),
                        data_hex=bytes(value[:64]).hex(),
                    )
                values.append(detail)
            results.append(
                {
                    "case": case.__name__,
                    "status": "failed",
                    "error": error,
                    "first_row": repr(values),
                }
            )
        else:
            results.append({"case": case.__name__, "status": "passed"})
        finally:
            database.disconnect()
    Path(os.environ["VALIDATION_REPORT"], "postgres-bulk.json").write_text(
        json.dumps(results, indent=2) + "\n"
    )
    return int(any(row["status"] != "passed" for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
