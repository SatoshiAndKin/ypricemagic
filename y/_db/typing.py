"""Typed interfaces for the Pony session object used by the database layer."""

from collections.abc import Callable
from types import TracebackType
from typing import ParamSpec, Protocol, TypeVar, cast

from pony.orm import db_session as _db_session

_P = ParamSpec("_P")
_T = TypeVar("_T")


class _DBSession(Protocol):
    def __call__(self, fn: Callable[_P, _T]) -> Callable[_P, _T]: ...

    def __enter__(self) -> None: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


# Pony preserves the wrapped function's signature and never suppresses an
# exception when used as a context manager. Its distributed stubs use Any.
db_session = cast(_DBSession, _db_session)
