"""Block-scoped contract reads for sale estimates."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from logging import getLogger
from typing import Any, TypeVar, cast
from weakref import WeakKeyDictionary

from aiohttp import ClientConnectionError, ClientResponseError
from brownie import chain
from dank_mids.brownie_patch import dank_web3
from eth_abi.exceptions import DecodingError
from eth_typing import URI
from hexbytes import HexBytes
from msgspec import json
from multicall import Call
from multicall.constants import MULTICALL2_ADDRESSES, MULTICALL3_ADDRESSES
from web3 import AsyncHTTPProvider
from web3._utils.request import async_make_post_request
from web3.types import RPCEndpoint

from y._decorators import stuck_coro_debugger
from y.exceptions import call_reverted
from y.prices._candidates import _UNAVAILABLE
from y.prices._quote import SharedCache, bounded_map
from y.utils._timing import timed

_T = TypeVar("_T")


@stuck_coro_debugger
async def _retry_state_read(
    request: Callable[[], Awaitable[_T]], *, retry_timeouts: bool = True
) -> _T:
    """Retry archive misses and one transport timeout at the unchanged block identifier.

    Failures during concurrent historical reads can outlast a short retry burst.
    Keep a bounded recovery window while propagating a persistent archive miss.
    """
    transport_timeouts = 0
    for attempt in range(10):
        try:
            return await request()
        except TimeoutError:
            # One transport retry fits inside the caller's existing deadline.
            # A task cancellation remains CancelledError and is never retried.
            if not retry_timeouts or transport_timeouts or attempt == 9:
                raise
            transport_timeouts += 1
            getLogger(__name__).debug("RPC transport timeout; retrying the same block identifier")
            await asyncio.sleep(0.25)
        except ClientConnectionError as exc:
            raise ConnectionError("RPC connection failed") from exc
        except ClientResponseError as exc:
            if exc.status == 429 and attempt < 4:
                await asyncio.sleep(min(0.25 * 2**attempt, 2))
                continue
            if exc.status == 429 or exc.status >= 500:
                raise ConnectionError(f"RPC HTTP status {exc.status}") from exc
            raise
        except ValueError as exc:
            error = exc.args[0] if exc.args else None
            if (
                isinstance(error, dict)
                and error.get("code") == -32000
                and error.get("message") == "hash is not currently canonical"
            ):
                # Never read an orphan with requireCanonical disabled or switch
                # a partially evaluated quote to a different hash.
                raise ConnectionError("RPC block hash is no longer canonical") from exc
            if isinstance(error, dict) and error.get("code") == 429:
                if attempt >= 4:
                    raise ConnectionError("RPC provider rate limit exceeded") from exc
                await asyncio.sleep(min(0.25 * 2**attempt, 2))
                continue
            if (
                attempt == 9
                or not isinstance(error, dict)
                or error.get("code") != -32000
                or not isinstance(error.get("message"), str)
                or re.fullmatch(
                    r"historical state (?:0x)?[0-9a-fA-F]{64} is not available",
                    error["message"],
                )
                is None
            ):
                raise
            delay = min(0.5 * 2**attempt, 30.0)
            getLogger(__name__).debug(
                "Archive state unavailable; retrying the same block identifier in %ss (%s/9)",
                delay,
                attempt + 1,
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")


@dataclass(frozen=True)
class BlockRef:
    chain: int
    number: int
    hash: str
    timestamp: int

    @property
    def identifier(self) -> dict[str, str | bool]:
        return {"blockHash": self.hash, "requireCanonical": True}

    @classmethod
    async def resolve(cls, number: "int | BlockRef | None") -> "BlockRef":
        if isinstance(number, BlockRef):
            return number
        block = await dank_web3.eth.get_block("latest" if number is None else int(number))
        return cls(
            int(chain.id),
            int(block["number"]),
            "0x" + bytes(block["hash"]).hex(),
            int(block["timestamp"]),
        )

    async def verify(self) -> None:
        # Reads are hash-bound. Also require the block to remain canonical when
        # publishing a result, including one obtained from shared state caches.
        current = await BlockRef.resolve(self.number)
        if self.hash != current.hash:
            raise RuntimeError(f"block {self.number} changed from {self.hash} to {current.hash}")


def unavailable(exc: Exception) -> bool:
    return isinstance(exc, (*_UNAVAILABLE, DecodingError)) or call_reverted(exc)


@stuck_coro_debugger
async def read(address: str, signature: str, block: BlockRef, *args: Any) -> Any:
    """Bound the native eth_call transport at the unchanged canonical hash."""
    return await _reserve_aggregate(address, signature, block, *args)


@lru_cache(maxsize=1)
def state_cache() -> SharedCache[Any]:
    return SharedCache(16384)


@stuck_coro_debugger
async def deployed(address: str, block: BlockRef) -> bool:
    async def code() -> bool:
        from y import convert

        target = await convert.to_address_async(address)
        return bool(
            await _retry_state_read(lambda: dank_web3.eth.get_code(target, block.identifier))
        )

    return bool(await state_cache().get((block.chain, block.hash, address.lower(), "code"), code))


@timed("pool_state")
async def state(address: str, signature: str, block: BlockRef, *args: Any) -> Any:
    """Share amount-independent block state across requests and route prefixes."""
    return await state_cache().get(
        (block.chain, block.hash, address.lower(), signature, args),
        lambda: read(address, signature, block, *args),
    )


@lru_cache(maxsize=1)
def reserve_cache() -> SharedCache[tuple[Any, ...]]:
    return SharedCache(128, immutable=True, maxweight=16384, getsizeof=len)


@lru_cache(maxsize=1)
def _reserve_semaphores() -> WeakKeyDictionary[Any, asyncio.Semaphore]:
    return WeakKeyDictionary()


@stuck_coro_debugger
async def _reserve_aggregate(address: str, signature: str, block: BlockRef, *args: Any) -> Any:
    """Use native calls and decoding without the SDK's batching and retry queue."""
    call = await asyncio.to_thread(Call, address, [signature, *args])
    data = await asyncio.to_thread(lambda: "0x" + call.data.hex())
    provider = dank_web3.eth.w3.provider
    semaphore = _reserve_semaphores().setdefault(asyncio.get_running_loop(), asyncio.Semaphore(8))

    async def request() -> HexBytes:
        for attempt in range(5):
            async with semaphore, asyncio.timeout(30):
                response = await provider.make_request(
                    RPCEndpoint("eth_call"), [{"to": call.target, "data": data}, block.identifier]
                )
            if "error" not in response:
                return HexBytes(response["result"])
            error = response["error"]
            if not isinstance(error, dict) or error.get("code") != 429:
                raise ValueError(error)
            if attempt == 4:
                raise ConnectionError("RPC provider rate limit exceeded") from ValueError(error)
            getLogger(__name__).debug("reserve aggregate rate limit retry=%s", attempt + 1)
            await asyncio.sleep(min(0.25 * 2**attempt, 2))
        raise AssertionError("unreachable")

    output = await _retry_state_read(request)
    return await asyncio.to_thread(Call.decode_output, output, call.signature, call.returns)


