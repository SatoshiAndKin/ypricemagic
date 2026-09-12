"""Exact quantities, bounded work, and shared immutable quote data."""

import asyncio
from collections.abc import Awaitable, Callable, Coroutine, Hashable, Iterable
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Generic, TypeVar

from cachetools import LRUCache

from y._decorators import stuck_coro_debugger

T = TypeVar("T")
U = TypeVar("U")


def validate_amount(amount: object) -> Decimal:
    if isinstance(amount, bool) or not isinstance(amount, (int, Decimal)):
        raise TypeError("amount must be an integer or Decimal in readable token units")
    value = Decimal(amount)
    if not value.is_finite() or value <= 0:
        raise ValueError("amount must be positive and finite")
    return value


def to_base_units(amount: int | Decimal, decimals: int) -> int:
    """Convert without Decimal context rounding, including for uint256-sized inputs."""
    value = validate_amount(amount)
    numerator, denominator = value.as_integer_ratio()
    integer, remainder = divmod(numerator * 10**decimals, denominator)
    if remainder:
        raise ValueError("amount cannot be represented exactly in token base units")
    if integer >= 2**256:
        raise ValueError("amount exceeds uint256")
    return int(integer)


@stuck_coro_debugger
async def bounded_map(
    function: Callable[[T], Awaitable[U]], values: Iterable[T], workers: int = 64
) -> list[U]:
    """Create at most 64 workers, rather than one task per pool."""
    if not 1 <= workers <= 64:
        raise ValueError("workers must be between 1 and 64")
    iterator = iter(enumerate(values))
    results: dict[int, U] = {}

    async def worker() -> None:
        for index, value in iterator:
            results[index] = await function(value)

    tasks = [asyncio.create_task(worker()) for _ in range(workers)]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return [results[index] for index in range(len(results))]


@dataclass
class _Flight(Generic[T]):
    task: asyncio.Task[T]
    waiters: int = 0


class SharedCache(Generic[T]):
    """Bound completed results and isolate cancellation between active callers."""

    def __init__(self, maxsize: int, *, immutable: bool = False) -> None:
        self.values: LRUCache[Hashable, T] = LRUCache(maxsize)
        self.flights: dict[tuple[asyncio.AbstractEventLoop, Hashable], _Flight[T]] = {}
        self.immutable = immutable

    async def get(
        self,
        key: Hashable,
        factory: Callable[[], Coroutine[Any, Any, T]],
        *,
        skip_cache: bool = False
    ) -> T:
        if skip_cache:
            return await factory()
        if key in self.values:
            return self.values[key] if self.immutable else deepcopy(self.values[key])
        flight_key = (asyncio.get_running_loop(), key)
        flight = self.flights.get(flight_key)
        if flight is None:
            flight = _Flight(asyncio.create_task(factory()))
            self.flights[flight_key] = flight
        flight.waiters += 1
        try:
            result = await asyncio.shield(flight.task)
            self.values[key] = result
            return result if self.immutable else deepcopy(result)
        finally:
            flight.waiters -= 1
            if not flight.waiters:
                self.flights.pop(flight_key, None)
                if not flight.task.done():
                    flight.task.cancel()
                await asyncio.gather(flight.task, return_exceptions=True)
