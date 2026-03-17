"""Tests for the Decimal(terminal_price.price) fix in UniswapRouterV2.get_price.

When the deepest-pool fallback ends at a non-stablecoin terminal token (e.g. WETH),
the router calls ``magic.get_price(terminal)`` which returns a :class:`PriceResult`.
The result must be converted to Decimal via ``Decimal(result.price)`` -- calling
``Decimal(result)`` directly raises TypeError because PriceResult is a dataclass,
not a number that Decimal's constructor accepts.
"""

from decimal import Decimal, InvalidOperation

import pytest

try:
    from y.datatypes import PriceResult, PriceStep, UsdPrice

    _CAN_IMPORT = True
except Exception:
    _CAN_IMPORT = False

pytestmark = pytest.mark.skipif(
    not _CAN_IMPORT, reason="y package unavailable (dank_mids init failed)"
)


def _make_price_result(price: float) -> "PriceResult":
    """Create a minimal PriceResult for testing."""
    return PriceResult(
        price=UsdPrice(price),
        path=[
            PriceStep(
                source="test",
                input_token="0x" + "ab" * 20,
                output_token="USD",
                pool=None,
                price=price,
            )
        ],
    )


class TestDecimalFromPriceResult:
    """Verify that PriceResult cannot be passed directly to Decimal()."""

    def test_decimal_of_price_result_raises(self) -> None:
        """Decimal(PriceResult) raises -- this is the bug that was fixed."""
        result = _make_price_result(2352.50)
        with pytest.raises((TypeError, InvalidOperation)):
            Decimal(result)  # type: ignore[arg-type]

    def test_decimal_of_price_result_price_works(self) -> None:
        """Decimal(result.price) is the correct conversion (no float intermediate)."""
        result = _make_price_result(2352.50)
        d = Decimal(result.price)
        assert d == pytest.approx(Decimal("2352.5"), rel=1e-9)

    def test_multiplication_with_decimal(self) -> None:
        """Simulates the actual code path: amount_out *= Decimal(terminal_price.price)."""
        amount_out = Decimal("0.5")
        terminal_price = _make_price_result(2352.50)
        amount_out *= Decimal(terminal_price.price)
        assert amount_out == pytest.approx(Decimal("1176.25"), rel=1e-9)

    def test_zero_price_result(self) -> None:
        """A zero PriceResult is falsy -- the caller returns None before reaching Decimal."""
        result = _make_price_result(0.0)
        assert not result
        d = Decimal(result.price)
        assert d == Decimal(0)

    def test_price_result_price_is_usd_price(self) -> None:
        """result.price is a UsdPrice (float subclass), directly usable with Decimal."""
        result = _make_price_result(1234.5678)
        assert isinstance(result.price, UsdPrice)
        assert isinstance(result.price, float)
        assert Decimal(result.price) == pytest.approx(Decimal("1234.5678"), rel=1e-9)
