"""Debug-only timing for pricing stages; retain normal exception propagation."""

from collections.abc import Callable, Coroutine
from functools import wraps
from logging import DEBUG, getLogger
from time import monotonic
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


def timed(
    stage: str,
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]]:
    def decorate(
        function: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(function)
        async def measured(*args: P.args, **kwargs: P.kwargs) -> T:
            logger = getLogger(function.__module__)
            if not logger.isEnabledFor(DEBUG):
                return await function(*args, **kwargs)
            started = monotonic()
            try:
                return await function(*args, **kwargs)
            finally:
                logger.debug("pricing stage=%s seconds=%.6f", stage, monotonic() - started)
                if stage == "discovery":
                    logger.debug("pricing discovery token=%s", args[0] if args else "")

        return measured

    return decorate
