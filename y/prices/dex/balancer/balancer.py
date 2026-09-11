import logging
from typing import Final, final

import a_sync
import dank_mids
from a_sync.a_sync.property import HiddenMethodDescriptor
from typing_extensions import Self

from y import ENVIRONMENT_VARIABLES as ENVS
from y import exceptions
from y._decorators import stuck_coro_debugger
from y.datatypes import AnyAddressType, Block, Pool, PriceResult, UsdPrice
from y.prices._candidates import derive_price, gather_owned, select_price, valid_price
from y.prices.dex.balancer._abc import BalancerABC
from y.prices.dex.balancer.v1 import BalancerV1
from y.prices.dex.balancer.v2 import BalancerV2
from y.utils.cache import optional_async_diskcache

logger: Final = logging.getLogger(__name__)


@final
class BalancerMultiplexer(a_sync.ASyncGenericBase):
    """A multiplexer for interacting with different versions of Balancer pools.

    This class provides methods to determine if a token is a Balancer pool,
    retrieve pool prices, and get token prices across different Balancer versions.

    Examples:
        Initialize the multiplexer:

        >>> multiplexer = BalancerMultiplexer(asynchronous=True)

        Check if a token is a Balancer pool:

        >>> is_pool = await multiplexer.is_balancer_pool(token_address)

        Get the price of a token:

        >>> price = await multiplexer.get_price(token_address, block=12345678)

    See Also:
        - :class:`BalancerV1`
        - :class:`BalancerV2`
    """

    def __init__(self, *, asynchronous: bool = False) -> None:
        """
        Initialize the BalancerMultiplexer.

        Args:
            asynchronous: Whether to operate in asynchronous mode.
        """
        super().__init__()
        self.asynchronous: Final = asynchronous

    @a_sync.aka.property
    async def versions(self) -> list[BalancerV1 | BalancerV2]:
        """
        Get the available Balancer versions.

        Returns:
            A list of available Balancer versions.

        Examples:
            >>> versions = await multiplexer.versions
        """
        return [v for v in await gather_owned([self.__v1__, self.__v2__]) if v]

    __versions__: HiddenMethodDescriptor[Self, list[BalancerV1 | BalancerV2]]

    @a_sync.aka.cached_property
    async def v1(self) -> BalancerV1 | None:
        """
        Get the Balancer V1 instance.

        Returns:
            An instance of BalancerV1 if available, otherwise None.

        Examples:
            >>> v1 = await multiplexer.v1
        """
        try:
            return BalancerV1(asynchronous=self.asynchronous)
        except ImportError:
            return None

    __v1__: HiddenMethodDescriptor[Self, BalancerV1 | None]

    @a_sync.aka.cached_property
    async def v2(self) -> BalancerV2 | None:
        """
        Get the Balancer V2 instance.

        Returns:
            An instance of BalancerV2 if available, otherwise None.

        Examples:
            >>> v2 = await multiplexer.v2
        """
        try:
            return BalancerV2(asynchronous=self.asynchronous)
        except ImportError:
            return None

    __v2__: HiddenMethodDescriptor[Self, BalancerV2 | None]

    @stuck_coro_debugger
    @optional_async_diskcache
    async def is_balancer_pool(self, token_address: AnyAddressType) -> bool:
        """
        Check if a given token address is a Balancer pool.

        Args:
            token_address: The address of the token to check.

        Returns:
            True if the token is a Balancer pool, otherwise False.

        Examples:
            >>> is_pool = await multiplexer.is_balancer_pool(token_address)
        """
        try:
            await self.get_version(token_address)
            return True
        except exceptions.TokenError:
            return False

    @stuck_coro_debugger
    async def get_pool_price(
        self,
        token_address: AnyAddressType,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
        ignore_pools: tuple[Pool, ...] = (),
    ) -> UsdPrice | None:
        """
        Get the price of a Balancer pool.

        Args:
            token_address: The address of the pool token.
            block: The block number to query the price at.
            skip_cache: Whether to skip the cache.

        Returns:
            The price of the pool in USD, or None if not available.

        Examples:
            >>> price = await multiplexer.get_pool_price(token_address, block=12345678)
        """
        balancer: BalancerABC = await self.get_version(token_address)
        logger.debug("pool %s is from %s", token_address, balancer)
        price = await balancer.get_pool_price(
            token_address, block, skip_cache=skip_cache, ignore_pools=ignore_pools, sync=False
        )
        return None if price is None else UsdPrice(price)

    @stuck_coro_debugger
    async def get_price(
        self,
        token_address: AnyAddressType,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
        ignore_pools: tuple[Pool, ...] = (),
    ) -> PriceResult | None:
        """
        Get the price of a token using Balancer pools.

        Args:
            token_address: The address of the token.
            block: The block number to query the price at.
            skip_cache: Whether to skip the cache.

        Returns:
            The price of the token in USD, or None if not available.

        Examples:
            >>> price = await multiplexer.get_price(token_address, block=12345678)
        """
        if block is None:
            block = await dank_mids.eth.block_number
        if await self.is_balancer_pool(token_address, sync=False):
            price = await self.get_pool_price(
                token_address,
                block=block,
                skip_cache=skip_cache,
                ignore_pools=ignore_pools,
                sync=False,
            )
            if price is not None and valid_price(price):
                return derive_price(token_address, price, f"Balancer pool {token_address}")

        versions = await self.__versions__
        price, source = await select_price(
            (
                f"Balancer {type(version).__name__}",
                version.get_token_price(
                    token_address,
                    block,
                    skip_cache=skip_cache,
                    ignore_pools=ignore_pools,
                    sync=False,
                ),
            )
            for version in versions
        )
        if price is not None:
            return (
                price
                if isinstance(price, PriceResult)
                else derive_price(token_address, float(price), source or "Balancer")
            )

    # cached forever because not many items
    @a_sync.a_sync(
        cache_type="memory", ram_cache_ttl=None, ram_cache_maxsize=ENVS.DEFAULT_CACHE_MAXSIZE
    )
    async def get_version(self, token_address: AnyAddressType) -> BalancerABC:
        """
        Determine the Balancer version for a given token address.

        Args:
            token_address: The address of the token.

        Returns:
            The Balancer version instance.

        Raises:
            exceptions.TokenError: If the token is not a Balancer pool.

        Examples:
            >>> version = await multiplexer.get_version(token_address)
        """
        for v in await self.__versions__:
            if await v.is_pool(token_address, sync=False):
                return v
        raise exceptions.TokenError(token_address, "Balancer pool")


balancer_multiplexer: Final = BalancerMultiplexer(asynchronous=True)
