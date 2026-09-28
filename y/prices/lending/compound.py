import logging
from typing import Any, Optional, cast

import a_sync
from a_sync import cgather
from a_sync.a_sync import HiddenMethodDescriptor
from brownie import ZERO_ADDRESS, chain
from brownie.exceptions import VirtualMachineError
from multicall import Call
from typing_extensions import Self
from web3.exceptions import ContractLogicError

from y import ENVIRONMENT_VARIABLES as ENVS
from y._decorators import stuck_coro_debugger
from y.classes.common import ERC20, ContractBase
from y.constants import EEE_ADDRESS
from y.contracts import Contract, has_methods
from y.datatypes import AddressOrContract, AnyAddressType, Block, PriceResult
from y.exceptions import ContractNotVerified, call_reverted
from y.networks import Network
from y.prices._candidates import derive_price
from y.utils.logging import _gh_issue_request
from y.utils.raw_calls import raw_call

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.INFO)

TROLLERS = {
    Network.Mainnet: {
        "comp": "0x3d9819210A31b4961b30EF54bE2aeD79B9c9Cd3B",
        "cream": "0x3d5BC3c8d13dcB8bF317092d84783c2697AE9258",
        "ironbank": "0xAB1c342C7bf5Ec5F02ADEA1c2270670bCa144CbB",
        "inverse": "0x4dCf7407AE5C07f8681e1659f626E114A7667339",
        "unfederalreserve": "0x3105D328c66d8d55092358cF595d54608178E9B5",
        "flux": "0x95Af143a021DF745bc78e845b54591C53a8B3A51",
        "venus": "0x687a01ecF6d3907658f7A7c714749fAC32336D1B",
    },
    Network.BinanceSmartChain: {
        "venus": "0xfD36E2c2a6789Db23113685031d7F16329158384",
    },
    Network.Polygon: {
        "easyfi": "0xcb3fA413B23b12E402Cfcd8FA120f983FB70d8E8",
        "apple": "0x46220a07F071D1a821D68fA7C769BCcdA3C65430",
        "chumhum": "0x1D43f6DA91e9EF6614dCe95bCef43E4d7b2bcFB5",
        "cream": "0x20CA53E2395FA571798623F1cFBD11Fe2C114c24",
    },
    Network.Fantom: {
        "cream": "0x4250A6D3BD57455d7C6821eECb6206F507576cD2",
        "scream": "0x260E596DAbE3AFc463e75B6CC05d8c46aCAcFB09",
        "ola": "0xD65eB596cFb5DE402678a12df651E0e588Dc3A81",
    },
    Network.Avalanche: {
        "vee": "0xA67DFeD73025b0d61F2515c531dd8D25D4Cfd0Db",
        "vee2": "0x43AAd7d8Bc661dfA70120865239529ED92Faa054",
        "vee3": "0xeEf69Cab52480D2BD2D4A3f3E8F5CcfF2923f6eF",
        "cream": "0x2eE80614Ccbc5e28654324a66A396458Fa5cD7Cc",
    },
    Network.Arbitrum: {
        "cream": "0xbadaC56c9aca307079e8B8FC699987AAc89813ee",
        "neku": "0xD5B649c7d27C13a2b80425daEe8Cb6023015Dc6B",
        "channels": "0x3C13b172bf8BE5b873EB38553feC50F78c826284",
        "hund": "0x0F390559F258eB8591C8e31Cf0905E97cf36ACE2",
    },
    Network.Optimism: {
        "ironbank": "0xE0B57FEEd45e7D908f2d0DaCd26F113Cf26715BF",
    },
}.get(chain.id, {})


def _oracle_unavailable(exc: Exception) -> bool:
    """Recognize only the protocol's documented unavailable-feed reverts."""
    if not isinstance(exc, (VirtualMachineError, ContractLogicError)):
        return False
    # dank_mids may append a Request to args; Brownie may append source text.
    # Match the native revert reason rather than the formatted exception tuple.
    reason = getattr(exc, "revert_msg", None) or (exc.args[0] if exc.args else str(exc))
    if not isinstance(reason, str):
        return False
    reason = reason.removeprefix("execution reverted: ").removeprefix("revert: ")
    return reason in {
        "grace period not over",
        "Chainlink feeds are not being updated",
        "Feed not found",
        "token config not found",
        "no price",
        "invalid resilient oracle price",
    }


