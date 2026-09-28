import pytest

from typing import Any, cast
from tests.fixtures import blocks_for_contract
from multicall import Call
from brownie import ZERO_ADDRESS
from y.exceptions import call_reverted
from y.prices.lending.compound import CToken, compound

CTOKENS = [
    ctoken.address
    for troller in compound.trollers.values()
    for ctoken in troller.__markets__(sync=True)
]
"""A list of CToken addresses to be tested."""


@pytest.mark.parametrize("token", CTOKENS)
def test_compound_pricing_sync(token):
    """
    Test the synchronous pricing of Compound tokens.

    This test iterates over a list of CToken addresses, retrieves the price
    for each token at various block heights, and asserts that a price is returned.

    Args:
        token: The address of the CToken to test.

    See Also:
        - :class:`~y.prices.lending.compound.CToken`
        - :func:`~y.prices.lending.compound.CToken.get_price`
    """
    print(token)
    ctoken = CToken(token)
    for block in blocks_for_contract(token):
        price = ctoken.get_price(block)
        if token.lower() == "0x1dd7950c266fb1be96180a8fdb0591f70200e018" and block == 16_531_121:
            assert cast(Any, ctoken.total_supply)(block) == 0
            assert (
                Call(
                    "0x95Af143a021DF745bc78e845b54591C53a8B3A51",
                    "oracle()(address)",
                    block_id=block,
                )()
                == ZERO_ADDRESS
            )
            assert price is None
        elif token.lower() == "0x892b14321a4fcba80669ae30bd0cd99a7ecf6ac0" and price is None:
            with pytest.raises(Exception) as exc:
                ctoken.exchange_rate(block)
            assert call_reverted(exc.value)
        else:
            assert price, f"Failed to fetch price at {block}."
        print(f"                price = {price}")


@pytest.mark.parametrize("token", CTOKENS)
@pytest.mark.asyncio_cooperative
async def test_compound_pricing_async(token):
    """
    Test the asynchronous pricing of Compound tokens.

    This test iterates over a list of CToken addresses, retrieves the price
    for each token at various block heights asynchronously, and asserts that
    a price is returned.

    Args:
        token: The address of the CToken to test.

    See Also:
        - :class:`~y.prices.lending.compound.CToken`
        - :func:`~y.prices.lending.compound.CToken.get_price`
    """
    print(token)
    ctoken = CToken(token, asynchronous=True)
    for block in blocks_for_contract(token):
        price = await compound.get_price(token, block)
        if token.lower() == "0x1dd7950c266fb1be96180a8fdb0591f70200e018" and block == 16_531_121:
            assert await ctoken.total_supply(block) == 0
            assert (
                await Call(
                    "0x95Af143a021DF745bc78e845b54591C53a8B3A51",
                    "oracle()(address)",
                    block_id=block,
                )
                == ZERO_ADDRESS
            )
            assert price is None
        elif token.lower() == "0x892b14321a4fcba80669ae30bd0cd99a7ecf6ac0" and price is None:
            with pytest.raises(Exception) as exc:
                await ctoken.exchange_rate(block)
            assert call_reverted(exc.value)
        else:
            assert price, f"Failed to fetch price at {block}."
        print(f"                price = {price}")
