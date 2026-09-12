"""Block-scoped contract reads for sale estimates."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from brownie import chain
from dank_mids.brownie_patch import dank_web3
from eth_abi.exceptions import DecodingError
from multicall import Call

from y._decorators import stuck_coro_debugger
from y.exceptions import call_reverted
from y.prices._candidates import _UNAVAILABLE
from y.prices._quote import SharedCache


@dataclass(frozen=True)
class BlockRef:
    chain: int
    number: int
    hash: str
    timestamp: int

    @classmethod
    async def resolve(cls, number: int | None) -> "BlockRef":
        block = await dank_web3.eth.get_block("latest" if number is None else int(number))
        return cls(
            int(chain.id),
            int(block["number"]),
            "0x" + bytes(block["hash"]).hex(),
            int(block["timestamp"]),
        )

    async def verify(self) -> None:
        # Existing contract/discovery APIs accept block numbers. Reject the entire
        # result on a reorg; never publish it under a different block's hash.
        current = await BlockRef.resolve(self.number)
        if self.hash != current.hash:
            raise RuntimeError(f"block {self.number} changed from {self.hash} to {current.hash}")


def unavailable(exc: Exception) -> bool:
    return isinstance(exc, (*_UNAVAILABLE, DecodingError)) or call_reverted(exc)


@stuck_coro_debugger
async def read(address: str, signature: str, block: BlockRef, *args: Any) -> Any:
    """Use the repository's native call path; never send a transaction."""
    return await Call(address, [signature, *args], block_id=block.number)


@lru_cache(maxsize=1)
def state_cache() -> SharedCache[Any]:
    return SharedCache(16384)


async def state(address: str, signature: str, block: BlockRef, *args: Any) -> Any:
    """Share amount-independent block state across requests and route prefixes."""
    return await state_cache().get(
        (block.chain, block.hash, address.lower(), signature, args),
        lambda: read(address, signature, block, *args),
    )


@stuck_coro_debugger
async def optional_read(address: str, signature: str, block: BlockRef, *args: Any) -> Any:
    try:
        return await read(address, signature, block, *args)
    except Exception as exc:
        if not unavailable(exc):
            raise
        return None
