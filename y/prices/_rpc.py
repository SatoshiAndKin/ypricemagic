"""Block-scoped contract reads for sale estimates."""

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import lru_cache
from logging import getLogger
from time import monotonic
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

# These canonical getter layouts stay below 2.4 MiB of hexadecimal calldata,
# leaving room for JSON overhead under the measured provider payload limit.
_MAX_RESERVE_BATCH = 7500
_MAX_BALANCE_BATCH = 6250
_MAX_CODE_BATCH = 8192


def _batch_limit_error(error: Exception) -> bool:
    if isinstance(error, TimeoutError):
        return True
    if isinstance(error, ClientResponseError):
        return error.status == 413
    return isinstance(error, ValueError) and any(
        text in str(error).lower()
        for text in ("out of gas", "gas limit", "execution reverted", "response size")
    )


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
    started = monotonic()
    call = await asyncio.to_thread(Call, address, [signature, *args])
    data = await asyncio.to_thread(lambda: "0x" + _batch_call_data(call).hex())
    encoded = monotonic()
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
    received = monotonic()
    result = await asyncio.to_thread(_decode_batch_output, output, call)
    getLogger(__name__).debug(
        "native RPC signature=%s encode_seconds=%.6f transport_seconds=%.6f "
        "decode_seconds=%.6f bytes=%s",
        signature,
        encoded - started,
        received - encoded,
        monotonic() - received,
        len(output),
    )
    return result


def _batch_call_data(call: Call) -> bytes:
    """Encode canonical getter aggregates with exactly the native ABI layout."""
    if (
        call.function
        != "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])"
        or not call.args
        or len(call.args) != 2
        or call.args[0] is not False
        or not isinstance(call.args[1], (list, tuple))
    ):
        return call.data
    bodies = []
    for member in call.args[1]:
        if not isinstance(member, (list, tuple)) or len(member) != 2:
            return call.data
        target, payload = member
        if not isinstance(target, str) or len(target) != 42 or not target.startswith("0x"):
            return call.data
        if not isinstance(payload, bytes):
            return call.data
        try:
            address_bytes = bytes.fromhex(target[2:])
        except ValueError:
            return call.data
        if len(address_bytes) != 20:
            return call.data
        bodies.append(
            bytes(12)
            + address_bytes
            + (64).to_bytes(32, "big")
            + len(payload).to_bytes(32, "big")
            + payload
            + bytes(-len(payload) % 32)
        )
    cursor = 32 * len(bodies)
    offsets = []
    for body in bodies:
        offsets.append(cursor.to_bytes(32, "big"))
        cursor += len(body)
    return (
        call.signature.fourbyte
        + bytes(32)
        + (64).to_bytes(32, "big")
        + len(bodies).to_bytes(32, "big")
        + b"".join(offsets)
        + b"".join(bodies)
    )


def _getter_call_data(call: Call) -> bytes:
    """Encode canonical balance getter inputs without repeated ABI validation."""
    if call.function == "balanceOf(address)(uint256)" and call.args and len(call.args) == 1:
        holder = call.args[0]
        if isinstance(holder, str) and len(holder) == 42 and holder.startswith("0x"):
            try:
                value = bytes.fromhex(holder[2:])
            except ValueError:
                return call.data
            if len(value) == 20:
                return call.signature.fourbyte + bytes(12) + value
    return call.data


def _decode_batch_output(output: bytes, call: Call) -> Any:
    """Decode canonical batch results, with the native decoder as the fallback.

    Check every dynamic offset, boolean, length and padding byte before using
    the fast path. Unusual layouts and malformed responses retain Call's result
    and error behavior, including its unavailable result on decoding failure.
    """
    if call.returns is None:
        if call.function == (
            "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])"
        ):
            decoded = _canonical_aggregate(output)
            if decoded is not None:
                return decoded
        words = {
            "getReserves()(uint256,uint256,uint256)": 3,
            "balanceOf(address)(uint256)": 1,
        }.get(call.function)
        if words is not None and len(output) == 32 * words:
            values = tuple(
                int.from_bytes(output[i : i + 32], "big") for i in range(0, len(output), 32)
            )
            return values if words > 1 else values[0]
    return Call.decode_output(output, call.signature, call.returns)