@lru_cache(maxsize=1)
def code_cache() -> SharedCache[tuple[bool, ...]]:
    return SharedCache(128, immutable=True, maxweight=16384, getsizeof=len)


@lru_cache(maxsize=1)
def _code_semaphores() -> WeakKeyDictionary[Any, asyncio.Semaphore]:
    return WeakKeyDictionary()


async def _codes_batch(addresses: tuple[str, ...], block: BlockRef) -> tuple[bool, ...]:
    """Batch transport only; each getCode still targets the exact canonical hash."""
    native_provider = dank_web3.eth.w3.provider
    if not all(
        hasattr(native_provider, name)
        for name in ("encode_rpc_request", "endpoint_uri", "get_request_kwargs")
    ):
        return tuple(await bounded_map(lambda address: deployed(address, block), addresses))
    provider = cast(AsyncHTTPProvider, native_provider)
    requests = [
        provider.encode_rpc_request(RPCEndpoint("eth_getCode"), [address, block.identifier])
        for address in addresses
    ]
    ids = [json.decode(request)["id"] for request in requests]
    data = b"[" + b",".join(requests) + b"]"
    semaphore = _code_semaphores().setdefault(asyncio.get_running_loop(), asyncio.Semaphore(2))

    async def request() -> tuple[bool, ...]:
        for attempt in range(5):
            try:
                async with semaphore, asyncio.timeout(30):
                    raw = await async_make_post_request(
                        URI(str(provider.endpoint_uri)), data, **provider.get_request_kwargs()
                    )
                responses = json.decode(raw)
                if isinstance(responses, dict):
                    responses = [responses]
                errors = [row["error"] for row in responses if "error" in row]
                if any(isinstance(error, dict) and error.get("code") == 429 for error in errors):
                    raise ConnectionError("RPC provider rate limit exceeded")
                if errors:
                    raise ValueError(errors[0])
                by_id = {row["id"]: row for row in responses}
                if len(by_id) != len(responses) or set(by_id) != set(ids):
                    raise RuntimeError("Code batch returned different response IDs")
                return tuple(bool(HexBytes(by_id[id]["result"])) for id in ids)
            except ClientResponseError as exc:
                if exc.status != 429:
                    raise
                if attempt == 4:
                    raise ConnectionError("RPC provider rate limit exceeded") from exc
            except ConnectionError:
                if attempt == 4:
                    raise
            await asyncio.sleep(min(0.25 * 2**attempt, 2))
        raise AssertionError("unreachable")

    return await _retry_state_read(request)


