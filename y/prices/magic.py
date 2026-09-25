from collections.abc import Coroutine, Iterable
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from functools import wraps
from logging import Logger, getLogger
from typing import Any, Literal, Protocol, TypeVar, overload

import a_sync
import dank_mids
from brownie import ZERO_ADDRESS
from brownie.exceptions import ContractNotFound
from cachetools import TTLCache
from eth_typing import BlockNumber, ChecksumAddress, HexAddress

from y import ENVIRONMENT_VARIABLES as ENVS
from y import constants, convert
from y._decorators import stuck_coro_debugger
from y.classes import ERC20
from y.datatypes import AnyAddressType, Block, Pool, PriceResult, UsdPrice
from y.exceptions import NonStandardERC20, PriceError, yPriceMagicError
from y.prices import (
    band,
    chainlink,
    convex,
    curve_gauge,
    erc4626,
    exotic_tokens,
    one_to_one,
    pendle,
    popsicle,
    rkp3r,
    solidex,
    utils,
    yearn,
)
from y.prices._candidates import derive_price, pool_address, valid_price
from y.prices._usdc import USDC_VALUATION, fixed_usdc_price
from y.prices.dex import *
from y.prices.dex.uniswap import UniswapV2Pool
from y.prices.eth_derivs import *
from y.prices.gearbox import gearbox
from y.prices.lending import *
from y.prices.stable_swap import *
from y.prices.synthetix import synthetix
from y.prices.tokenized_fund import *
from y.utils.logging import get_price_logger

_TAddress = TypeVar("_TAddress", bound=AnyAddressType)

cache_logger = getLogger(f"{__name__}.cache")


@dataclass(frozen=True)
class _PriceRequest:
    dependencies: tuple[tuple[str, int], ...] = ()
    ignore_pools: tuple[Pool, ...] = ()
    skip_cache: bool = False


_price_request: ContextVar[_PriceRequest] = ContextVar("price_request", default=_PriceRequest())


def _shorten_address(address: str) -> str:
    """Shorten an Ethereum address to first 6 + last 4 chars, e.g. '0x1234...5678'."""
    address = str(address)
    if len(address) >= 12:
        return f"{address[:6]}...{address[-4:]}"
    return address


@overload
async def get_price(
    token_address: AnyAddressType,
    block: Block | None = None,
    *,
    amount: int | Decimal | None = None,
    fail_to_None: Literal[True],
    skip_cache: bool = ENVS.SKIP_CACHE,
    ignore_pools: tuple[Pool, ...] = (),
    silent: bool = False,
) -> PriceResult | None: ...


@overload
async def get_price(
    token_address: AnyAddressType,
    block: Block | None = None,
    *,
    amount: int | Decimal | None = None,
    fail_to_None: bool = False,
    skip_cache: bool = ENVS.SKIP_CACHE,
    ignore_pools: tuple[Pool, ...] = (),
    silent: bool = False,
) -> PriceResult: ...