class CToken(ERC20):
    def __init__(
        self,
        address: AnyAddressType,
        comptroller: Optional["Comptroller"] = None,
        *,
        asynchronous: bool = False,
    ) -> None:
        """
        Initialize a CToken instance.

        Args:
            address: The address of the CToken.
            comptroller: An optional instance of :class:`~Comptroller` associated with this CToken.
            asynchronous: Whether to use asynchronous operations.

        Examples:
            >>> ctoken = CToken("0x1234567890abcdef1234567890abcdef12345678")
            >>> ctoken_with_comptroller = CToken("0x1234567890abcdef1234567890abcdef12345678", comptroller=my_comptroller)
        """
        self.troller = comptroller
        super().__init__(address, asynchronous=asynchronous)
        self.exchange_rate_current = Call(self.address, "exchangeRateCurrent()(uint)").coroutine

    @stuck_coro_debugger
    async def get_price(
        self, block: Block | None = None, skip_cache: bool = ENVS.SKIP_CACHE
    ) -> PriceResult | None:
        """
        Get the price of the CToken in USD.

        Args:
            block: The block number to query. Defaults to the latest block.
            skip_cache: Whether to skip using the cache while fetching price data.

        Examples:
            >>> price = await ctoken.get_price()
            >>> price_at_block = await ctoken.get_price(block=12345678)
        """
        try:
            underlying_per_ctoken = await self.underlying_per_ctoken(block=block, asynchronous=True)
        except Exception as exc:
            if not call_reverted(exc):
                raise
            return None
        if not underlying_per_ctoken:
            return None
        underlying_price = await self.get_underlying_price(
            block=block, skip_cache=skip_cache, asynchronous=True
        )
        if underlying_price:
            return derive_price(
                self.address,
                float(underlying_per_ctoken) * float(underlying_price),
                f"Compound {self.address} historical underlying oracle",
                underlying_price,
            )

        underlying = await self.__underlying__
        child_price = await underlying.price(
            block=block, skip_cache=skip_cache, return_None_on_failure=True, asynchronous=True
        )
        if child_price is None:
            return None
        return derive_price(
            self.address,
            float(underlying_per_ctoken) * float(child_price),
            f"Compound {self.address} underlying",
            child_price,
        )

    @a_sync.aka.cached_property
    async def underlying(self) -> ERC20:
        """
        Get the underlying ERC20 token for this CToken.

        Returns:
            An instance of :class:`~ERC20` representing the underlying token.

        Examples:
            >>> underlying_token = await ctoken.underlying
        """
        # sourcery skip: use-or-for-fallback
        underlying = await self.has_method(
            "underlying()(address)", return_response=True, sync=False
        )
        # this will run for gas coin markets like cETH, crETH
        if not underlying:
            underlying = EEE_ADDRESS
        return ERC20(underlying, asynchronous=self.asynchronous)

    __underlying__: HiddenMethodDescriptor[Self, ERC20]

    async def underlying_per_ctoken(self, block: Block | None = None) -> float:
        """
        Get the exchange rate of the CToken, adjusted for decimals.

        This method calculates the amount of underlying tokens per CToken by
        multiplying the exchange rate by a factor based on the difference in
        decimals between the CToken and its underlying token.

        Args:
            block: The block number to query. Defaults to the latest block.

        Examples:
            >>> amount = await ctoken.underlying_per_ctoken()
            >>> amount_at_block = await ctoken.underlying_per_ctoken(block=12345678)

        See Also:
            - :meth:`exchange_rate`
        """
        underlying: ERC20
        exchange_rate, decimals, underlying = await cgather(
            self.exchange_rate(block=block, sync=False),
            self.__decimals__,
            self.__underlying__,
        )
        return exchange_rate * 10 ** (decimals - await underlying.__decimals__)

    # yLazyLogger(logger)
    @stuck_coro_debugger
    async def exchange_rate(self, block: Block | None = None) -> float:
        """
        Get the current exchange rate of the CToken.

        Args:
            block: The block number to query. Defaults to the latest block.

        Examples:
            >>> rate = await ctoken.exchange_rate()
            >>> rate_at_block = await ctoken.exchange_rate(block=12345678)
        """
        try:
            exchange_rate = await self.exchange_rate_current(block_id=block)
        except Exception as e:
            if not call_reverted(e):
                raise
            exchange_rate = None

        if exchange_rate is None:
            # NOTE: Sometimes this works, not sure why
            contract = await Contract.coroutine(self.address)
            exchange_rate = await contract.exchangeRateCurrent.coroutine(block_identifier=block)

        return exchange_rate / 10**18

    @stuck_coro_debugger
    async def get_underlying_price(
        self, block: Block | None = None, skip_cache: bool = ENVS.SKIP_CACHE
    ) -> float | None:
        """
        Get the price of the underlying token in USD.

        Args:
            block: The block number to query. Defaults to the latest block.
            skip_cache: Whether to skip using the cache while fetching price data.

        Examples:
            >>> price = await ctoken.get_underlying_price()
            >>> price_at_block = await ctoken.get_underlying_price(block=12345678)
        """
        # A standalone CToken has no registry-injected comptroller. Resolve it
        # at the requested block; never attach historical metadata to the instance.
        troller = (
            self.troller.address
            if self.troller
            else await Call(self.address, "comptroller()(address)", block_id=block)
        )
        if not troller or troller == ZERO_ADDRESS:
            return None
        oracle = await Call(troller, "oracle()(address)", block_id=block)
        if not oracle or oracle == ZERO_ADDRESS:
            return None
        try:
            price = await Call(
                oracle, ["getUnderlyingPrice(address)(uint256)", self.address], block_id=block
            )
        except Exception as exc:
            if _oracle_unavailable(exc):
                return None
            # This immutable Inverse oracle delegates to configured Chainlink
            # proxies. A retired proxy with no aggregator reverts without a
            # reason. Verify that state instead of accepting arbitrary reverts.
            if (
                chain.id == Network.Mainnet
                and oracle.lower() == "0xe8929afd47064efd36a7fb51da3f8c5eb40c4cb4"
                and isinstance(exc, ContractLogicError)
                and exc.args
                and exc.args[0] == "execution reverted"
            ):
                feed = await Call(
                    oracle, ["feeds(address)(address,uint8)", self.address], block_id=block
                )
                if feed and feed[0] != ZERO_ADDRESS:
                    aggregator = await Call(feed[0], "aggregator()(address)", block_id=block)
                    if aggregator == ZERO_ADDRESS:
                        return None
            raise
        if not price:
            return None
        underlying = await self.__underlying__
        price /= 10 ** (36 - await underlying.__decimals__)
        # This verified legacy Cream oracle quotes all markets relative to ETH.
        # Later Cream and Compound oracles quote USD with the same decimal scale.
        if (
            chain.id == Network.Mainnet
            and oracle.lower() == "0x4b7dba23bea9d1a2d652373bcd1b78b0e9e0188a"
        ):
            eth_price = await cast(Any, ERC20(EEE_ADDRESS, asynchronous=True).price)(
                block=block, skip_cache=skip_cache, return_None_on_failure=True, asynchronous=True
            )
            if eth_price is None:
                return None
            price *= float(eth_price)
        return price


