"""Tests for misc bug fixes: NonStandardERC20 catch, stablecoins, Chainlink feed resolution."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from brownie import ZERO_ADDRESS
from eth_abi.abi import encode
from eth_utils.crypto import keccak
from web3.exceptions import ContractLogicError

from tests.test_pricing_correctness import run_async_test
from y import convert
from y.constants import STABLECOINS

# ---------------------------------------------------------------------------
# Fix 3 & 4: crvUSD address and new stablecoins
# ---------------------------------------------------------------------------


def test_crvusd_address_is_correct() -> None:
    """VAL-MISC-003: crvUSD address is the actual crvUSD token, not the ERC-1155 NFT."""
    correct_address = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"
    wrong_nft_address = "0xf939E0A03FB57F7cc3E4655C5262C496284665DC"
    assert correct_address in STABLECOINS, "crvUSD should be in STABLECOINS"
    assert wrong_nft_address not in STABLECOINS, "ERC-1155 NFT address should NOT be in STABLECOINS"
    assert STABLECOINS[convert.to_address(correct_address)] == "crvusd"


def test_new_stablecoins_present() -> None:
    """VAL-MISC-004: crvUSD, FRAX, PYUSD, GHO are in STABLECOINS dict."""
    expected = {
        "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E": "crvusd",
        "0x853d955aCEf822Db058eb8505911ED77F175b99e": "frax",
        "0x6c3ea9036406852006290770BEdFcAbA0e23A0e8": "pyusd",
        "0x40D16FC0246aD3160Ccc09B8D0D3A2cD28aE6C2f": "gho",
    }
    for address, name in expected.items():
        assert address in STABLECOINS, f"{name} ({address}) should be in STABLECOINS"
        assert STABLECOINS[convert.to_address(address)] == name


def test_chainlink_get_feed_falls_back_to_static_feeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """A registry event for another asset must not replace this asset's static feed."""
    import importlib
    from types import SimpleNamespace

    import a_sync

    from y.prices._rpc import BlockRef

    module = importlib.import_module("y.prices.chainlink")
    chainlink = object.__new__(module.Chainlink)
    a_sync.ASyncGenericBase.__init__(chainlink)
    chainlink.asynchronous = True
    asset = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    static = SimpleNamespace(asset=asset, address=asset, start_block=0)
    chainlink._feeds = [static]
    chainlink.registry = "0x0000000000000000000000000000000000000100"
    block = BlockRef(1, 20_000_000, "0x" + "12" * 32, 1_700_000_000)

    async def events(to_block: int) -> AsyncIterator[Any]:
        assert to_block == 20_000_000
        yield SimpleNamespace(asset="0x0000000000000000000000000000000000000001", start_block=1)

    chainlink._feeds_from_events = SimpleNamespace(objects=events)
    deployed = AsyncMock(return_value=True)
    registered = AsyncMock(return_value=module.ZERO_ADDRESS)
    monkeypatch.setattr(module, "deployed", deployed)
    monkeypatch.setattr(module, "optional_read", registered)
    result = asyncio.get_event_loop().run_until_complete(
        chainlink.get_feed(asset, block, sync=False)
    )
    assert result is static
    registered.assert_awaited_once_with(
        chainlink.registry,
        "getFeed(address,address)(address)",
        block,
        asset,
        module.DENOMINATIONS["USD"],
    )
    assert deployed.await_count == 2
    deployed.assert_awaited_with(static.address, block)


@run_async_test
@pytest.mark.parametrize(
    "response",
    ["legacy_revert", "legacy_empty", "removed", "active_stale", "active_fresh", "legacy_fresh"],
)
async def test_latest_feed_validation_handles_legacy_and_removed_aggregators(
    monkeypatch: Any, response: str
) -> None:
    from tests.prices import test_chainlink as fixture
    from y.prices import _rpc
    from y.prices.chainlink import Feed

    token = "0x0000000000000000000000000000000000000101"
    block = _rpc.BlockRef(1, 20_000_000, "0x" + "12" * 32, 1_700_000_000)
    feed = Feed(token, token, asynchronous=True)
    seen: list[bytes] = []

    async def rpc(transaction: dict[str, Any], *, block_identifier: Any) -> bytes:
        assert block_identifier == block.identifier
        assert transaction["to"].lower() == token
        data = bytes(transaction["data"])
        seen.append(data)
        if data == keccak(text="aggregator()")[:4]:
            if response in ("legacy_revert", "legacy_fresh"):
                raise ContractLogicError("execution reverted")
            if response == "legacy_empty":
                return b""
            return encode(["address"], [ZERO_ADDRESS if response == "removed" else token])
        assert response != "removed", "removed aggregators must not query a reverting timestamp"
        assert data == keccak(text="latestTimestamp()")[:4]
        return encode(
            ["uint256"],
            [block.timestamp if response.endswith("fresh") else block.timestamp - 86401],
        )

    price, get_feed = AsyncMock(return_value=None), AsyncMock(return_value=feed)
    monkeypatch.setattr(fixture, "chainlink", SimpleNamespace(get_price=price, get_feed=get_feed))
    monkeypatch.setattr(_rpc.BlockRef, "resolve", AsyncMock(return_value=block))
    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=rpc)))
    if response == "removed":
        await fixture.test_chainlink_latest(token)
    elif response.endswith("fresh"):
        with pytest.raises(pytest.fail.Exception, match="active aggregator"):
            await fixture.test_chainlink_latest(token)
    else:
        with pytest.raises(pytest.skip.Exception, match="feed is stale"):
            await fixture.test_chainlink_latest(token)
    assert seen == [keccak(text="aggregator()")[:4]] + (
        [] if response == "removed" else [keccak(text="latestTimestamp()")[:4]]
    )
    price.assert_awaited_once_with(token, block=block.number)
    get_feed.assert_awaited_once_with(token, block=block)


@run_async_test
@pytest.mark.parametrize(
    "error", [TypeError("bad decoder"), RuntimeError("RPC failed"), asyncio.CancelledError()]
)
async def test_latest_feed_validation_propagates_unexpected_errors(
    monkeypatch: Any, error: BaseException
) -> None:
    from tests.prices import test_chainlink as fixture
    from y.prices import _rpc

    token = "0x0000000000000000000000000000000000000101"
    block = _rpc.BlockRef(1, 20_000_000, "0x" + "12" * 32, 1_700_000_000)
    rpc = AsyncMock(side_effect=error)
    monkeypatch.setattr(
        fixture,
        "chainlink",
        SimpleNamespace(
            get_price=AsyncMock(return_value=None),
            get_feed=AsyncMock(return_value=SimpleNamespace(address=token)),
        ),
    )
    monkeypatch.setattr(_rpc.BlockRef, "resolve", AsyncMock(return_value=block))
    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=rpc)))
    with pytest.raises(type(error)) as raised:
        await fixture.test_chainlink_latest(token)
    assert raised.value is error
    rpc.assert_awaited_once()
