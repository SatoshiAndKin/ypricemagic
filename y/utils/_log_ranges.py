"""Sparse indexed creation events can use large ranges with bounded splitting."""

from collections.abc import Iterable, Sequence
from typing import Any

from aiohttp import ClientResponseError
from dank_mids.brownie_patch import dank_eth
from evmspec import Log

from y._decorators import stuck_coro_debugger
from y.datatypes import AnyAddressType, Block

# Below this range, use the existing provider policy unchanged.
SAFE_RANGE = 10_000
INDEXED_RANGE = 1_000_000


def indexed_chunk_size() -> int:
    """Respect explicit settings and known providers with smaller range limits."""
    from y import ENVIRONMENT_VARIABLES as ENVS
    from y.utils.middleware import BATCH_SIZE

    return int(ENVS.GETLOGS_BATCH_SIZE) or (
        BATCH_SIZE if BATCH_SIZE < SAFE_RANGE else INDEXED_RANGE
    )


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
    try:
        return await dank_eth.get_logs(args)
    except (ClientResponseError, ValueError) as error:
        if end - start + 1 <= SAFE_RANGE:
            raise
        if isinstance(error, ClientResponseError):
            if error.status != 400:
                raise
        elif not any(
            message in str(error).lower()
            for message in (
                "log response size exceeded",
                "exceed maximum block range",
                "block range is too wide",
                "query returned more than",
            )
        ):
            raise
        middle = (start + end) // 2
        first = await adaptive_logs(addresses, topics, start, middle)
        return first + await adaptive_logs(addresses, topics, middle + 1, end)