class Comptroller(ContractBase):
    def __init__(
        self,
        address: AnyAddressType | None = None,
        key: str | None = None,
        *,
        asynchronous: bool = False,
    ) -> None:
        """
        Initialize a Comptroller instance.

        You must provide either an address or a key. If both are provided, the key will be used to look up the address.

        Args:
            address: The address of the Comptroller.
            key: The key associated with the Comptroller in the TROLLERS dictionary.
            asynchronous: Whether to use asynchronous operations.

        Examples:
            >>> comptroller = Comptroller(address="0x1234567890abcdef1234567890abcdef12345678")
            >>> comptroller_with_key = Comptroller(key="comp")
        """
        assert address or key, "Must provide either an address or a key"
        assert not (address and key), "Must provide either an address or a key, not both"

        if key:
            address = TROLLERS[key]
        else:
            key = [key for key in TROLLERS if address == TROLLERS[key]][0]

        super().__init__(address, asynchronous=asynchronous)
        self.key = key

    def __repr__(self) -> str:
        return f"<Comptroller {self.key} '{self.address}'>"

    # yLazyLogger(logger)
    def __contains__(self, token_address: AnyAddressType) -> bool:
        """
        Check if a token address is contained within the Comptroller's markets.

        Args:
            token_address: The address of the token to check.

        Returns:
            True if the token address is in the Comptroller's markets, False otherwise.

        Examples:
            >>> "0x1234567890abcdef1234567890abcdef12345678" in comptroller
        """
        if self.asynchronous:
            raise RuntimeError("'self.asynchronous' must be False to use Comptroller.__contains__")
        return token_address in self.markets

    @a_sync.aka.cached_property
    async def markets(self) -> tuple[CToken]:
        """
        Get the markets associated with this Comptroller.

        Returns:
            A tuple of :class:`~CToken` instances representing the markets.

        Examples:
            >>> markets = await comptroller.markets
        """
        response = await self.has_method(
            "getAllMarkets()(address[])", return_response=True, sync=False
        )
        if not response:
            logger.warning("had trouble loading markets for %s", self)
            response = set()
        markets = tuple(
            CToken(market, comptroller=self, asynchronous=self.asynchronous) for market in response
        )
        logger.info("loaded %s markets for %s", len(markets), self)
        return markets

    __markets__ = HiddenMethodDescriptor[Self, tuple[CToken]]

    async def oracle(self, block: Block | None = None) -> Contract:
        """
        Get the oracle contract associated with this Comptroller.

        Args:
            block: The block number to query. Defaults to the latest block.

        Examples:
            >>> oracle = await comptroller.oracle()
            >>> oracle_at_block = await comptroller.oracle(block=12345678)
        """
        contract = await Contract.coroutine(self.address)
        try:
            oracle = await contract.oracle.coroutine(block_identifier=block)
        except Exception as e:
            # TODO debug why this occurs and refactor. only found on arbitrum cream
            if not call_reverted(e):
                raise
            oracle = contract.oracle(block_identifier=block)
        try:
            return await Contract.coroutine(oracle)
        except ContractNotVerified:
            raise ContractNotVerified(
                f"{self} oracle {oracle} at block {block} is not verified"
            ) from None


