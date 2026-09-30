"""Tests for Uniswap price fetching functions.

This module contains asynchronous tests for verifying price retrieval via the Uniswap multiplexer
across different Uniswap versions (V1, V2, and V3). Controlled multiplexer tests
assert deepest-viable-pool selection, independent of the highest USD quote.

See Also:
    :class:`~y.prices.dex.uniswap.uniswap.UniswapMultiplexer`
"""

from decimal import Decimal, localcontext
from typing import Any

import pytest
from a_sync import cgather
from brownie import chain
from web3.exceptions import ContractLogicError

from tests.fixtures import async_result, mutate_addresses
from tests.price_expectations import (
    REVIEW_BLOCK_HASH,
    expected_feed,
    expected_feed_price,
    native_read,
)
from tests.test_amount_quotes import BLOCK, TOKEN, USD, market
from tests.test_pricing_correctness import run_async_test
from tests.test_quote_repairs import multiplexer_graph
from y.datatypes import Address
from y.networks import Network
from y.prices import magic
from y.prices._rpc import BlockRef
from y.prices.dex.uniswap import v3
from y.prices.dex.uniswap.uniswap import uniswap_multiplexer
from y.prices.dex.uniswap.v1 import UniswapV1

V1_TOKENS = dict[int, list[str]](
    {
        Network.Mainnet: [
            "0x6B175474E89094C44Da98b954EedeAC495271d0F",
            "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2",
            "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
        ],
    }
).get(chain.id, [])

V2_TOKENS = dict[int, list[str]](
    {
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
    }
).get(chain.id, [])

V2_TOKENS = mutate_addresses(V2_TOKENS)


@pytest.mark.parametrize("token", V1_TOKENS)
@pytest.mark.asyncio_cooperative
async def test_uniswap_v1(token: Address, async_uni_v1: UniswapV1) -> None:
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
    block = await BlockRef.resolve(None)
    lookup: Any = magic.get_price  # a_sync supplies the runtime sync flag.
    price, alt_price = await cgather(
        async_result(async_uni_v1.get_price(token, block.number)),
        lookup(token, block.number, skip_cache=True, sync=False),
    )
    print(token, block, price, alt_price, price.path if price is not None else None)
    # check if price is within 5% range
    assert price is not None and alt_price is not None
    assert float(price) == pytest.approx(float(alt_price), rel=5e-2)


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
    result = await async_result(
        uniswap_multiplexer.get_price(TOKEN, BLOCK.number, ignore_pools=ignored, skip_cache=True)
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
async def test_uniswap_v3(token: Address) -> None:
    """Replay full-token native quotes instead of comparing them with spot oracles."""
    # Pin independent native replay to the investigated canonical historical state.
    from eth_abi.packed import encode_packed

    from y.prices._routing import liquidity_price
    from y.prices.dex.uniswap.v3 import load_quoter

    block = await BlockRef.resolve(26_063_967)
    assert block.hash == REVIEW_BLOCK_HASH
    assert v3.uniswap_v3 is not None
    price = await v3.uniswap_v3.get_price(token, block.number, skip_cache=True, sync=False)
    token_address = str(token).lower()
    unavailable_tokens = {
        "0xec67005c4e498ec7f55e092bd1d35cbc47c91892",
        "0xba11d00c5f74255f56a5e366f4f77f5a186d7f55",
    }
    if token_address in unavailable_tokens:
        assert price is None
        quoter = await load_quoter(v3.uniswap_v3._quoter)
        path = encode_packed(
            ["address", "uint24", "address"],
            [token, 3000, "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"],
        )
        if token_address == "0xba11d00c5f74255f56a5e366f4f77f5a186d7f55":
            # BAND's native pool is at its price boundary and rejects either input.
            for amount in (10**16, 10**18):
                with pytest.raises(ContractLogicError, match="execution reverted: SPL"):
                    await quoter.quoteExactInput.coroutine(
                        path, amount, block_identifier=block.identifier
                    )
        else:
            # MLN exhausts liquidity: 0.01 and 1 MLN return the same WETH amount.
            # A full-token sale must be unavailable.
            small: int = await quoter.quoteExactInput.coroutine(
                path, 10**16, block_identifier=block.identifier
            )
            large: int = await quoter.quoteExactInput.coroutine(
                path, 10**18, block_identifier=block.identifier
            )
            assert small == large == 3838826218858
    else:
        assert price is not None
        sale = await liquidity_price(
            str(token),
            block.number,
            amount=1,
            skip_cache=True,
            first_markets=(str(v3.uniswap_v3._factory).lower(),),
        )
        assert sale is not None and sale.quote is not None
        quote = sale.quote
        decimals = await native_read(token_address, "decimals()(uint8)", block)
        assert quote.input.token == token_address
        assert quote.input.decimals == decimals
        assert quote.input.amount == 10**decimals
        assert quote.block_number == block.number and quote.block_hash == block.hash
        assert quote.steps, "an available V3 price must execute a native trade"
        current = quote.input
        for index, step in enumerate(quote.steps):
            assert step.kind == "swap" and step.protocol == "Uniswap V3"
            assert step.input == current
            assert len(step.outputs) == 1
            output = step.outputs[0]
            assert output.decimals == await native_read(output.token, "decimals()(uint8)", block)
            fee = await native_read(step.contract, "fee()(uint24)", block)
            factory = await native_read(step.contract, "factory()(address)", block)
            if index == 0:
                assert str(factory).lower() == str(v3.uniswap_v3._factory).lower()
            pool = await native_read(
                factory,
                "getPool(address,address,uint24)(address)",
                block,
                current.token,
                output.token,
                fee,
            )
            assert str(pool).lower() == step.contract.lower()
            router = next(
                router
                for router in (uniswap_multiplexer.v3, *uniswap_multiplexer.v3_forks)
                if router and str(router._factory).lower() == str(factory).lower()
            )
            native_quoter = await load_quoter(router._quoter)
            path = encode_packed(
                ["address", "uint24", "address"], [current.token, fee, output.token]
            )
            native: int | tuple[int, ...] = await native_quoter.quoteExactInput.coroutine(
                path, current.amount, block_identifier=block.identifier
            )
            assert output.amount == (native if isinstance(native, int) else native[0])
            assert output.amount > 0
            reverse = encode_packed(
                ["address", "uint24", "address"], [output.token, fee, current.token]
            )
            required: int | tuple[int, ...] = await native_quoter.quoteExactOutput.coroutine(
                reverse, output.amount + 1, block_identifier=block.identifier
            )
            assert (required if isinstance(required, int) else required[0]) > current.amount
            current = output
        assert quote.outputs == (current,)
        if current.token == "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48":
            usd = 1.0  # Explicit fixed-USDC policy, independent of routing.
        else:
            feed = await expected_feed(current.token, block)
            assert feed is not None
            native_usd = await expected_feed_price(feed, block)
            assert native_usd is not None and native_usd > 0
            usd = native_usd
        with localcontext() as context:
            context.prec = 100
            expected_usd = Decimal(current.amount) / 10**current.decimals * Decimal(str(usd))
        assert quote.total_usd == expected_usd
        assert float(sale) == float(expected_usd)
        assert float(price) == float(expected_usd)
    await block.verify()
