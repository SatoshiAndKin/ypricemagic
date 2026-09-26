"""Tests for Uniswap price fetching functions.

This module contains asynchronous tests for verifying price retrieval via the Uniswap multiplexer
across different Uniswap versions (V1, V2, and V3). Controlled multiplexer tests
assert deepest-viable-pool selection, independent of the highest USD quote.

See Also:
    :class:`~y.prices.dex.uniswap.uniswap.UniswapMultiplexer`
"""

from typing import Any

import pytest
from a_sync import cgather
from brownie import chain
from web3.exceptions import ContractLogicError

from tests.fixtures import mutate_addresses
from tests.test_amount_quotes import BLOCK, TOKEN, USD, market
from tests.test_pricing_correctness import run_async_test
from tests.test_quote_repairs import multiplexer_graph
from y.networks import Network
from y.prices import magic
from y.prices.dex.uniswap import v3
from y.prices.dex.uniswap.uniswap import uniswap_multiplexer

V1_TOKENS = {
    Network.Mainnet: [
        "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    ],
}.get(chain.id, [])

V2_TOKENS = {
    Network.Mainnet: [
        "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
        "0xBA11D00c5f74255f56a5E366F4F77f5A186d7f55",
        "0xc00e94Cb662C3520282E6f5717214004A7f26888",
        "0xD533a949740bb3306d119CC777fa900bA034cd52",
        "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "0x6810e776880C02933D47DB1b9fc05908e5386b96",
        "0xc944E90C64B2c07662A292be6244BDf05Cda44a7",
        "0x514910771AF9Ca656af840dff83E8264EcF986CA",
        "0x0F5D2fB29fb7d3CFeE444a200298f468908cC942",
        "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2",
        "0xec67005c4E498Ec7f55E092bd1d35cbC47C91892",
        "0x4fE83213D56308330EC302a8BD641f1d0113A4Cc",
        "0xC011a73ee8576Fb46F5E1c5751cA3B9Fe0af2a6F",
        "0x04Fa0d235C4abf4BcF4787aF4CF447DE572eF828",
        "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",
        "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
        "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        "0x0bc529c00C6401aEF6D220BE8C6Ea1667F6Ad93e",
        "0xE41d2489571d322189246DaFA5ebDe1F4699F498",
    ],
}.get(chain.id, [])

V2_TOKENS = mutate_addresses(V2_TOKENS)


@pytest.mark.parametrize("token", V1_TOKENS)
@pytest.mark.asyncio_cooperative
async def test_uniswap_v1(token, async_uni_v1):
    """Test Uniswap V1 price fetching.

    This test concurrently retrieves the price using an asynchronous Uniswap V1 caller and the generic
    :func:`~y.prices.magic.get_price` function. It verifies that the prices obtained from both methods are
    consistent within a 5% relative tolerance.

    Args:
        token: The token address to query.
        async_uni_v1: Fixture providing an asynchronous Uniswap V1 instance.

    See Also:
        :meth:`~y.prices.dex.uniswap.uniswap.UniswapMultiplexer.get_price`
    """
    price, alt_price = await cgather(
        async_uni_v1.get_price(token, None),
        magic.get_price(token, skip_cache=True, sync=False),
    )
    print(token, price, alt_price)
    # check if price is within 5% range
    assert price == pytest.approx(alt_price, rel=5e-2)


@run_async_test
@pytest.mark.parametrize("scenario", ["deep", "reverted", "zero", "excluded", "exhausted", "tie"])
async def test_uniswap_v2(monkeypatch: pytest.MonkeyPatch, scenario: str) -> None:
    """The public multiplexer selects the deepest viable pool, with stable ties."""
    pools = [market("shallow", depth=1), market("deep", depth=2)]
    rates: dict[str, Any] = {"shallow": 9, "deep": 2}
    if scenario == "reverted":
        rates["deep"] = ContractLogicError("execution reverted")
    elif scenario in ("zero", "exhausted"):
        rates["deep"] = 0
        if scenario == "exhausted":
            rates["shallow"] = 0
    elif scenario == "tie":
        pools = [market("b", depth=2), market("a", depth=2)]
        rates = {"a": 2, "b": 9}
    _, seen, _ = multiplexer_graph(monkeypatch, pools, rates)
    ignored = ("deep",) if scenario == "excluded" else ()
    result = await uniswap_multiplexer.get_price(
        TOKEN, BLOCK.number, ignore_pools=ignored, skip_cache=True
    )
    expected = None if scenario == "exhausted" else 2 if scenario in ("deep", "tie") else 9
    assert (float(result) if result is not None else None) == expected
    attempted = {
        "deep": ["deep"],
        "reverted": ["deep", "shallow"],
        "zero": ["deep", "shallow"],
        "excluded": ["shallow"],
        "exhausted": ["deep", "shallow"],
        "tie": ["a"],
    }[scenario]
    assert seen == [(pool, TOKEN, 10**6, USD) for pool in attempted]


@pytest.mark.parametrize("token", V2_TOKENS)
@pytest.mark.asyncio_cooperative
async def test_uniswap_v3(token):
    """Test Uniswap V3 price fetching.

    This test concurrently retrieves pricing data using the Uniswap V3 router and the generic
    :func:`~y.prices.magic.get_price` function. It ensures that the price returned by the Uniswap V3 router
    is within a 5% relative tolerance of the price obtained from the magic fetch.

    Args:
        token: The token address to query.

    See Also:
        :meth:`~y.prices.dex.uniswap.v3.uniswap_v3.get_price`
    """
    price, alt_price = await cgather(
        v3.uniswap_v3.get_price(token, skip_cache=True, sync=False),
        magic.get_price(token, skip_cache=True, sync=False),
    )
    print(token, price, alt_price)
    assert price == pytest.approx(alt_price, rel=5e-2)