@a_sync.a_sync(default="sync")
async def get_price(
    token_address: AnyAddressType,
    block: Block | None = None,
    *,
    amount: int | Decimal | None = None,
    fail_to_None: bool = False,
    skip_cache: bool = ENVS.SKIP_CACHE,
    ignore_pools: tuple[Pool, ...] = (),
    silent: bool = False,
) -> PriceResult | None:
    """
    Get the price of a token in USD.

    Args:
        token_address: The address of the token to price. The function accepts hexadecimal strings, Brownie Contract objects, and integers as shorthand for addresses.
        amount: Optional exact readable amount as an integer or Decimal. Returns a native sale estimate with structured quote details.
        block (optional): The block number at which to get the price. If None, uses the latest block.
        fail_to_None (optional): If True, return None instead of raising a :class:`~yPriceMagicError` on failure. Defaults to False.
        skip_cache (optional): If True, bypass the cache and fetch the price directly. Defaults to :obj:`ENVS.SKIP_CACHE`.
        ignore_pools (optional): A tuple of pool addresses to ignore when fetching the price.
        silent: If True, suppress error logging. Defaults to False.

    Returns:
        A :class:`~y.datatypes.PriceResult` containing the price and derivation path,
        or None if the price couldn't be determined and fail_to_None is True.
        PriceResult is backward-compatible with float (supports arithmetic and comparison).

    Raises:
        yPriceMagicError: If the price couldn't be determined and fail_to_None is False.

    Note:
        ypricemagic accepts integers as valid token_address values for convenience.
        For example, you can use :samp:`y.get_price(0x0bc529c00C6401aEF6D220BE8C6Ea1667F6Ad93e)` to save keystrokes
        while testing in an interactive console.

    Examples:
        >>> from y import get_price
        >>> price = get_price("0x0bc529c00C6401aEF6D220BE8C6Ea1667F6Ad93e", 12345678)
        >>> print(price)

    See Also:
        :func:`get_prices`
    """
    if amount is not None:
        from y.prices._quote import validate_amount

        validate_amount(amount)
    block = BlockNumber(int(await dank_mids.eth.block_number if block is None else block))
    token_address = await convert.to_address_async(token_address)
    parent = _price_request.get()
    # Recursive conversions inherit the exclusions of the lookup that owns them.
    ignore_pools = tuple(
        {pool_address(pool): pool for pool in (*parent.ignore_pools, *ignore_pools)}.values()
    )
    skip_cache = skip_cache or parent.skip_cache
    dependency = (str(token_address), block)
    request_token = _price_request.set(
        _PriceRequest(
            (*parent.dependencies, dependency),
            ignore_pools,
            skip_cache,
        )
    )
    try:
        if dependency in parent.dependencies:
            logger = get_price_logger(token_address, block, extra="cycle")
            try:
                logger.debug("cyclic price dependency: %s", parent.dependencies)
                _fail_appropriately(logger, str(token_address), fail_to_None, True)
                return None
            finally:
                logger.close()
        if amount is not None:
            from y.prices._routing import liquidity_price

            result = await liquidity_price(
                str(token_address),
                block,
                amount=amount,
                ignore_pools=ignore_pools,
                skip_cache=skip_cache,
            )
            if result is None and not fail_to_None:
                logger = get_price_logger(token_address, block, extra="amount")
                try:
                    _fail_appropriately(logger, str(token_address), False, silent)
                finally:
                    logger.close()
            return result
        return await _get_price(
            token_address,
            block,
            fail_to_None=fail_to_None,
            ignore_pools=ignore_pools,
            skip_cache=skip_cache,
            silent=silent,
        )
    except (ContractNotFound, NonStandardERC20, PriceError) as e:
        if not fail_to_None:
            try:
                symbol = await ERC20(token_address, asynchronous=True).symbol
            except NonStandardERC20:
                symbol = str(token_address)
            raise_from = None if isinstance(e, PriceError) else e
            raise yPriceMagicError(e, token_address, block, symbol) from raise_from
        return None
    finally:
        _price_request.reset(request_token)


@overload
async def get_prices(
    token_addresses: Iterable[AnyAddressType],
    block: Block | None = None,
    *,
    amounts: Iterable[int | Decimal] | None = None,
    fail_to_None: Literal[True],
    skip_cache: bool = ENVS.SKIP_CACHE,
    silent: bool = False,
) -> list[PriceResult | None]: ...


@overload
async def get_prices(
    token_addresses: Iterable[AnyAddressType],
    block: Block | None = None,
    *,
    amounts: Iterable[int | Decimal] | None = None,
    fail_to_None: bool = False,
    skip_cache: bool = ENVS.SKIP_CACHE,
    silent: bool = False,
) -> list[PriceResult]: ...


