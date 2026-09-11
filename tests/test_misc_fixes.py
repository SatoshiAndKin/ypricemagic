"""Tests for misc bug fixes: NonStandardERC20 catch, stablecoins, Chainlink feed resolution."""

import asyncio
from unittest.mock import AsyncMock

from y.constants import STABLECOINS

# ---------------------------------------------------------------------------
# Fix 3 & 4: crvUSD address and new stablecoins
# ---------------------------------------------------------------------------


def test_crvusd_address_is_correct():
    """VAL-MISC-003: crvUSD address is the actual crvUSD token, not the ERC-1155 NFT."""
    correct_address = "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E"
    wrong_nft_address = "0xf939E0A03FB57F7cc3E4655C5262C496284665DC"
    assert correct_address in STABLECOINS, "crvUSD should be in STABLECOINS"
    assert wrong_nft_address not in STABLECOINS, "ERC-1155 NFT address should NOT be in STABLECOINS"
    assert STABLECOINS[correct_address] == "crvusd"


def test_new_stablecoins_present():
    """VAL-MISC-004: crvUSD, FRAX, PYUSD, GHO are in STABLECOINS dict."""
    expected = {
        "0xf939E0A03FB07F59A73314E73794Be0E57ac1b4E": "crvusd",
        "0x853d955aCEf822Db058eb8505911ED77F175b99e": "frax",
        "0x6c3ea9036406852006290770BEdFcAbA0e23A0e8": "pyusd",
        "0x40D16FC0246aD3160Ccc09B8D0D3A2cD28aE6C2f": "gho",
    }
    for address, name in expected.items():
        assert address in STABLECOINS, f"{name} ({address}) should be in STABLECOINS"
        assert STABLECOINS[address] == name


def test_chainlink_get_feed_falls_back_to_static_feeds(monkeypatch):
    """A registry event for another asset must not replace this asset's static feed."""
    import importlib
    from types import SimpleNamespace

    import a_sync

    module = importlib.import_module("y.prices.chainlink")
    chainlink = object.__new__(module.Chainlink)
    a_sync.ASyncGenericBase.__init__(chainlink)
    chainlink.asynchronous = True
    asset = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    static = SimpleNamespace(asset=asset, address=asset, start_block=0)
    chainlink._feeds = [static]

    async def events(to_block):
        assert to_block == 20_000_000
        yield SimpleNamespace(asset="0x0000000000000000000000000000000000000001", start_block=1)

    chainlink._feeds_from_events = SimpleNamespace(objects=events)
    monkeypatch.setattr(module, "contract_creation_block_async", AsyncMock(return_value=1))
    result = asyncio.get_event_loop().run_until_complete(
        chainlink.get_feed(asset, 20_000_000, sync=False)
    )
    assert result is static