def _canonical_aggregate(output: bytes) -> tuple[int, int, tuple[tuple[bool, bytes], ...]] | None:
    # RPC results are HexBytes. Slice ordinary bytes so each ABI word does not
    # construct another wrapper, and nested payloads retain the native bytes type.
    output = bytes(output)
    if len(output) < 128 or int.from_bytes(output[64:96], "big") != 96:
        return None
    size = int.from_bytes(output[96:128], "big")
    cursor = 128 + 32 * size
    if cursor > len(output):
        return None
    values = []
    for index in range(size):
        offset = 128 + 32 * index
        if int.from_bytes(output[offset : offset + 32], "big") != cursor - 128:
            return None
        if cursor + 96 > len(output):
            return None
        flag = int.from_bytes(output[cursor : cursor + 32], "big")
        if flag > 1 or int.from_bytes(output[cursor + 32 : cursor + 64], "big") != 64:
            return None
        length = int.from_bytes(output[cursor + 64 : cursor + 96], "big")
        end = cursor + 96 + length
        aligned = cursor + 96 + (length + 31) // 32 * 32
        if aligned > len(output) or any(output[end:aligned]):
            return None
        values.append((bool(flag), output[cursor + 96 : end]))
        cursor = aligned
    if cursor != len(output):
        return None
    return int.from_bytes(output[:32], "big"), int.from_bytes(output[32:64], "big"), tuple(values)


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
        chunks = [
            addresses[i : i + _MAX_CODE_BATCH] for i in range(0, len(addresses), _MAX_CODE_BATCH)
        ]
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
        output = bytes(HexBytes(response["result"]))
        if len(output) != 32 * len(addresses):
            raise RuntimeError("Code probe returned a different result count")
        words = tuple(int.from_bytes(output[i : i + 32]) for i in range(0, len(output), 32))
        if any(word not in (0, 1) for word in words):
            raise RuntimeError("Code probe returned an invalid presence value")
        return tuple(map(bool, words))

    try:
        return await _retry_state_read(request)
    except (TimeoutError, ValueError, ClientResponseError) as exc:
        if isinstance(exc, ValueError) and any(
            phrase in str(exc).lower()
            for phrase in (
                "state override is not supported",
                "state overrides are not supported",
                "too many arguments, want at most 2",
                "expected 2 arguments",
            )
        ):
            _unsupported_code_probes()[provider] = True
            return await _code_presence(addresses, block)
        if len(addresses) > 1 and _batch_limit_error(exc):
            middle = len(addresses) // 2
            return (
                *await _code_presence(addresses[:middle], block),
                *await _code_presence(addresses[middle:], block),
            )
        raise


@timed("pool_state")
async def reserves_batch(addresses: tuple[str, ...], block: BlockRef) -> tuple[Any, ...]:
    """Batch standard factory-pair getters at one canonical block hash.

    This is deliberately restricted to getReserves, whose factory implementations
    do not depend on the caller. Individual failures use the ordinary read path
    so transport failures and unavailable contracts retain their existing meaning.
    """
    if len(addresses) > _MAX_RESERVE_BATCH:
        raise ValueError(f"reserve batches cannot exceed {_MAX_RESERVE_BATCH} pairs")
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
                [[call.target, _getter_call_data(call)] for call in calls],
            )
        except (TimeoutError, ValueError, ClientResponseError) as exc:
            if len(addresses) <= 1 or not _batch_limit_error(exc):
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
                    value = _decode_batch_output(output, call)
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


@lru_cache(maxsize=1)
def vault_cache() -> SharedCache[tuple[Any, ...]]:
    return SharedCache(128, immutable=True, maxweight=16384, getsizeof=len)


@stuck_coro_debugger
@timed("pool_state")
async def pool_tokens_batch(
    vault: str, pool_ids: tuple[bytes, ...], block: BlockRef
) -> tuple[Any, ...]:
    """Batch Balancer's caller-independent vault inventory getter at one hash."""
    if len(pool_ids) > 128:
        raise ValueError("vault batches cannot exceed 128 pools")
    signature = "getPoolTokens(bytes32)(address[],uint256[],uint256)"

    async def individual(pool_id: bytes) -> Any:
        try:
            return await state(vault, signature, block, pool_id)
        except Exception as exc:
            if not unavailable(exc):
                raise
            return None

    async def load() -> tuple[Any, ...]:
        aggregate = MULTICALL3_ADDRESSES.get(block.chain) or MULTICALL2_ADDRESSES.get(block.chain)
        if not aggregate or not await deployed(aggregate, block):
            return tuple(await bounded_map(individual, pool_ids))
        calls = [Call(vault, [signature, pool_id]) for pool_id in pool_ids]
        try:
            number, _, outputs = await _reserve_aggregate(
                aggregate,
                "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])",
                block,
                False,
                [[call.target, _getter_call_data(call)] for call in calls],
            )
        except (TimeoutError, ValueError, ClientResponseError) as exc:
            if len(pool_ids) <= 1 or not _batch_limit_error(exc):
                raise
            middle = len(pool_ids) // 2
            return (
                *await pool_tokens_batch(vault, pool_ids[:middle], block),
                *await pool_tokens_batch(vault, pool_ids[middle:], block),
            )
        if number != block.number or len(outputs) != len(calls):
            raise RuntimeError("Vault aggregate returned a different block or result count")
        values = []
        for pool_id, call, (success, output) in zip(pool_ids, calls, outputs):
            value = Call.decode_output(output, call.signature, call.returns) if success else None
            if value is None:
                value = await individual(pool_id)
            values.append(value)
        return tuple(values)

    return await vault_cache().get((block.chain, block.hash, vault, pool_ids), load)


@timed("pool_state")
async def balances_batch(requests: tuple[tuple[str, str], ...], block: BlockRef) -> tuple[Any, ...]:
    """Batch ERC-20 balance getters without retaining token or pool objects."""
    if len(requests) > _MAX_BALANCE_BATCH:
        raise ValueError(f"balance batches cannot exceed {_MAX_BALANCE_BATCH} getters")
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
                [[call.target, _getter_call_data(call)] for call in calls],
            )
        except (TimeoutError, ValueError, ClientResponseError) as exc:
            if len(requests) <= 1 or not _batch_limit_error(exc):
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
                    value = _decode_batch_output(output, call)
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