class Compound(a_sync.ASyncGenericSingleton):
    def __init__(self, *, asynchronous: bool = False) -> None:
        """
        Initialize a Compound instance.

        Args:
            asynchronous: Whether to use asynchronous operations.

        Examples:
            >>> compound = Compound()
            >>> compound_async = Compound(asynchronous=True)
        """
        super().__init__()
        self.asynchronous = asynchronous
        self.trollers = {
            protocol: Comptroller(troller, asynchronous=self.asynchronous)
            for protocol, troller in TROLLERS.items()
        }

    def __contains__(self, token_address: AddressOrContract) -> bool:
        """
        Check if a token address is a Compound market.

        Args:
            token_address: The address of the token to check.

        Returns:
            True if the token address is a Compound market, False otherwise.

        Examples:
            >>> "0x1234567890abcdef1234567890abcdef12345678" in compound
        """
        if self.asynchronous:
            raise RuntimeError(
                "'self.asynchronous' must be False and the event loop must not be running"
            )
        return self.is_compound_market(token_address)

    async def get_troller(self, token_address: AddressOrContract) -> Comptroller | None:
        """
        Get the Comptroller associated with a token address.

        Args:
            token_address: The address of the token.

        Returns:
            An instance of :class:`~Comptroller` if found, None otherwise.

        Examples:
            >>> troller = await compound.get_troller("0x1234567890abcdef1234567890abcdef12345678")
        """
        if self.trollers:
            async for troller, markets in Comptroller.markets.map(self.trollers.values()):
                if token_address in markets:
                    return troller

    @a_sync.a_sync(ram_cache_ttl=5 * 60, ram_cache_maxsize=ENVS.DEFAULT_CACHE_MAXSIZE)
    async def is_compound_market(self, token_address: AddressOrContract) -> bool:
        """
        Check if a token address is a Compound market.

        Args:
            token_address: The address of the token to check.

        Returns:
            True if the token address is a Compound market, False otherwise.

        Examples:
            >>> is_market = await compound.is_compound_market("0x1234567890abcdef1234567890abcdef12345678")
        """
        if await self.get_troller(token_address, sync=False):
            return True

        # NOTE: Workaround for pools that have since been revoked
        result = await has_methods(
            token_address,
            ("isCToken()(bool)", "comptroller()(address)", "underlying()(address)"),
            sync=False,
        )
        if result is True:
            await self.__notify_if_unknown_comptroller(token_address)
        return result

    @stuck_coro_debugger
    async def get_price(
        self,
        token_address: AnyAddressType,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
    ) -> PriceResult | None:
        """
        Get the price of a token in USD.

        Args:
            token_address: The address of the token.
            block: The block number to query. Defaults to the latest block.
            skip_cache: Whether to skip using the cache while fetching price data.

        Examples:
            >>> price = await compound.get_price("0x1234567890abcdef1234567890abcdef12345678")
            >>> price_at_block = await compound.get_price("0x1234567890abcdef1234567890abcdef12345678", block=12345678)
        """
        troller = await self.get_troller(token_address)
        return await CToken(token_address, comptroller=troller, asynchronous=True).get_price(
            block=block, skip_cache=skip_cache
        )

    async def __notify_if_unknown_comptroller(self, token_address: AddressOrContract) -> None:
        """
        Notify if a Comptroller is unknown to ypricemagic.

        Args:
            token_address: The address of the token.

        Examples:
            >>> await compound.__notify_if_unknown_comptroller("0x1234567890abcdef1234567890abcdef12345678")
        """
        comptroller = await raw_call(token_address, "comptroller()", output="address", sync=False)
        if comptroller not in self.trollers.values():
            _gh_issue_request(f"Comptroller {comptroller} is unknown to ypricemagic.", logger)


compound: Compound = Compound(asynchronous=True)
