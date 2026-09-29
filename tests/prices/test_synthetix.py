import pytest
from multicall.utils import await_awaitable

from tests.fixtures import async_result, mainnet_only, sync_result
from y.exceptions import UnsupportedNetwork
from y.prices.synthetix import Synthetix

try:
    sync_synthetix = Synthetix()
    async_synthetix = Synthetix(asynchronous=True)
    SYNTHS = sync_result(sync_synthetix.synths)
except UnsupportedNetwork:
    SYNTHS = []


@mainnet_only
def test_get_synths() -> None:
    assert len(sync_result(sync_synthetix.synths)) >= 10


@mainnet_only
@pytest.mark.asyncio_cooperative
async def test_get_synths_async() -> None:
    assert len(await async_synthetix.synths) >= 10


@mainnet_only
def test_synthetix_detection() -> None:
    sLINK = "0xbBC455cb4F1B9e4bFC4B73970d360c8f032EfEE6"
    assert sync_synthetix.is_synth(sLINK) == True


@mainnet_only
@pytest.mark.asyncio_cooperative
async def test_synthetix_detection_async() -> None:
    sLINK = "0xbBC455cb4F1B9e4bFC4B73970d360c8f032EfEE6"
    assert await async_result(async_synthetix.is_synth(sLINK)) == True


@pytest.mark.parametrize("token", SYNTHS)
def test_synthetix_price(token: str) -> None:
    assert async_synthetix.get_price(token, sync=True) == await_awaitable(
        sync_synthetix.get_price(token, sync=False)
    )
