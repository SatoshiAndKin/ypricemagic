"""Explicit valuation policy for curated USDC contracts; never token symbols."""

from typing import cast

from y import constants
from y.datatypes import PriceResult, PriceStep, UsdPrice
from y.networks import Network

USDC_VALUATION = "Fixed USDC valuation policy: 1 USDC = $1"


def fixed_usdc_price(token: str, chain: int) -> PriceResult | None:
    """Apply the same assumption at every block, including bridged USDC."""
    normalized = token.lower()
    curated = constants._STABLECOINS.get(cast(Network, chain), {})
    known = any(
        normalized == address.lower() and name in ("usdc", "usdc.e", "usdbc")
        for address, name in curated.items()
    )
    configured = getattr(constants, "usdc", None)
    if not known and not (
        chain == constants.CHAINID
        and configured is not None
        and normalized == str(configured).lower()
    ):
        return None
    return PriceResult(UsdPrice(1), [PriceStep(token, UsdPrice(1), USDC_VALUATION)])
