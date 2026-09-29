"""Static contracts for the public sync/async price API."""

from typing import assert_type
from y.datatypes import PriceResult
from y.prices.magic import get_price, get_prices


def synchronous() -> None:
    assert_type(get_price("0x123"), PriceResult)
    assert_type(get_price("0x123", fail_to_None=True), PriceResult | None)
    assert_type(get_prices(["0x123"]), list[PriceResult])


async def asynchronous(flag: bool) -> None:
    assert_type(await get_price("0x123", sync=False), PriceResult)
    assert_type(await get_price("0x123", fail_to_None=True, sync=False), PriceResult | None)
    assert_type(await get_price("0x123", fail_to_None=flag, sync=False), PriceResult | None)
    assert_type(await get_prices(["0x123"], sync=False), list[PriceResult])


# The upstream plugin only handles explicitly declared metaclasses. Inherited
# async classes must retain their arguments and mode-dependent result types too.
import a_sync
from y._decorators import stuck_coro_debugger


class Quote(a_sync.ASyncGenericSingleton):
    def __init__(self, asynchronous: bool = False) -> None:
        self.asynchronous = asynchronous
        super().__init__()

    async def quote(self, amount: int) -> str:
        return str(amount)


@a_sync.a_sync(default="sync")
async def echo(amount: int) -> str:
    return str(amount)


@stuck_coro_debugger
@a_sync.a_sync(default="sync")
async def debugged(amount: int) -> str:
    return str(amount)


def modes() -> None:
    assert_type(echo(2), str)
    assert_type(Quote().quote(2, sync=True), str)


async def async_modes() -> None:
    assert_type(await echo(2, sync=False), str)
    assert_type(await Quote(asynchronous=True).quote(2, sync=False), str)
    assert_type(await debugged(2, sync=False), str)


from y.contracts import Contract


def contracts() -> None:
    assert_type(Contract("0x123"), Contract)
    assert_type(Contract.from_abi("Token", "0x123", []), Contract)


"""Expected diagnostics: strict unused-ignore checking makes lost errors fail CI."""


def invalid_calls() -> None:
    echo("wrong")  # type: ignore[call-overload]
    Quote().quote("wrong", sync=True)  # type: ignore[call-overload]
    _ = get_price("0x123", sync=True, asynchronous=True)  # type: ignore[misc]
    get_price("0x123", block=object())  # type: ignore[call-overload]


async def invalid_async_calls() -> None:
    await debugged("wrong", sync=False)  # type: ignore[call-overload]
    await debugged(1, sync=True)  # type: ignore[call-overload]


class InvalidOverride(Quote):
    async def quote(self, amount: str) -> str:  # type: ignore[override]
        return amount


class InvalidBody(Quote):
    async def quote(self, amount: int) -> str:
        return amount  # type: ignore[return-value]


class BroadQuote(Quote):
    async def pool(self) -> object:
        return "pool"


class NarrowQuote(BroadQuote):
    async def pool(self) -> str:
        return "pool"


class InvalidResult(BroadQuote):
    async def quote(self, amount: int) -> int:  # type: ignore[override]
        return amount


async def specialized_result() -> None:
    assert_type(await NarrowQuote().pool(sync=False), str)
    assert_type(await debugged(1, asynchronous=True), str)


from collections.abc import AsyncIterator
from tests.fixtures import async_result, sync_result


class WiderArguments(Quote):
    async def quote(self, amount: object) -> str:
        return str(amount)


class Stream(Quote):
    async def values(self, count: int) -> AsyncIterator[int]:
        for value in range(count):
            yield value


@a_sync.a_sync(default="async")
async def queued(amount: int) -> str:
    return str(amount)


async def descriptors_and_queues() -> None:
    assert_type(await async_result(Quote().quote(1)), str)
    assert_type(sync_result(Quote().quote(1)), str)
    assert_type(await WiderArguments().quote(object(), sync=False), str)
    stream = Stream(asynchronous=True)
    assert_type(Stream.values(stream, 1), a_sync.ASyncIterator[int])
    assert_type(stream.values(1), a_sync.ASyncIterator[int])
    stream.values("bad")  # type: ignore[arg-type]
    queue = a_sync.ProcessingQueue(queued, 1)
    assert_type(await queue(1), str)
    await queue("bad")  # type: ignore[arg-type]
