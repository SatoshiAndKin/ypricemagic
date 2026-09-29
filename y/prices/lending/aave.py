import logging
from abc import abstractmethod
from collections.abc import Awaitable
from decimal import Decimal
from typing import Any, Union, cast

import a_sync
from a_sync import cgather, igather
from a_sync.a_sync import HiddenMethodDescriptor
from brownie import chain
from multicall import Call
from typing_extensions import Self
from web3.exceptions import ContractLogicError

from y import ENVIRONMENT_VARIABLES as ENVS
from y import convert
from y._decorators import stuck_coro_debugger
from y.classes.common import ERC20, ContractBase
from y.contracts import Contract, has_methods
from y.datatypes import Address, AddressOrContract, AnyAddressType, Block, PriceResult
from y.networks import Network
from y.prices._candidates import derive_price, gather_owned
from y.utils.logging import get_price_logger
from y.utils.raw_calls import raw_call

logger = logging.getLogger(__name__)


v1_pools = dict[int, tuple[str, ...]](
    {
        Network.Mainnet: ("0x398eC7346DcD622eDc5ae82352F02bE94C62d119",),
    }
).get(chain.id, ())

v2_pools = dict[int, tuple[str, ...]](
    {
        Network.Mainnet: (
            "0x7d2768dE32b0b80b7a3454c06BdAc94A69DDc7A9",  # aave
            "0x7937D4799803FbBe595ed57278Bc4cA21f3bFfCB",  # aave amm
            "0xcE744a9BAf573167B2CF138114BA32ed7De274Fa",  # umee
        ),
        Network.Polygon: ("0x8dFf5E27EA6b7AC08EbFdf9eB090F32ee9a30fcf",),  # aave
        Network.Avalanche: ("0x70BbE4A294878a14CB3CDD9315f5EB490e346163",),  # blizz
    }
).get(chain.id, ())

v3_pools = dict[int, tuple[str, ...]](
    {
        Network.Mainnet: ("0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2",),  # aave v3
        Network.Optimism: ("0x794a61358D6845594F94dc1DB02A252b5b4814aD",),  # aave v3
        Network.Arbitrum: ("0x794a61358D6845594F94dc1DB02A252b5b4814aD",),  # aave v3
        Network.Harmony: ("0x794a61358D6845594F94dc1DB02A252b5b4814aD",),  # aave v3
        Network.Arbitrum: ("0x794a61358D6845594F94dc1DB02A252b5b4814aD",),  # aave v3
        Network.Fantom: ("0x794a61358D6845594F94dc1DB02A252b5b4814aD",),  # aave v3
        Network.Avalanche: ("0x794a61358D6845594F94dc1DB02A252b5b4814aD",),  # aave v3
        Network.Polygon: ("0x794a61358D6845594F94dc1DB02A252b5b4814aD",),  # aave v3
    }
).get(chain.id, ())


