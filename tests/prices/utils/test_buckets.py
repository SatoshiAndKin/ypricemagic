from typing import cast

import pytest
from brownie import web3

from tests.fixtures import async_result, mainnet_only, mutate_address, mutate_contract
from tests.prices.lending.test_aave import ATOKENS
from tests.prices.lending.test_compound import CTOKENS
from tests.prices.test_chainlink import FEEDS
from tests.prices.test_popsicle import POPSICLES
from tests.prices.test_synthetix import SYNTHS
from tests.test_constants import STABLECOINS
from y import convert
from y.constants import EEE_ADDRESS, WRAPPED_GAS_COIN
from y.prices.chainlink import Chainlink, chainlink
from y.prices.utils.buckets import check_bucket

STARGATE_LPS = ("0xdf0770dF86a8034b3EFEf0A1Bb3c889B8332FF56",)

# @pytest.mark.parametrize('token',ATOKENS)
# def test_check_bucket_aave(token: str):
# assert check_bucket(token) == 'atoken'


@pytest.mark.parametrize("token", ATOKENS)
@pytest.mark.asyncio_cooperative
async def test_check_bucket_aave(token: str) -> None:
    assert await check_bucket(token, sync=False) == "atoken"


@pytest.fixture(scope="module")
def finalized_feed_block() -> int:
    """Keep the live comparison at one canonical block across both lookups."""
    return int(web3.eth.get_block("finalized")["number"])


@pytest.mark.parametrize("token", FEEDS)
@pytest.mark.asyncio_cooperative
async def test_check_bucket_chainlink(token: str, finalized_feed_block: int) -> None:
    if await convert.to_address_async(token) in [
        stable for stable in STABLECOINS if not isinstance(stable, int)
    ]:
        pytest.skip(f"Not applicable to stablecoins.")
    if token in mutate_contract(WRAPPED_GAS_COIN) + mutate_address(EEE_ADDRESS):
        pytest.skip(f"Not applicable to native token.")
    # FEEDS includes historical registry entries that may since have been removed.
    # Compare both lookups at one block rather than requiring a retired feed.
    block = finalized_feed_block
    expected = (
        "chainlink feed"
        if await async_result(cast(Chainlink, chainlink).has_feed(token, block))
        else None
    )
    assert await check_bucket(token, block, sync=False) == expected


@pytest.mark.parametrize("token", CTOKENS)
@pytest.mark.asyncio_cooperative
async def test_check_bucket_compound(token: str) -> None:
    assert await check_bucket(token, sync=False) == "compound"


@pytest.mark.parametrize("token", POPSICLES)
@pytest.mark.asyncio_cooperative
async def test_check_bucket_popsicle(token: str) -> None:
    assert await check_bucket(token, sync=False) == "popsicle"


@pytest.mark.parametrize("token", STABLECOINS)
@pytest.mark.asyncio_cooperative
async def test_check_bucket_stablecoins(token: str) -> None:
    assert await check_bucket(token, sync=False) == "stable usd"


@pytest.mark.parametrize("token", SYNTHS)
@pytest.mark.asyncio_cooperative
async def test_check_bucket_synthetix(token: str) -> None:
    assert await check_bucket(token, sync=False) == "synthetix"


@mainnet_only
@pytest.mark.parametrize("token", STARGATE_LPS)
@pytest.mark.asyncio_cooperative
async def test_check_bucket_stargate(token: str) -> None:
    assert await check_bucket(token, sync=False) == "stargate lp"
