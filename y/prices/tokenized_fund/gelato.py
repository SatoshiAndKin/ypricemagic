from typing import cast
from y.datatypes import PriceResult
import logging
from decimal import Decimal

import a_sync
from a_sync import cgather
from multicall import Call

import y.prices.magic
from y import ENVIRONMENT_VARIABLES as ENVS
from y import convert
from y._decorators import stuck_coro_debugger
from y.classes.common import ERC20
from y.datatypes import AnyAddressType, Block, UsdPrice
from y.utils.cache import optional_async_diskcache
from y.prices._candidates import gather_owned
from y.prices._rpc import unavailable
from y.utils.raw_calls import raw_call

logger = logging.getLogger(__name__)


@a_sync.a_sync(
    default="sync",
    cache_type="memory",
    ram_cache_ttl=5 * 60,
    ram_cache_maxsize=ENVS.DEFAULT_CACHE_MAXSIZE,
)
@optional_async_diskcache
async def is_gelato_pool(token_address: AnyAddressType) -> bool:
    """
    Check if a given token address is a Gelato pool.

    Args:
        token_address: The address of the token to check.

    Returns:
        True if the token is a Gelato pool, False otherwise.

    Example:
        >>> is_gelato_pool("0x1234567890abcdef1234567890abcdef12345678")
        True

    See Also:
        - :func:`y.contracts.has_methods`
    """
    return await _is_gelato_pool(token_address, None)


@stuck_coro_debugger
async def _is_gelato_pool(token_address: AnyAddressType, block: Block | None) -> bool:
    token_address = await convert.to_address_async(token_address)
    # Upgraded GUNI pools expose aggregate underlying balances; old pools also
    # exposed separate fee balances. Neither detection nor valuation needs an ABI.
    try:
        balances = await Call(
            token_address, "getUnderlyingBalances()(uint256,uint256)", block_id=block
        )
    except Exception as exc:
        if not unavailable(exc):
            raise
    else:
        if balances is not None:
            return True
    try:
        return all(
            value is not None
            for value in await gather_owned(
                Call(token_address, signature, block_id=block).coroutine()
                for signature in ("gelatoBalance0()(uint)", "gelatoBalance1()(uint)")
            )
        )
    except Exception as exc:
        if not unavailable(exc):
            raise
        return False


@a_sync.a_sync(default="sync")
async def get_price(
    token: AnyAddressType,
    block: Block | None = None,
    skip_cache: bool = ENVS.SKIP_CACHE,
) -> UsdPrice | None:
    """
    Calculate the price of a Gelato pool token in USD.

    This function calculates the price of a Gelato pool token by retrieving the balances,
    scales, and prices of the pool's underlying assets (token0 and token1), calculating
    their total value, and dividing by the total supply of the pool token.

    Args:
        token: The address of the token to price.
        block: The block number at which to get the price. Defaults to None.
        skip_cache: Whether to skip the cache. Defaults to ENVS.SKIP_CACHE.

    Example:
        >>> get_price("0x1234567890abcdef1234567890abcdef12345678")
        123.45

    See Also:
        - :func:`y.prices.magic.get_price`
        - :class:`y.classes.common.ERC20`
    """
    return await _get_price(token, block, skip_cache=skip_cache)


@stuck_coro_debugger
async def _get_price(
    token: AnyAddressType, block: Block | None, *, skip_cache: bool
) -> UsdPrice | None:
    address = await convert.to_address_async(token)

    token0, token1 = await cgather(
        raw_call(address, "token0()", block=block, output="address", sync=False),
        raw_call(address, "token1()", block=block, output="address", sync=False),
    )

    balances = await Call(address, "getUnderlyingBalances()(uint256,uint256)", block_id=block)
    if balances is None:
        return None
    balance0, balance1 = balances
    (
        scale0,
        scale1,
        price0,
        price1,
        total_supply,
    ) = await cgather(
        *map(ERC20._get_scale_for, (token0, token1)),
        y.prices.magic.get_price(token0, block, skip_cache=skip_cache, sync=False),
        y.prices.magic.get_price(token1, block, skip_cache=skip_cache, sync=False),
        ERC20(address, asynchronous=True).total_supply_readable(block, sync=False),
    )

    if not total_supply or price0 is None or price1 is None:
        return None
    scale0, scale1 = cast(int, scale0), cast(int, scale1)
    price0, price1 = cast(PriceResult, price0), cast(PriceResult, price1)
    total_value = Decimal(balance0) / scale0 * Decimal(str(float(price0))) + Decimal(
        balance1
    ) / scale1 * Decimal(str(float(price1)))
    return UsdPrice(total_value / Decimal(str(total_supply)))
