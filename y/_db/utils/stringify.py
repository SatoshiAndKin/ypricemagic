"""Build bulk statements with values bound by the database driver."""

from collections.abc import Iterable
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Final

UTC: Final = timezone.utc

astimezone: Final = datetime.astimezone
isoformat: Final = datetime.isoformat


def column_parameter(value: Any, provider: str) -> Any:
    """Keep binary values intact and preserve UTC dates and decimal values."""
    if value is None or isinstance(value, (bytes, str, int)):
        return value
    elif isinstance(value, Decimal):
        return str(value) if provider == "sqlite" else value
    elif isinstance(value, datetime):
        return isoformat(astimezone(value, UTC))
    raise NotImplementedError(type(value), value)


def build_query(
    provider_name: str, entity_name: str, columns: Iterable[str], items: Iterable[Iterable[Any]]
) -> tuple[str, list[tuple[Any, ...]]]:
    """Return one reusable statement and the rows for the driver's batch executor."""
    names = tuple(columns)
    if provider_name == "sqlite":
        placeholders = ",".join("?" for _ in names)
        sql = f'insert or ignore into {entity_name} ({",".join(names)}) values ({placeholders})'
    elif provider_name == "postgres":
        placeholders = ",".join("%s" for _ in names)
        sql = (
            f'insert into {entity_name} ({",".join(names)}) values ({placeholders}) '
            "on conflict do nothing"
        )
    else:
        raise NotImplementedError(provider_name)
    parameters = [tuple(column_parameter(value, provider_name) for value in row) for row in items]
    return sql, parameters