@a_sync.a_sync(default="sync")
async def get_prices(
    token_addresses: Iterable[AnyAddressType],
    block: Block | None = None,
    *,
    amounts: Iterable[int | Decimal] | None = None,
    fail_to_None: bool = False,
    skip_cache: bool = ENVS.SKIP_CACHE,
    silent: bool = False,
) -> list[PriceResult | None]:
    """
    Get prices for multiple tokens in USD.

    This function is optimized for parallel execution and should be preferred over
    :func:`get_price` when querying prices in bulk.

    Args:
        token_addresses: An iterable of token addresses to price.
        amounts: Optional aligned integer or Decimal amounts in readable tokens. Duplicate tokens retain their own amounts and input order.
        block (optional): The block number at which to get the prices. If None, defaults to the latest block.
        fail_to_None (optional): If True, return None for tokens whose price couldn't be determined. Defaults to False.
        skip_cache (optional): If True, bypass the cache and fetch prices directly. Defaults to :obj:`ENVS.SKIP_CACHE`.
        silent (optional): If True, suppress error logging and any progress indicators. Defaults to False.

    Returns:
        A list of token prices in USD, in the same order as the input :samp:`token_addresses`.

    Examples:
        >>> from y import get_prices
        >>> prices = get_prices(["0x123...", "0x456..."], block=12345678)
        >>> print(prices)

    See Also:
        :func:`get_price` and :func:`map_prices`
    """
    from y.prices._quote import bounded_map, validate_amount

    tokens = list(token_addresses)
    sizes: list[int | Decimal | None] = (
        list(amounts) if amounts is not None else [None] * len(tokens)
    )
    if len(tokens) != len(sizes):
        raise ValueError("amounts must have the same length as token_addresses")
    if amounts is not None:
        sizes = [validate_amount(size) for size in sizes]
    if not tokens:
        return []
    resolved = int(await dank_mids.eth.block_number if block is None else block)

    async def quote(item: tuple[Any, int | Decimal | None]) -> PriceResult | None:
        token, size = item
        lookup: Any = get_price
        result: PriceResult | None = await lookup(
            token,
            resolved,
            amount=size,
            fail_to_None=fail_to_None,
            skip_cache=skip_cache,
            silent=silent,
            sync=False,
        )
        return result

    return await bounded_map(quote, zip(tokens, sizes))


@overload
def map_prices(
    token_addresses: Iterable[_TAddress],
    block: Block,
    *,
    fail_to_None: Literal[True],
    skip_cache: bool = ENVS.SKIP_CACHE,
    silent: bool = False,
) -> a_sync.TaskMapping[_TAddress, PriceResult | None]: ...


@overload
def map_prices(
    token_addresses: Iterable[_TAddress],
    block: Block,
    *,
    fail_to_None: bool = False,
    skip_cache: bool = ENVS.SKIP_CACHE,
    silent: bool = False,
) -> a_sync.TaskMapping[_TAddress, PriceResult]: ...


def map_prices(
    token_addresses: Iterable[_TAddress],
    block: Block,
    *,
    fail_to_None: bool = False,
    skip_cache: bool = ENVS.SKIP_CACHE,
    silent: bool = False,
) -> a_sync.TaskMapping[_TAddress, PriceResult | None]:
    """
    Map token addresses to their prices asynchronously.

    Args:
        token_addresses: An iterable of token addresses to price.
        amounts: Optional aligned integer or Decimal amounts in readable tokens. Duplicate tokens retain their own amounts and input order.
        block (optional): The block number at which to get the prices.
        fail_to_None (optional): If True, map tokens whose price couldn't be determined to None. Defaults to False.
        skip_cache (optional): If True, bypass the cache and fetch prices directly. Defaults to :obj:`ENVS.SKIP_CACHE`.
        silent (optional): If True, suppress error logging. Defaults to False.

    Returns:
        A :class:`~a_sync.TaskMapping` object mapping token addresses to their USD prices.

    Examples:
        >>> from y import map_prices
        >>> task_map = map_prices(["0xabc...", "0xdef..."], 12345678)
        >>> results = await task_map.values(pop=True)
        >>> print(results)
        [1.234, 2.345]

    See Also:
        :func:`get_prices`
    """
    return a_sync.map(
        get_price,
        token_addresses,
        block=block,
        fail_to_None=fail_to_None,
        skip_cache=skip_cache,
        silent=silent,
    )


class _PriceLookup(Protocol):
    def __call__(
        self,
        token: ChecksumAddress,
        block: BlockNumber,
        *,
        fail_to_None: bool = False,
        skip_cache: bool = ENVS.SKIP_CACHE,
        ignore_pools: tuple[Pool, ...] = (),
        silent: bool = False,
    ) -> Coroutine[Any, Any, PriceResult | None]: ...