async def deployed_batch(addresses: tuple[str, ...], block: BlockRef) -> tuple[bool, ...]:
    async def load() -> tuple[bool, ...]:
        chunks = [addresses[i : i + 1024] for i in range(0, len(addresses), 1024)]
        values = await bounded_map(lambda chunk: _code_presence(chunk, block), chunks, workers=2)
        return tuple(value for chunk in values for value in chunk)

    return await code_cache().get((block.chain, block.hash, addresses), load)


# solc 0.8.26, Paris, optimizer=200, no CBOR/metadata hash. Source and native
# equivalence/fuzz checks: tools/validation/code-probe. Uses only EXTCODESIZE;
# overriding the probe account never changes any inspected account's state.
_CODE_PROBE = "0x000000000000000000000000000000000000bEEF"
_CODE_RUNTIME = (
    "0x6080604052348015600f57600080fd5b50601f361615601d57600080fd5b60005b368110"
    "1560355780353b151581526020016020565b50366000f3"
)


@lru_cache(maxsize=1)
def _unsupported_code_probes() -> WeakKeyDictionary[Any, bool]:
    return WeakKeyDictionary()


async def _code_presence(addresses: tuple[str, ...], block: BlockRef) -> tuple[bool, ...]:
    provider = dank_web3.eth.w3.provider
    if provider in _unsupported_code_probes() or _CODE_PROBE.lower() in addresses:
        chunks = [addresses[i : i + 128] for i in range(0, len(addresses), 128)]
        values = await bounded_map(lambda chunk: _codes_batch(chunk, block), chunks, workers=2)
        return tuple(value for chunk in values for value in chunk)
    data = "0x" + "".join(address[2:].zfill(64) for address in addresses)
    semaphore = _reserve_semaphores().setdefault(asyncio.get_running_loop(), asyncio.Semaphore(8))

    async def request() -> tuple[bool, ...]:
        async with semaphore, asyncio.timeout(30):
            response = await provider.make_request(
                RPCEndpoint("eth_call"),
                [
                    {"to": _CODE_PROBE, "data": data},
                    block.identifier,
                    {_CODE_PROBE: {"code": _CODE_RUNTIME}},
                ],
            )
        if "error" in response:
            raise ValueError(response["error"])
        output = HexBytes(response["result"])
        if len(output) != 32 * len(addresses):
            raise RuntimeError("Code probe returned a different result count")
        words = tuple(int.from_bytes(output[i : i + 32]) for i in range(0, len(output), 32))
        if any(word not in (0, 1) for word in words):
            raise RuntimeError("Code probe returned an invalid presence value")
        return tuple(map(bool, words))

    try:
        return await _retry_state_read(request)
    except ValueError as exc:
        text = str(exc).lower()
        if not any(
            phrase in text
            for phrase in (
                "state override is not supported",
                "state overrides are not supported",
                "too many arguments, want at most 2",
                "expected 2 arguments",
            )
        ):
            raise
        _unsupported_code_probes()[provider] = True
        return await _code_presence(addresses, block)


