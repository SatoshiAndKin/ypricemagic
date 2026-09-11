"""Concurrent pricing with deterministic selection and owned task cleanup."""

import asyncio
from collections.abc import Awaitable, Iterable
from dataclasses import replace
from decimal import Decimal
from logging import getLogger
from math import isfinite
from typing import SupportsFloat, TypeVar

from brownie.exceptions import ContractNotFound

from y._decorators import stuck_coro_debugger
from y.datatypes import PriceResult, PriceStep, UsdPrice
from y.exceptions import (
    CantFindSwapPath,
    ContractNotVerified,
    NonStandardERC20,
    PriceError,
    TokenNotFound,
    call_reverted,
    yPriceMagicError,
)

logger = getLogger(__name__)
T = TypeVar("T")
Price = UsdPrice | PriceResult
QuotedPrice = TypeVar("QuotedPrice", bound=SupportsFloat)
_UNAVAILABLE = (
    PriceError,
    CantFindSwapPath,
    ContractNotFound,
    ContractNotVerified,
    NonStandardERC20,
    TokenNotFound,
)


def valid_price(price: object) -> bool:
    """Accept only positive, finite USD prices."""
    if price is None or isinstance(price, bool):
        return False
    if not isinstance(price, (int, float, Decimal, PriceResult)):
        return False
    try:
        value = float(price)
    except (OverflowError, ValueError):
        return False
    return value > 0 and isfinite(value)


async def gather_owned(coros: Iterable[Awaitable[T]]) -> list[T]:
    """Start all calls and drain the tasks on success, failure, or cancellation.

    Pass owned coroutines. Shield shared registry loaders at their owners.
    """
    tasks: list[asyncio.Future[T]] = []
    try:
        tasks.extend(asyncio.ensure_future(coro) for coro in coros)
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@stuck_coro_debugger
async def select_price(
    candidates: Iterable[tuple[str, Awaitable[QuotedPrice | None]]],
) -> tuple[QuotedPrice | None, str | None]:
    """Await every candidate, then select the highest valid USD price.

    Source keys encode protocol, address, and route. Lexical key order breaks
    exact price ties. Expected missing or reverted quotes are unavailable.
    """
    ordered = sorted(candidates, key=lambda candidate: candidate[0])

    async def quote(source: str, coro: Awaitable[QuotedPrice | None]) -> QuotedPrice | None:
        try:
            result = await coro
        except yPriceMagicError as exc:
            if not isinstance(exc.exception, _UNAVAILABLE):
                raise
            logger.debug("unavailable candidate %s: %s", source, exc)
            return None
        except _UNAVAILABLE as exc:
            logger.debug("unavailable candidate %s: %s", source, exc)
            return None
        except Exception as exc:
            if not call_reverted(exc):
                logger.debug("failed candidate %s", source, exc_info=True)
                raise
            logger.debug("reverted candidate %s: %s", source, exc)
            return None
        logger.debug("candidate %s -> %s", source, result)
        return result if valid_price(result) else None

    results = await gather_owned(quote(source, coro) for source, coro in ordered)
    best: QuotedPrice | None = None
    selected: str | None = None
    for (source, _), result in zip(ordered, results):
        if result is not None and (best is None or float(result) > float(best)):
            best, selected = result, source
    logger.debug("selected candidate %s -> %s", selected, best)
    return best, selected


def derive_price(
    token: object, price: SupportsFloat, source: str, *children: object
) -> PriceResult:
    """Put the conversion first and copy child paths without changing their prices."""
    return PriceResult(
        UsdPrice(float(price)),
        [PriceStep(str(token), UsdPrice(float(price)), source)]
        + [
            replace(step)
            for child in children
            if isinstance(child, PriceResult)
            for step in child.path
        ],
    )


def pool_address(pool: object) -> str:
    return str(getattr(pool, "address", pool)).lower()


def pool_is_ignored(pool: object, ignore_pools: Iterable[object]) -> bool:
    address = pool_address(pool)
    return any(address == pool_address(ignored) for ignored in ignore_pools)
