"""Only explicitly curated USDC contracts have a fixed dollar valuation."""

import pytest

from tests.fixtures import blocks_for_contract
from y.constants import CHAINID
from y.constants import STABLECOINS as STABLECOINS
from y.prices import magic
from y.prices._usdc import fixed_usdc_price


@pytest.mark.parametrize("token,name", STABLECOINS.items())
def test_stablecoins(token: str, name: str) -> None:
    expected_fixed = name in ("usdc", "usdc.e", "usdbc")
    fixed = fixed_usdc_price(token, CHAINID)
    assert (fixed is not None) == expected_fixed
    if expected_fixed:
        for block in blocks_for_contract(token, 20):
            assert magic.get_price(token, block, skip_cache=True) == 1
