"""Bound factory log ranges and split explicit provider range-limit failures."""

from asyncio import timeout
from collections.abc import Iterable, Sequence
from logging import getLogger
from time import monotonic
from typing import Any

from aiohttp import ClientResponseError
from dank_mids.brownie_patch import dank_web3
from evmspec import Log
from evmspec.data._main import _decode_hook
from msgspec import json
from web3.types import RPCEndpoint

from y._decorators import stuck_coro_debugger
from y.datatypes import AnyAddressType, Block

# Below this range, use the existing provider policy unchanged.
SAFE_RANGE = 10_000
INDEXED_RANGE = 10_000


def indexed_chunk_size() -> int:
    """Respect explicit settings and known providers with smaller range limits."""
    from brownie import web3

    from y import ENVIRONMENT_VARIABLES as ENVS
    from y.utils.middleware import BATCH_SIZE, provider_specific_batch_sizes

    endpoint = str(getattr(web3.provider, "endpoint_uri", "")).lower()
    provider_limit = min(
        (size for provider, size in provider_specific_batch_sizes.items() if provider in endpoint),
        default=SAFE_RANGE,
    )
    return min(SAFE_RANGE, BATCH_SIZE, int(ENVS.GETLOGS_BATCH_SIZE) or SAFE_RANGE, provider_limit)


def sparse_chunk_ceiling() -> int:
    """Allow sparse Curve history to grow while honoring smaller provider limits."""
    from brownie import web3

    from y import ENVIRONMENT_VARIABLES as ENVS
    from y.utils.middleware import provider_specific_batch_sizes

    endpoint = str(getattr(web3.provider, "endpoint_uri", "")).lower()
    configured = int(ENVS.GETLOGS_BATCH_SIZE)
    return min(
        200_000,
        configured if 0 < configured < SAFE_RANGE else 200_000,
        *(size for provider, size in provider_specific_batch_sizes.items() if provider in endpoint),
    )


@stuck_coro_debugger
async def _request_logs(args: dict[str, Any]) -> list[Log]:
    """Keep range errors out of Dank's batch retry loop so callers can split."""
    from y.prices._rpc import _request_once, _retry_state_read

    provider = dank_web3.eth.w3.provider

    async def request() -> list[Log]:
        async with timeout(30):
            response = await _request_once(provider, RPCEndpoint("eth_getLogs"), [args])
        if "error" in response:
            error = response["error"]
            if (
                isinstance(error, dict)
                and error.get("code") == -32002
                and error.get("message") == "request timed out"
            ):
                # Geth can report its own deadline before the transport expires.
                # Use the same bounded retry and range splitting as a transport
                # timeout; do not classify it as missing event history.
                raise TimeoutError("RPC log request timed out") from ValueError(error)
            raise ValueError(error)
        return json.decode(json.encode(response["result"]), type=list[Log], dec_hook=_decode_hook)

    # A large timed-out scan has a bounded smaller-range recovery path.
    # Split it immediately instead of spending another transport deadline on
    # the same range. Ordinary reads retain their single timeout retry.
    width = int(args["toBlock"], 16) - int(args["fromBlock"], 16) + 1
    return await _retry_state_read(request, retry_timeouts=width <= SAFE_RANGE)


@stuck_coro_debugger
async def adaptive_logs(
    addresses: AnyAddressType | Iterable[AnyAddressType] | None,
    topics: Sequence[str | Sequence[str] | None] | None,
    start: Block,
    end: Block,
) -> list[Log]:
    """Split rejected large ranges; errors at a safe range still propagate.

    Some providers return range-limit JSON errors with HTTP 400, whose body is
    unavailable through the transport exception. Probe smaller ranges rather
    than endlessly retrying that same rejected request. An unrelated HTTP 400
    still fails once the range reaches the provider's ordinary 10,000 blocks.
    """
    args: dict[str, Any] = {"topics": topics, "fromBlock": hex(start), "toBlock": hex(end)}
    if addresses is not None:
        args["address"] = addresses
    started = monotonic()
    try:
        result = await _request_logs(args)
        getLogger(__name__).debug(
            "log range from=%s to=%s seconds=%.3f events=%s",
            start,
            end,
            monotonic() - started,
            len(result),
        )
        return result
    except (ClientResponseError, ValueError, TimeoutError) as error:
        if end <= start:
            raise
        if isinstance(error, ClientResponseError):
            if error.status != 400 or end - start + 1 <= SAFE_RANGE:
                raise
        elif isinstance(error, ValueError) and not any(
            message in str(error).lower()
            for message in (
                "log response size exceeded",
                "exceed maximum block range",
                "block range is too wide",
                "invalid block range given",
                "query returned more than",
            )
        ):
            raise
        getLogger(__name__).debug(
            "log range split from=%s to=%s seconds=%.3f error=%s",
            start,
            end,
            monotonic() - started,
            type(error).__name__,
        )
        middle = (start + end) // 2
        first = await adaptive_logs(addresses, topics, start, middle)
        return first + await adaptive_logs(addresses, topics, middle + 1, end)
