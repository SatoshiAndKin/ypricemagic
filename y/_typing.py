"""Typed interfaces for dependency descriptors whose shipped stubs are incomplete."""

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Concatenate, ParamSpec, Protocol, TypeVar, cast, overload

from a_sync import ASyncIterator
from async_property import async_property as _async_property  # type: ignore[import-untyped]

_O = TypeVar("_O", contravariant=True)
_T = TypeVar("_T")
_T_co = TypeVar("_T_co", covariant=True)
_P = ParamSpec("_P")


class _AsyncProperty(Protocol[_O, _T_co]):
    @overload
    def __get__(self, instance: None, owner: type[_O]) -> "_AsyncProperty[_O, _T_co]": ...

    @overload
    def __get__(self, instance: _O, owner: type[_O] | None = None) -> Awaitable[_T_co]: ...


class _PropertyDecorator(Protocol):
    def __call__(self, fn: Callable[[_O], Awaitable[_T]]) -> _AsyncProperty[_O, _T]: ...


async_property = cast(_PropertyDecorator, _async_property)


class _AsyncIteratorMethod(Protocol[_O, _P, _T]):
    @overload
    def __get__(
        self, instance: None, owner: type[_O]
    ) -> Callable[Concatenate[_O, _P], ASyncIterator[_T]]: ...

    @overload
    def __get__(
        self, instance: _O, owner: type[_O] | None = None
    ) -> Callable[_P, ASyncIterator[_T]]: ...


class _IteratorDecorator(Protocol):
    def __call__(
        self, fn: Callable[Concatenate[_O, _P], AsyncIterator[_T]]
    ) -> _AsyncIteratorMethod[_O, _P, _T]: ...


# ASyncIterator.wrap returns an ASyncGeneratorFunction which binds self on access.
# Its distributed stub omits wrap and does not remove self from bound parameters.
async_iterator = cast(_IteratorDecorator, getattr(ASyncIterator, "wrap"))


from a_sync.a_sync.property import ASyncPropertyDescriptor
from a_sync.a_sync.property import a_sync_property as _a_sync_property


class _DualPropertyDecorator(Protocol):
    def __call__(self, fn: Callable[[_O], Awaitable[_T]]) -> ASyncPropertyDescriptor[_O, _T]: ...


# The upstream callable-or-coroutine overload otherwise infers Never for both
# type variables when used as a decorator on a coroutine method.
a_sync_property = cast(_DualPropertyDecorator, _a_sync_property)
