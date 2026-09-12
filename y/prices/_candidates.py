"""Concurrent pricing with deterministic selection and owned task cleanup."""

import asyncio
from collections.abc import Awaitable, Iterable
from dataclasses import replace
from decimal import Decimal
from logging import getLogger
from math import isfinite
from typing import SupportsFloat, TypeVar

from brownie.exceptions import ContractNotFound

from y.datatypes import PriceResult, PriceStep, UsdPrice
from y.exceptions import (
    CantFindSwapPath,
    ContractNotVerified,
    NonStandardERC20,
    PriceError,
    TokenNotFound,
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
