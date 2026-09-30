"""Native reference reads independent of pricing discovery and result construction."""

from typing import Any

from brownie import ZERO_ADDRESS
from dank_mids.brownie_patch import dank_web3
from eth_utils.address import to_checksum_address
from multicall import Call
from web3.exceptions import ContractLogicError

from y._decorators import stuck_coro_debugger
from y.prices._rpc import BlockRef, _retry_state_read
from y.prices.chainlink import FEEDS, registries

USD_DENOMINATION = "0x0000000000000000000000000000000000000348"
REVIEW_BLOCK_HASH = "0xb70aaad0284471dfe63bac8acd9b3690445e79fe1fcbafd19c1b08a63e465817"


@stuck_coro_debugger
async def native_read(address: str, signature: str, block: BlockRef, *args: Any) -> Any:
    """Decode contract fields directly, without feed discovery or price calculation."""
    call = Call(address, [signature, *args])
    output = await _retry_state_read(
        lambda: dank_web3.eth.call(
            {"to": call.target, "data": call.data}, block_identifier=block.identifier
        )
    )
    return Call.decode_output(output, call.signature, None)


@stuck_coro_debugger
async def expected_feed(token: str, block: BlockRef) -> str | None:
    """Read registry state directly; static aliases apply only without registry history."""
    token = token.lower()
    static = next((feed for asset, feed in FEEDS.items() if asset.lower() == token), None)
    registry = registries.get(block.chain)
    if registry and await dank_web3.eth.get_code(to_checksum_address(registry), block.identifier):
        # Registry phases advance even when a feed is removed. Query the phase
        # mapping directly, independently of Chainlink.get_feed and its event cache.
        # https://github.com/smartcontractkit/feed-registry/blob/master/contracts/FeedRegistry.sol
        phase = await native_read(
            registry, "getCurrentPhaseId(address,address)(uint16)", block, token, USD_DENOMINATION
        )
        assert phase is not None
        if phase:
            try:
                registered = await native_read(
                    registry,
                    "getPhaseFeed(address,address,uint16)(address)",
                    block,
                    token,
                    USD_DENOMINATION,
                    phase,
                )
            except ContractLogicError as exc:
                assert "Feed not found for phase" in str(exc), str(exc)
                return None
            # multicall represents a reverted subcall as an empty decoded result.
            return str(registered).lower() if registered and registered != ZERO_ADDRESS else None
    if static and await dank_web3.eth.get_code(to_checksum_address(static), block.identifier):
        return static.lower()
    return None


@stuck_coro_debugger
async def expected_feed_price(feed: str, block: BlockRef) -> float | None:
    """Reconstruct a USD value from native feed fields at the pinned block."""
    try:
        updated = await native_read(feed, "latestTimestamp()(uint256)", block)
        if updated is None:
            assert await native_read(feed, "aggregator()(address)", block) == ZERO_ADDRESS
            return None
        if updated + 86_400 < block.timestamp:
            return None
        answer = await native_read(feed, "latestAnswer()(int256)", block)
        decimals = await native_read(feed, "decimals()(uint8)", block)
    except ContractLogicError:
        # Prove removal independently; an unexplained revert must fail this test.
        assert await native_read(feed, "aggregator()(address)", block) == ZERO_ADDRESS
        return None
    return float(answer / 10**decimals)