def __cache(get_price: _PriceLookup) -> _PriceLookup:
    """
    A decorator to cache the results of the get_price function.

    The DB cache stores only the numeric price value.  On cache hits a
    :class:`~y.datatypes.PriceResult` is reconstructed with an empty path
    (the derivation path is not persisted).

    Args:
        get_price: The function to be cached.

    Returns:
        A wrapped version of the input function with caching functionality.
    """

    prices: TTLCache[tuple[ChecksumAddress, BlockNumber], PriceResult] = TTLCache(
        maxsize=int(ENVS.PRICE_CACHE_MAXSIZE), ttl=int(ENVS.CACHE_TTL)
    )

    @wraps(get_price)
    async def cache_wrap(
        token: ChecksumAddress,
        block: BlockNumber,
        *,
        fail_to_None: bool = False,
        skip_cache: bool = ENVS.SKIP_CACHE,
        ignore_pools: tuple[Pool, ...] = (),
        silent: bool = False,
    ) -> PriceResult | None:
        fixed = fixed_usdc_price(str(token), constants.CHAINID)
        if fixed is not None:
            return fixed

        from y._db.utils import price as db

        use_cache = (
            not skip_cache and not ignore_pools and len(_price_request.get().dependencies) <= 1
        )
        key = (token, block)
        if use_cache:
            if key in prices:
                return deepcopy(prices[key])
            cached_price = await db.get_price(token, block)
            if cached_price is not None and valid_price(cached_price):
                cache_logger.debug("disk cache -> %s", cached_price)
                return PriceResult(price=UsdPrice(cached_price), path=[])
        result = await get_price(
            token,
            block=block,
            fail_to_None=fail_to_None,
            ignore_pools=ignore_pools,
            skip_cache=skip_cache,
            silent=silent,
        )
        if result is not None and valid_price(result) and use_cache:
            prices[key] = deepcopy(result)
            # Store only the numeric price in DB, not the derivation path
            db.set_price(token, block, Decimal(str(float(result.price))))
        return result

    return cache_wrap


@stuck_coro_debugger
@__cache
async def _get_price(
    token: ChecksumAddress,
    block: BlockNumber,
    *,
    fail_to_None: bool = False,
    skip_cache: bool = ENVS.SKIP_CACHE,
    ignore_pools: tuple[Pool, ...] = (),
    silent: bool = False,
) -> PriceResult | None:  # sourcery skip: remove-redundant-if
    """
    Internal function to get the price of a token.

    This function implements the core logic for fetching token prices.
    Every successful code path returns a :class:`~y.datatypes.PriceResult`
    with a human-readable source description in its ``path``.

    Args:
        token: The address of the token to price.
        block: The block number at which to get the price.
        fail_to_None: If True, return None instead of raising an exception on failure.
        skip_cache: If True, bypass the cache and fetch the price directly.
        ignore_pools: A tuple of pool addresses to ignore when fetching the price.
        silent: If True, suppress error logging.

    Returns:
        A :class:`~y.datatypes.PriceResult` containing the price and derivation path,
        or None if the price couldn't be determined and fail_to_None is True.
    """
    if token == ZERO_ADDRESS:
        logger = get_price_logger(
            token, block, symbol="[ZERO_ADDRESS]", extra="magic", start_task=True
        )
        try:
            _fail_appropriately(logger, "[ZERO_ADDRESS]", fail_to_None, silent)
            return None
        finally:
            logger.close()

    try:
        # We do this to cache the symbol for later, otherwise some repr woudl break
        symbol = await ERC20(token, asynchronous=True).symbol
    except NonStandardERC20:
        symbol = None

    logger = get_price_logger(token, block, symbol=symbol, extra="magic", start_task=True)
    try:
        logger.debug("fetching price for %s", symbol)
        raw_price = None
        source = None

        # Try API first
        api_price = await _get_price_from_api(token, block, logger)
        if valid_price(api_price):
            raw_price = api_price
            source = f"ypriceapi for {_shorten_address(token)}"

        # Try bucket-specific pricing
        if raw_price is None:
            bucket_price, bucket_source = await _exit_early_for_known_tokens(
                token,
                block=block,
                ignore_pools=ignore_pools,
                skip_cache=skip_cache,
                logger=logger,
            )
            if valid_price(bucket_price):
                raw_price = bucket_price
                source = bucket_source

        # Try DEX fallback
        if raw_price is None:
            dex_price, dex_source = await _get_price_from_dexes(
                token, block, ignore_pools, skip_cache, logger
            )
            if valid_price(dex_price):
                raw_price = dex_price
                source = dex_source

        if raw_price is not None and valid_price(raw_price):
            # Extract numeric price for sense_check (handles PriceResult from recursive calls)
            numeric_price = raw_price.price if isinstance(raw_price, PriceResult) else raw_price
            await utils.sense_check(token, block, float(numeric_price))
        else:
            _fail_appropriately(logger, symbol, fail_to_None, silent)
        logger.debug("%s price: %s", symbol, raw_price)
        if raw_price is not None and valid_price(raw_price):
            if (
                isinstance(raw_price, PriceResult)
                and raw_price.path
                and raw_price.path[0].token == str(token)
            ):
                return raw_price
            return derive_price(
                token,
                float(raw_price),
                source or f"unknown pricing for {_shorten_address(token)}",
                raw_price,
            )
        return None

    finally:
        logger.close()