class AaveMarketBase(ContractBase):
    """
    Base class for Aave markets.

    This class provides common functionality for Aave markets, including methods
    to check if a token is an aToken from the market and to retrieve reserve data.

    See Also:
        - :class:`AaveMarketV1`
        - :class:`AaveMarketV2`
        - :class:`AaveMarketV3`
    """

    def __contains__(self, token: object) -> bool:
        """
        Check if `token` is an aToken from this market.

        This method is intended for synchronous use. If `self.asynchronous` is not `False`,
        a `RuntimeError` will be raised.

        Args:
            token: The item to check.

        Returns:
            True if the token is an aToken from the market, False otherwise.

        Raises:
            RuntimeError: If `self.asynchronous` is not `False`.

        Example:
            >>> market = AaveMarketV1("0xAddress")
            >>> token = "0xTokenAddress"
            >>> token in market
            True
        """
        if self.asynchronous:
            cls = self.__class__.__name__
            raise RuntimeError(
                f"'self.asynchronous' must be False to use {cls}.__contains__.\nYou may wish to use {cls}.is_atoken instead."
            )
        address = convert.to_address(cast(AnyAddressType, token))
        return any(atoken == address for atoken in self.__atokens__(sync=True))

    async def contains(self, token: object) -> bool:
        """
        Check if `token` is an aToken from this market.

        This method is intended for asynchronous use.

        Args:
            token: The item to check.

        Returns:
            True if the token is an aToken from the market, False otherwise.

        Example:
            >>> market = AaveMarketV1("0xAddress", asynchronous=True)
            >>> token = "0xTokenAddress"
            >>> await market.contains(token)
            True
        """
        address = await convert.to_address_async(cast(AnyAddressType, token))
        contains = any(atoken == address for atoken in await self.__atokens__)
        logger.debug("%s contains %s: %s", self, token, contains)
        return contains

    async def get_reserves(self) -> list[Address]:
        return cast(list[Address], await Call(self.address, [self._get_reserves_method]))

    async def get_reserve_data(self, reserve: AnyAddressType) -> tuple[Any, ...]:
        return await self.contract.getReserveData.coroutine(reserve)

    @property
    @abstractmethod
    def atokens(self) -> Awaitable[list[ERC20]]:
        """
        Get the aTokens of the market.

        This is an abstract property and must be implemented by subclasses.

        Returns:
            A list of aTokens as :class:`~ERC20` objects.

        Example:
            >>> market = AaveMarketV1("0xAddress", asynchronous=True)
            >>> atokens = await market.atokens
            >>> print(atokens)
            [<ERC20 '0xTokenAddress1'>, <ERC20 '0xTokenAddress2'>]
        """

    __atokens__: HiddenMethodDescriptor["AaveMarketBase", list[ERC20]]

    @abstractmethod
    async def underlying(self, atoken_address: AddressOrContract) -> ERC20:
        """
        Get the underlying asset of the given aToken address.

        This is an abstract method and must be implemented by subclasses.

        Args:
            atoken_address: The address of the aToken.

        Returns:
            The underlying asset.

        Example:
            >>> market = AaveMarketV1("0xAddress", asynchronous=True)
            >>> underlying_asset = await market.underlying("0xATokenAddress")
            >>> print(underlying_asset)
            <ERC20 '0xUnderlyingAssetAddress'>
        """

    @property
    @abstractmethod
    def _get_reserves_method(self) -> str:
        """
        The method that must be called to get the reserves list.

        This is an abstract property and must be implemented by subclasses.

        Example:
            >>> market = AaveMarketV1("0xAddress")
            >>> print(market._get_reserves_method)
            'getReserves()(address[])'
        """


class AaveMarketV1(AaveMarketBase):
    @a_sync.aka.cached_property
    @stuck_coro_debugger
    async def atokens(self) -> list[ERC20]:
        reserves_data = await gather_owned(
            cast(Any, self.get_reserve_data)(reserve, sync=False)
            for reserve in await self.get_reserves(sync=False)
        )
        atokens = [
            ERC20(reserve_data["aTokenAddress"], asynchronous=self.asynchronous)
            for reserve_data in reserves_data
        ]
        logger.info("loaded %s v1 atokens for %s", len(atokens), repr(self))
        return atokens

    @a_sync.a_sync(ram_cache_maxsize=256)
    async def underlying(self, atoken_address: AddressOrContract) -> ERC20:
        underlying = await raw_call(
            atoken_address, "underlyingAssetAddress()", output="address", sync=False
        )
        return ERC20(underlying)

    _get_reserves_method = "getReserves()(address[])"


_V2_RESERVE_DATA_METHOD = "getReserveData(address)((uint256,uint128,uint128,uint128,uint128,uint128,uint40,address,address,address,address,uint8))"


class AaveMarketV2(AaveMarketBase):
    @a_sync.aka.cached_property
    @stuck_coro_debugger
    async def atokens(self) -> list[ERC20]:
        reserves_data = await gather_owned(
            cast(Any, self.get_reserve_data)(reserve, sync=False)
            for reserve in await self.get_reserves(sync=False)
        )
        try:
            atokens = [
                ERC20(reserve_data[7], asynchronous=self.asynchronous)
                for reserve_data in reserves_data
            ]
            logger.info("loaded %s v2 atokens for %s", len(atokens), repr(self))
            return atokens
        except TypeError as e:  # TODO figure out what to do about non verified aave markets
            logger.exception(e)
            logger.warning("failed to load tokens for %s", self)
            return []

    async def get_reserve_data(self, reserve: AnyAddressType) -> tuple[Any, ...]:
        return cast(
            tuple[Any, ...], await Call(self.address, [_V2_RESERVE_DATA_METHOD, str(reserve)])
        )

    @a_sync.a_sync(ram_cache_maxsize=256)
    async def underlying(self, atoken_address: AddressOrContract) -> ERC20:
        underlying = await raw_call(
            atoken_address, "UNDERLYING_ASSET_ADDRESS()", output="address", sync=False
        )
        logger.debug("underlying: %s", underlying)
        return ERC20(underlying, asynchronous=self.asynchronous)

    _get_reserves_method = "getReservesList()(address[])"


