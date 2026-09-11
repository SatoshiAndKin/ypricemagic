"""Reset price rows in a selected SQLite database after stopping its writers."""

import sqlite3
from pathlib import Path


def reset_prices(database: Path, chain: int, backup: Path) -> dict[str, int]:
    """Back up the database and delete only the selected chain's price rows.

    The caller must stop all writers before this operation and restart them
    afterwards to discard their memory caches. This function does not import
    the pricing engine or start database writers.
    """
    if chain <= 0:
        raise ValueError("chain must be a positive chain ID")
    database = database.resolve(strict=True)
    backup = backup.resolve()
    if database == backup:
        raise ValueError("backup must differ from the selected database")
    # Refuse to overwrite any existing backup.
    with backup.open("xb"):
        pass
    with sqlite3.connect(f"{database.as_uri()}?mode=rw", uri=True) as connection:
        with sqlite3.connect(backup) as copy:
            connection.backup(copy)
            if copy.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise RuntimeError("price-cache backup failed its integrity check")
        connection.execute("BEGIN EXCLUSIVE")
        before = connection.execute(
            'SELECT count(*) FROM "Price" WHERE token_chain = ? AND block_chain = ?',
            (chain, chain),
        ).fetchone()[0]
        total = connection.execute('SELECT count(*) FROM "Price"').fetchone()[0]
        deleted = connection.execute(
            'DELETE FROM "Price" WHERE token_chain = ? AND block_chain = ?',
            (chain, chain),
        ).rowcount
        remaining = connection.execute('SELECT count(*) FROM "Price"').fetchone()[0]
        if deleted != before or remaining != total - before:
            raise RuntimeError("price-cache row counts did not match; deletion rolled back")
    return {"chain": chain, "before": before, "deleted": deleted, "other_chain_rows": remaining}
