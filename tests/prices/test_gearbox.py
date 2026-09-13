from decimal import Decimal

import pytest

from tests.fixtures import mainnet_only
from y.prices.gearbox import gearbox

ddai = "0x6CFaF95457d7688022FC53e7AbE052ef8DFBbdBA"


@mainnet_only
@pytest.mark.asyncio_cooperative
async def test_is_dtoken():
    assert await gearbox.is_diesel_token(ddai) is True


@mainnet_only
@pytest.mark.asyncio_cooperative
async def test_get_price():
    # At this block, Chainlink's DAI/USD feed (round 17128) reports 99970000
    # with eight decimals. The USD value includes this historical feed price.
    dai_per_share = Decimal("1.007850150784062913")
    dai_usd = Decimal("0.9997")
    result = await gearbox.get_price(ddai, 16980000)
    assert result is not None
    assert result == dai_per_share * dai_usd
    assert result.path[-1].price == float(dai_usd)