class AaveMarketV3(AaveMarketBase):
    @a_sync.aka.cached_property
    @stuck_coro_debugger
    async def atokens(self) -> list[ERC20]:
        reserves_data = await gather_owned(
            cast(Any, self.get_reserve_data)(reserve, sync=False)
            for reserve in await self.get_reserves(sync=False)
        )
        try:
            atokens = [
                ERC20(reserve_data[8], asynchronous=self.asynchronous)
                for reserve_data in reserves_data
            ]
            logger.info("loaded %s v3 atokens for %s", len(atokens), repr(self))
            return atokens
        except TypeError as e:  # TODO figure out what to do about non verified aave markets
            logger.exception(e)
            logger.warning("failed to load tokens for %s", self)
            return []

    @a_sync.a_sync(ram_cache_maxsize=256)
    async def underlying(self, atoken_address: AddressOrContract) -> ERC20:
        underlying = await raw_call(
            atoken_address, "UNDERLYING_ASSET_ADDRESS()", output="address", sync=False
        )
        logger.debug("underlying: %s", underlying)
        return ERC20(underlying, asynchronous=self.asynchronous)

    _get_reserves_method = "getReservesList()(address[])"


AaveMarket = Union[AaveMarketV1, AaveMarketV2, AaveMarketV3]