@stuck_coro_debugger
async def _exit_early_for_known_tokens(
    token_address: ChecksumAddress,
    block: BlockNumber,
    logger: Logger,
    skip_cache: bool = ENVS.SKIP_CACHE,
    ignore_pools: tuple[Pool, ...] = (),
) -> tuple[UsdPrice | PriceResult | Decimal | None, str | None]:  # sourcery skip: low-code-quality
    """
    Attempt to get the price for known token types without having to fully load everything.

    This function checks if the token is of a known type (e.g., atoken, balancer pool, etc.)
    and attempts to get its price using type-specific methods.

    Args:
        token_address: The address of the token to price.
        block: The block number at which to get the price.
        logger: A logger instance for recording debug information.
        skip_cache: If True, bypass the cache and fetch the price directly.
        ignore_pools: A tuple of pool addresses to ignore when fetching the price.

    Returns:
        A tuple of ``(price, source_string)`` if the price can be determined early,
        or ``(None, None)`` otherwise.  The source string is a human-readable
        description used to construct the :class:`~y.datatypes.PriceStep`.
    """
    bucket = await utils.check_bucket(token_address, block=block, sync=False)

    price: UsdPrice | PriceResult | Decimal | None = None
    source = None
    addr_short = _shorten_address(token_address)

    if bucket == "atoken":
        price = await aave.get_price(token_address, block=block, skip_cache=skip_cache, sync=False)
        if price is not None:
            try:
                sym = await ERC20(token_address, asynchronous=True).symbol
            except NonStandardERC20:
                sym = addr_short
            # Detect Aave version from symbol prefix
            version = "2" if str(sym).startswith("a") and not str(sym).startswith("aW") else "3"
            source = f"Aave v{version} {sym} underlying"

    elif bucket == "balancer pool":
        price = await balancer_multiplexer.get_pool_price(
            token_address, block, skip_cache=skip_cache, ignore_pools=ignore_pools, sync=False
        )
        if price is not None:
            source = f"Balancer pool {addr_short}"

    elif bucket == "basketdao":
        price = await basketdao.get_price(token_address, block, skip_cache=skip_cache, sync=False)
        if price is not None:
            source = f"BasketDAO pricing for {addr_short}"

    elif bucket == "belt lp":
        price = await belt.get_price(token_address, block, sync=False)
        if price is not None:
            source = f"Belt LP pricing for {addr_short}"

    elif bucket == "chainlink and band":
        price = await chainlink.get_price(token_address, block, sync=False)
        if valid_price(price):
            source = f"Chainlink feed for {addr_short}"
        else:
            price = await band.get_price(token_address, block, sync=False)
            if price is not None:
                source = f"Band USDC rate for {addr_short}; {USDC_VALUATION}"

    elif bucket == "chainlink feed":
        price = await chainlink.get_price(token_address, block, sync=False)
        if price is not None:
            source = f"Chainlink feed for {addr_short}"

    elif bucket == "compound":
        price = await compound.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            try:
                sym = await ERC20(token_address, asynchronous=True).symbol
            except NonStandardERC20:
                sym = addr_short
            source = f"Compound {sym} underlying"

    elif bucket == "convex":
        raw = await convex.get_price(token_address, block, skip_cache=skip_cache, sync=False)
        if raw is not None:
            price = raw
            underlying = await convex.get_underlying_lp(token_address, sync=False)
            underlying_short = _shorten_address(str(underlying)) if underlying else addr_short
            source = f"Convex wrapping Curve LP {underlying_short}"

    elif bucket == "curve gauge":
        raw = await curve_gauge.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if raw is not None:
            price = raw
            lp_addr = await curve_gauge._get_lp_token(await convert.to_address_async(token_address))
            lp_short = _shorten_address(lp_addr) if lp_addr else addr_short
            source = f"Curve gauge for LP {lp_short}"

    elif bucket == "creth":
        price = await creth.get_price_creth(token_address, block, skip_cache=skip_cache, sync=False)
        if price is not None:
            source = f"crETH pricing for {addr_short}"

    elif bucket == "curve lp":
        price = await curve.get_price(token_address, block, skip_cache=skip_cache, sync=False)
        if price is not None:
            try:
                sym = await ERC20(token_address, asynchronous=True).symbol
            except NonStandardERC20:
                sym = addr_short
            source = f"Curve {sym} LP"

    elif bucket == "erc4626 vault":
        price = await erc4626.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = price.path[0].source

    elif bucket == "ellipsis lp":
        price = await ellipsis.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Ellipsis LP pricing for {addr_short}"

    elif bucket == "froyo":
        price = await froyo.get_price(token_address, block=block, sync=False)
        if price is not None:
            source = f"Froyo pricing for {addr_short}"

    elif bucket == "gearbox":
        price = await gearbox.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Gearbox pricing for {addr_short}"

    elif bucket == "gelato":
        price = await gelato.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Gelato pricing for {addr_short}"

    elif bucket == "generic amm":
        price = await generic_amm.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Generic AMM pricing for {addr_short}"

    elif bucket == "ib token":
        price = await ib.get_price(token_address, block=block, skip_cache=skip_cache, sync=False)
        if price is not None:
            source = f"Iron Bank pricing for {addr_short}"

    elif bucket == "mooniswap lp":
        price = await mooniswap.get_pool_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Mooniswap LP pricing for {addr_short}"

    elif bucket == "mstable feeder pool":
        price = await mstablefeederpool.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"mStable feeder pool pricing for {addr_short}"

    elif bucket == "one to one":
        price = await one_to_one.get_price(token_address, block, skip_cache=skip_cache, sync=False)
        if price is not None:
            target = one_to_one.MAPPING.get(str(token_address), "")
            target_short = _shorten_address(target) if target else addr_short
            source = f"1:1 peg with {target_short}"

    elif bucket == "pendle lp":
        price = await pendle.get_lp_price(token_address, block, skip_cache=skip_cache, sync=False)
        if price is not None:
            source = f"Pendle LP pricing for {addr_short}"

    elif bucket == "piedao lp":
        price = await piedao.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"PieDAO LP pricing for {addr_short}"

    elif bucket == "popsicle":
        price = await popsicle.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Popsicle pricing for {addr_short}"

    elif bucket == "reserve":
        price = await reserve.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Reserve pricing for {addr_short}"

    elif bucket == "rkp3r":
        price = await rkp3r.get_price(token_address, block, skip_cache=skip_cache, sync=False)
        if price is not None:
            source = f"rKP3R pricing for {addr_short}"

    elif bucket == "saddle":
        price = await saddle.get_price(token_address, block, skip_cache=skip_cache, sync=False)
        if price is not None:
            source = f"Saddle pricing for {addr_short}"

    elif bucket == "stargate lp":
        price = await stargate.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Stargate LP pricing for {addr_short}"

    elif bucket == "solidex":
        price = await solidex.get_price(token_address, block, skip_cache=skip_cache, sync=False)
        if price is not None:
            source = f"Solidex pricing for {addr_short}"

    elif bucket == "stable usd":
        # A classification can come from memory or disk. It never fixes a USD price.
        if chainlink:
            oracle: Any = chainlink
            price = await oracle.get_price(token_address, block, sync=False)
        if valid_price(price):
            source = f"Chainlink historical stablecoin USD for {token_address}"

    elif bucket == "synthetix":
        price = await synthetix.get_price(token_address, block, sync=False)
        if price is not None:
            source = f"Synthetix pricing for {addr_short}"

    elif bucket == "token set":
        price = await tokensets.get_price(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"TokenSet pricing for {addr_short}"

    elif bucket == "uni or uni-like lp":
        price = await UniswapV2Pool(token_address).get_price(
            block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Uniswap V2 LP pool {addr_short}"

    elif bucket == "wrapped gas coin":
        price = await get_price(
            constants.WRAPPED_GAS_COIN, block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Wrapped gas coin pricing for {addr_short}"

    elif bucket == "wrapped atoken v2":
        price = await aave.get_price_wrapped_v2(
            token_address, block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            try:
                sym = await ERC20(token_address, asynchronous=True).symbol
            except NonStandardERC20:
                sym = addr_short
            source = f"Aave v2 wrapped {sym} underlying"

    elif bucket == "wrapped atoken v3":
        price = await aave.get_price_wrapped_v3(
            token_address, block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            try:
                sym = await ERC20(token_address, asynchronous=True).symbol
            except NonStandardERC20:
                sym = addr_short
            source = f"Aave v3 wrapped {sym} underlying"

    elif bucket == "wsteth":
        price = await wsteth.wsteth.get_price(block, skip_cache=skip_cache, sync=False)
        if price is not None:
            source = "Lido wstETH via stEthPerToken"

    elif bucket == "yearn or yearn-like":
        price = await yearn.get_price(
            token_address,
            block,
            skip_cache=skip_cache,
            ignore_pools=ignore_pools,
            sync=False,
        )
        if price is not None:
            try:
                sym = await ERC20(token_address, asynchronous=True).symbol
            except NonStandardERC20:
                sym = addr_short
            source = f"Yearn {sym} vault share price"

    elif bucket == "pickle pslp":
        price = await exotic_tokens.get_price_pickle_pslp(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Pickle pSLP {addr_short} via getRatio"

    elif bucket == "pool together v4 ticket":
        price = await exotic_tokens.get_price_pool_together_v4(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"PoolTogether V4 Ticket {addr_short} 1:1 with underlying"

    elif bucket == "xpremia":
        price = await exotic_tokens.get_price_xpremia(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"xPREMIA {addr_short} via PREMIA backing per share"

    elif bucket == "xtarot":
        price = await exotic_tokens.get_price_tarot_vault(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"xTAROT {addr_short} via shareValuedAsUnderlying"

    elif bucket == "tarot supply vault":
        price = await exotic_tokens.get_price_tarot_vault(
            token_address, block=block, skip_cache=skip_cache, sync=False
        )
        if price is not None:
            source = f"Tarot SupplyVault {addr_short} via shareValuedAsUnderlying"

    logger.debug("%s -> %s", bucket, price)

    return price, source


async def _get_price_from_api(
    token: HexAddress,
    block: BlockNumber,
    logger: Logger,
):
    """
    Attempt to get the price from the ypricemagic API.

    Args:
        token: The address of the token to price.
        block: The block number at which to get the price.
        logger: A logger instance for recording debug information.

    Returns:
        The price of the token if it can be fetched from the ypricemagic API, or None otherwise.
    """
    if utils.ypriceapi.should_use and token not in utils.ypriceapi.skip_tokens:
        price = await utils.ypriceapi.get_price(token, block)
        logger.debug("ypriceapi -> %s", price)
        return price


@stuck_coro_debugger
async def _get_price_from_dexes(
    token: ChecksumAddress,
    block: BlockNumber,
    ignore_pools,
    skip_cache: bool,
    logger: Logger,
) -> tuple[UsdPrice | PriceResult | None, str | None]:
    """
    Attempt to get the price from decentralized exchanges.

    This function tries to fetch the price from various DEXes like Uniswap, Curve, and Balancer.

    Args:
        token: The address of the token to price.
        block : The block number at which to get the price.
        ignore_pools: A tuple of pool addresses to ignore when fetching the price.
        skip_cache: If True, bypass the cache and fetch the price directly.
        logger: A logger instance for recording debug information.

    Returns:
        A tuple of ``(price, source_string)`` if the price can be determined from DEXes,
        or ``(None, None)`` otherwise.
    """
    from y.prices._routing import liquidity_price

    price = await liquidity_price(
        str(token), block, ignore_pools=ignore_pools, skip_cache=skip_cache
    )
    return price, "Liquidity-based price estimation" if price is not None else None


def _fail_appropriately(
    logger: Logger,
    symbol: str,
    fail_to_None: bool,
    silent: bool,
) -> None:
    """
    Handle failure to get a price appropriately.

    This function decides how to handle a failure to get a price based on the input parameters.

    Args:
        logger: A logger instance for recording error information.
        symbol: The symbol of the token whose price couldn't be determined.
        fail_to_None: If True, the function will return silently. If False, it will raise a PriceError.
        silent: If True, suppress error logging.

    Raises:
        PriceError: If fail_to_None is False.
    """
    if not silent:
        logger.warning(f"failed to get price for {symbol}")

    if not fail_to_None:
        raise PriceError(logger, symbol)
