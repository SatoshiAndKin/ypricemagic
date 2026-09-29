from tests.fixtures import async_result
from dank_mids.brownie_patch import dank_eth
import pytest
from brownie import ZERO_ADDRESS, chain
from multicall import Call

from tests.fixtures import blocks_for_contract, sync_result
from tests.test_constants import STABLECOINS
from y.classes.common import ERC20
from y.constants import WRAPPED_GAS_COIN, wbtc
from y.contracts import Contract
from y.exceptions import NoProxyImplementation, call_reverted
from y.networks import Network

TOKENS: list[str] = [str(token) for token in STABLECOINS] + [str(WRAPPED_GAS_COIN)]
if wbtc is not None:
    TOKENS.append(wbtc.address)

if chain.id == Network.Mainnet:
    # MKR symbol and name methods return bytes, we want to test that our code returns strings
    MKR = "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2"
    TOKENS.append(MKR)

OLD_SUSD = "0x57Ab1E02fEE23774580C119740129eAC7081e9D3"

TOKENS_BY_BLOCK = [(token, block) for token in TOKENS for block in blocks_for_contract(token)]


@pytest.mark.parametrize("token", TOKENS)
def test_erc20_sync(token: str | ERC20) -> None:
    """
    Test the synchronous functionality of the :class:`~y.classes.common.ERC20` class.

    This test checks various properties and methods of the :class:`~y.classes.common.ERC20` class for a given token,
    including interactions with the :class:`~y.contracts.Contract` class to fetch the contract for the token.

    Args:
        token: The address of the token to test.

    Raises:
        AssertionError: If any of the assertions fail.

    Note:
        This test will be skipped for the old sUSD token with the address
        `0x57Ab1E02fEE23774580C119740129eAC7081e9D3`.

    See Also:
        - :class:`~y.classes.common.ERC20`
        - :class:`~y.contracts.Contract`
    """
    token = ERC20(token)

    if token.address == OLD_SUSD:
        pytest.skip("Not applicable to deprecated sUSD.")

    block = chain.height
    assert isinstance(token.contract, Contract), f"Cannot fetch contract for token {token}"
    assert isinstance(token.build_name, str), f"Cannot fetch build name for token {token}"
    assert isinstance(token.symbol, str), f"Cannot fetch symbol for token {token}"
    assert isinstance(token.name, str), f"Cannot fetch name for token {token}"
    assert 10 ** sync_result(token.decimals) == sync_result(
        token.scale
    ), f"Incorrect scale fetched for token {token}"
    assert sync_result(token.total_supply(block)) / sync_result(token.scale) == sync_result(
        token.total_supply_readable(block)
    ), f"Incorrect total supply readable for token {token}"
    assert token.price(), f"Cannot fetch price for token {token}"


@pytest.mark.parametrize("token", TOKENS)
@pytest.mark.asyncio_cooperative
async def test_erc20_async(token: str | ERC20) -> None:
    """
    Test the asynchronous functionality of the :class:`~y.classes.common.ERC20` class.

    This test checks various properties and methods of the :class:`~y.classes.common.ERC20` class for a given token asynchronously,
    including interactions with the :class:`~y.contracts.Contract` class to fetch the contract for the token.

    Args:
        token: The address of the token to test.

    Raises:
        AssertionError: If any of the assertions fail.

    Note:
        This test will be skipped for the old sUSD token with the address
        `0x57Ab1E02fEE23774580C119740129eAC7081e9D3`.

    See Also:
        - :class:`~y.classes.common.ERC20`
        - :class:`~y.contracts.Contract`
        - :mod:`dank_mids` for asynchronous operations
    """
    token = ERC20(token, asynchronous=True)

    if token.address == OLD_SUSD:
        pytest.skip("Not applicable to deprecated sUSD.")

    block = await dank_eth.block_number
    assert isinstance(token.contract, Contract), f"Cannot fetch contract for token {token}"
    assert isinstance(await token.build_name, str), f"Cannot fetch build name for token {token}"
    assert isinstance(await token.symbol, str), f"Cannot fetch symbol for token {token}"
    assert isinstance(await token.name, str), f"Cannot fetch name for token {token}"
    assert (
        10 ** await token.decimals == await token.scale
    ), f"Incorrect scale fetched for token {token}"
    assert await async_result(token.total_supply(block)) / await async_result(
        token.scale
    ) == await async_result(
        token.total_supply_readable(block)
    ), f"Incorrect total supply readable for token {token}"
    assert await async_result(token.price()), f"Cannot fetch price for token {token}"


@pytest.mark.parametrize("token,block", TOKENS_BY_BLOCK)
@pytest.mark.asyncio_cooperative
async def test_erc20_at_block(token: str | ERC20, block: int) -> None:
    """
    Test the :class:`~y.classes.common.ERC20` class at specific blocks.

    This test checks the total supply and price of the :class:`~y.classes.common.ERC20` token at specific blocks asynchronously,
    including interactions with the :class:`~y.contracts.Contract` class to fetch the contract for the token.

    Args:
        token: The address of the token to test.
        block: The block number to test at.

    Raises:
        AssertionError: If any of the assertions fail.
        NoProxyImplementation: If the token is a problematic proxy.

    Note:
        This test will be skipped for the old sUSD token with the address
        `0x57Ab1E02fEE23774580C119740129eAC7081e9D3` after its migration block.
        It will also be skipped for proxy contracts with implementation not set.

    See Also:
        - :class:`~y.classes.common.ERC20`
        - :class:`~y.contracts.Contract`
        - :mod:`dank_mids` for asynchronous operations
    """
    token = ERC20(token, asynchronous=True)

    if token.address == OLD_SUSD and block >= 13222927:
        pytest.skip("Not applicable to the old sUSD after migration block.")

    if token.address == OLD_SUSD and block == 5_761_012:
        assert await Call(token.address, "target()(address)", block_id=block) == ZERO_ADDRESS
        return

    # NOTE Some proxy tokens would fail tests in early days because no implementation is specified.
    try:
        if await Call(token.address, "implementation()(address)", block_id=block) == ZERO_ADDRESS:
            pytest.skip(f"Not applicable to proxy contracts with implementation not set.")
    except Exception as e:
        if not call_reverted(e):
            raise

    # NOTE We've validated token is not problematic proxy, proceed with test.
    try:
        # NOTE also tests ERC20._decimals
        assert await async_result(token.total_supply(block)) / await async_result(
            token._scale(block)
        ) == await async_result(
            token.total_supply_readable(block)
        ), f"Incorrect total supply readable for token {token}"
    except NoProxyImplementation:
        pass

    unavailable = {
        ("0x6b175474e89094c44da98b954eedeac495271d0f", 8_938_158),
        ("0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 4_729_568),
        ("0x2260fac5e5542a773aa44fbcfedf7c193bc2c599", 6_776_284),
        ("0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2", 4_630_855),
        ("0xdac17f958d2ee523a2206206994597c13d831ec7", 4_644_748),
        ("0x6c3ea9036406852006290770bedfcabA0e23a0e8".lower(), 15_931_958),
    }
    if (token.address.lower(), block) in unavailable:
        assert await async_result(token.price(block, return_None_on_failure=True)) is None
    else:
        assert await async_result(token.price(block)), f"Cannot fetch price for token {token}"