class AaveRegistry(a_sync.ASyncGenericSingleton):
    def __init__(self, *, asynchronous: bool = False) -> None:
        self.asynchronous = asynchronous
        super().__init__()

    @a_sync.aka.cached_property
    async def pools(self) -> list[AaveMarket]:
        groups = await gather_owned(
            cast(Awaitable[list[AaveMarket]], group)
            for group in (self.__pools_v1__, self.__pools_v2__, self.__pools_v3__)
        )
        return [pool for group in groups for pool in group]

    __pools__: HiddenMethodDescriptor["AaveRegistry", list[AaveMarket]]

    @a_sync.aka.cached_property
    async def pools_v1(self) -> list[AaveMarketV1]:
        pools = [AaveMarketV1(pool, asynchronous=self.asynchronous) for pool in v1_pools]
        logger.debug("AaveRegistry v1 pools %s", pools)
        return pools

    __pools_v1__: HiddenMethodDescriptor["AaveRegistry", list[AaveMarketV1]]

    @a_sync.aka.cached_property
    async def pools_v2(self) -> list[AaveMarketV2]:
        pools = [AaveMarketV2(pool, asynchronous=self.asynchronous) for pool in v2_pools]
        logger.debug("AaveRegistry v2 pools %s", pools)
        return pools

    __pools_v2__: HiddenMethodDescriptor["AaveRegistry", list[AaveMarketV2]]

    @a_sync.aka.cached_property
    async def pools_v3(self) -> list[AaveMarketV3]:
        pools = [AaveMarketV3(pool, asynchronous=self.asynchronous) for pool in v3_pools]
        logger.debug("AaveRegistry v3 pools %s", pools)
        return pools

    __pools_v3__: HiddenMethodDescriptor["AaveRegistry", list[AaveMarketV3]]

    async def pool_for_atoken(
        self, atoken_address: AnyAddressType
    ) -> AaveMarketV1 | AaveMarketV2 | AaveMarketV3 | None:
        pools = await self.__pools__
        for pool in pools:
            if await pool.contains(atoken_address, sync=False):
                return pool

    def __contains__(self, __o: object) -> bool:
        if self.asynchronous:
            raise RuntimeError(
                f"'self.asynchronous' must be False to use AaveRegistry.__contains__.\nYou may wish to use AaveRegistry.is_atoken instead."
            )
        return any(__o in pool for pool in self.__pools__(sync=True))

    @a_sync.a_sync(cache_type="memory", ram_cache_maxsize=ENVS.CONTRACT_CACHE_MAXSIZE)
    async def is_atoken(self, atoken_address: AnyAddressType) -> bool:
        logger = get_price_logger(atoken_address, block=None, extra="aave")
        is_atoken = any(
            await igather(
                pool.contains(atoken_address, sync=False) for pool in await self.__pools__
            )
        )
        logger.debug("is_atoken: %s", is_atoken)
        return is_atoken

    @stuck_coro_debugger
    async def is_wrapped_atoken_v2(self, atoken_address: AnyAddressType) -> bool:
        # NOTE: Not sure if this wrapped version is actually related to aave but this works for pricing purposes.
        return bool(
            await cast(Any, has_methods)(
                atoken_address,
                ("ATOKEN()(address)", "STATIC_ATOKEN_LM_REVISION()(uint256)"),
                sync=False,
            )
        )

    @stuck_coro_debugger
    async def is_wrapped_atoken_v3(self, atoken_address: AnyAddressType) -> bool:
        # NOTE: Not sure if this wrapped version is actually related to aave but this works for pricing purposes.
        return bool(
            await cast(Any, has_methods)(
                atoken_address,
                ("ATOKEN()(address)", "AAVE_POOL()(address)", "UNDERLYING()(address)"),
                sync=False,
            )
        )

    @a_sync.a_sync(cache_type="memory", ram_cache_maxsize=ENVS.CONTRACT_CACHE_MAXSIZE)
    @stuck_coro_debugger
    async def underlying(self, atoken_address: AddressOrContract) -> ERC20:
        pool = await self.pool_for_atoken(atoken_address, sync=False)
        if pool is None:
            raise ValueError(f"No Aave market for {str(atoken_address)}")
        return await pool.underlying(atoken_address, sync=False)

    @stuck_coro_debugger
    async def get_price(
        self,
        atoken_address: AddressOrContract,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
    ) -> PriceResult | None:
        underlying: ERC20 = await self.underlying(atoken_address, sync=False)
        child = await underlying.price(
            block, skip_cache=skip_cache, return_None_on_failure=True, sync=False
        )
        if child is None:
            return None
        return derive_price(
            atoken_address,
            float(child),
            f"Aave {str(atoken_address)} underlying {underlying.address}",
            child,
        )

    @stuck_coro_debugger
    async def get_price_wrapped_v2(
        self,
        atoken_address: AddressOrContract,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
    ) -> PriceResult | None:
        return await self._get_price_wrapped(
            atoken_address, "staticToDynamicAmount", block=block, skip_cache=skip_cache
        )

    @stuck_coro_debugger
    async def get_price_wrapped_v3(
        self,
        atoken_address: AddressOrContract,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
    ) -> PriceResult | None:
        return await self._get_price_wrapped(
            atoken_address, "convertToAssets", block=block, skip_cache=skip_cache
        )

    @stuck_coro_debugger
    async def _get_price_wrapped(
        self,
        atoken_address: AddressOrContract,
        method: str,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
    ) -> PriceResult | None:
        address = await convert.to_address_async(atoken_address)
        scale = await ERC20._get_scale_for(address)
        try:
            underlying, price_per_share = await gather_owned(
                [
                    # NOTE: We can probably cache this without breaking anything
                    Call(address, "ATOKEN()(address)", block_id=block).coroutine(),
                    Call(
                        address, [f"{method}(uint256)(uint256)", scale], block_id=block
                    ).coroutine(),
                ]
            )
        except ContractLogicError:
            return None
        price_per_share /= Decimal(scale)
        child = await ERC20(underlying, asynchronous=True).price(
            block, skip_cache=skip_cache, sync=False
        )
        if child is None:
            return None
        return derive_price(
            atoken_address,
            price_per_share * Decimal(float(child)),
            f"Aave wrapped {str(atoken_address)} via {method}",
            child,
        )


aave: AaveRegistry = AaveRegistry(asynchronous=True)