@timed("pool_state")
async def reserves_batch(addresses: tuple[str, ...], block: BlockRef) -> tuple[Any, ...]:
    """Batch standard factory-pair getters at one canonical block hash.

    This is deliberately restricted to getReserves, whose factory implementations
    do not depend on the caller. Individual failures use the ordinary read path
    so transport failures and unavailable contracts retain their existing meaning.
    """
    if len(addresses) > 4096:
        raise ValueError("reserve batches cannot exceed 4096 pairs")
    signature = "getReserves()(uint256,uint256,uint256)"

    async def individual(address: str) -> Any:
        try:
            return await state(address, signature, block)
        except Exception as exc:
            if not unavailable(exc):
                raise
            return None

    async def load() -> tuple[Any, ...]:
        aggregate = MULTICALL3_ADDRESSES.get(block.chain) or MULTICALL2_ADDRESSES.get(block.chain)
        if not aggregate or not await deployed(aggregate, block):
            return tuple(await bounded_map(individual, addresses))
        calls = [Call(address, signature) for address in addresses]
        try:
            number, _, outputs = await _reserve_aggregate(
                aggregate,
                "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])",
                block,
                False,
                [[call.target, call.data] for call in calls],
            )
        except (TimeoutError, ValueError) as exc:
            if len(addresses) <= 1 or (
                not isinstance(exc, TimeoutError)
                and not any(
                    text in str(exc).lower()
                    for text in ("out of gas", "gas limit", "execution reverted", "response size")
                )
            ):
                raise
            middle = len(addresses) // 2
            getLogger(__name__).debug("reserve batch split pairs=%s", len(addresses))
            return (
                *await reserves_batch(addresses[:middle], block),
                *await reserves_batch(addresses[middle:], block),
            )
        if number != block.number or len(outputs) != len(calls):
            raise RuntimeError("Reserve aggregate returned a different block or result count")
        values = []
        for address, call, (success, output) in zip(addresses, calls, outputs):
            if success:
                try:
                    value = Call.decode_output(output, call.signature, call.returns)
                except DecodingError:
                    value = await individual(address)
            else:
                value = await individual(address)
            values.append(value)
        return tuple(values)

    return await reserve_cache().get((block.chain, block.hash, addresses), load)


@lru_cache(maxsize=1)
def balance_cache() -> SharedCache[tuple[Any, ...]]:
    return SharedCache(128, immutable=True, maxweight=16384, getsizeof=len)


@timed("pool_state")
async def balances_batch(requests: tuple[tuple[str, str], ...], block: BlockRef) -> tuple[Any, ...]:
    """Batch ERC-20 balance getters without retaining token or pool objects."""
    if len(requests) > 2048:
        raise ValueError("balance batches cannot exceed 2048 getters")
    signature = "balanceOf(address)(uint256)"

    async def individual(request: tuple[str, str]) -> Any:
        try:
            return await state(request[0], signature, block, request[1])
        except Exception as exc:
            if not unavailable(exc):
                raise
            return None

    async def load() -> tuple[Any, ...]:
        aggregate = MULTICALL3_ADDRESSES.get(block.chain) or MULTICALL2_ADDRESSES.get(block.chain)
        if not aggregate or not await deployed(aggregate, block):
            return tuple(await bounded_map(individual, requests))
        calls = [Call(token, [signature, holder]) for token, holder in requests]
        try:
            number, _, outputs = await _reserve_aggregate(
                aggregate,
                "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])",
                block,
                False,
                [[call.target, call.data] for call in calls],
            )
        except (TimeoutError, ValueError) as exc:
            if len(requests) <= 1 or (
                not isinstance(exc, TimeoutError)
                and not any(
                    text in str(exc).lower()
                    for text in ("out of gas", "gas limit", "execution reverted", "response size")
                )
            ):
                raise
            middle = len(requests) // 2
            return (
                *await balances_batch(requests[:middle], block),
                *await balances_batch(requests[middle:], block),
            )
        if number != block.number or len(outputs) != len(calls):
            raise RuntimeError("Balance aggregate returned a different block or result count")
        values = []
        for request, call, (success, output) in zip(requests, calls, outputs):
            if success:
                try:
                    value = Call.decode_output(output, call.signature, call.returns)
                except DecodingError:
                    value = await individual(request)
            else:
                value = await individual(request)
            values.append(value)
        return tuple(values)

    return await balance_cache().get((block.chain, block.hash, requests), load)


@stuck_coro_debugger
async def optional_read(address: str, signature: str, block: BlockRef, *args: Any) -> Any:
    try:
        return await read(address, signature, block, *args)
    except Exception as exc:
        if not unavailable(exc):
            raise
        return None
