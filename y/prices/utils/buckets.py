from asyncio import iscoroutine
from collections.abc import Awaitable, Callable
from logging import DEBUG, getLogger
from typing import Any

import a_sync
from brownie.exceptions import ContractNotFound

from y import ENVIRONMENT_VARIABLES as ENVS
from y import convert
from y._decorators import stuck_coro_debugger
from y.classes.common import ERC20
from y.constants import STABLECOINS
from y.datatypes import Address, AnyAddressType
from y.exceptions import ContractNotVerified, NonStandardERC20, call_reverted
from y.prices import (
    convex,
    curve_gauge,
    erc4626,
    exotic_tokens,
    one_to_one,
    pendle,
    popsicle,
    rkp3r,
    solidex,
    yearn,
)
from y.prices._candidates import gather_owned
from y.prices.band import band
from y.prices.chainlink import chainlink
from y.prices.dex import mooniswap
from y.prices.dex.balancer import balancer_multiplexer
from y.prices.dex.genericamm import is_generic_amm
from y.prices.dex.uniswap import uniswap_multiplexer
from y.prices.eth_derivs import creth, wsteth
from y.prices.gearbox import gearbox
from y.prices.lending import ib
from y.prices.lending.aave import aave
from y.prices.lending.compound import compound
from y.prices.stable_swap import (
    belt,
    ellipsis,
    froyo,
    mstablefeederpool,
    saddle,
    stargate,
)
from y.prices.stable_swap.curve import curve
from y.prices.synthetix import synthetix
from y.prices.tokenized_fund import basketdao, gelato, piedao, reserve, tokensets
from y.utils.logging import get_price_logger

logger = getLogger(__name__)


@a_sync.a_sync(default="sync", cache_type="memory", ram_cache_maxsize=ENVS.CONTRACT_CACHE_MAXSIZE)
@stuck_coro_debugger
async def check_bucket(token: AnyAddressType, block: int | None = None) -> str | None:
    """Determine and return the category or "bucket" of a given token.

    Calls-only checks and heavy checks each run concurrently and finish before
    classification. The declared check order fixes priority. The Uniswap LP
    check has priority over Solidex. Cancellation and fatal failures drain all
    owned check tasks. Historical oracle eligibility uses the requested block.

    Args:
        token: The token address to classify.

    Examples:
        Basic usage with a stable USD token:
            >>> bucket = check_bucket("0x6B175474E89094C44Da98b954EedeAC495271d0F")
            >>> print(bucket)
            stable usd

        Example triggering a concurrent asynchronous test:
            >>> bucket = check_bucket("0xSomeLPTokenAddress")
            >>> print(bucket)
            popsicle

        Example where multiple fallback conditions are met (note that if both "solidex" and
        "uni or uni-like lp" tests pass, the latter overwrites the former):
            >>> bucket = check_bucket("0xAnotherTokenAddress")
            >>> print(bucket)
            uni or uni-like lp

    See Also:
        :func:`y.convert.to_address_async`
        :func:`y.utils.logging.get_price_logger`
        :func:`_check_bucket_helper` (Helper used for asynchronous bucket checks)
    """
    token_address = await convert.to_address_async(token)
    logger = get_price_logger(token_address, block=None, extra="buckets")

    import y._db.utils.token as db

    bucket = await db.get_bucket(token_address)
    if bucket and bucket not in ("chainlink feed", "chainlink and band"):
        logger.debug("returning bucket %s from ydb", bucket)
        return bucket

    debug_logs_enabled = logger.isEnabledFor(DEBUG)

    # these require neither calls to the chain nor contract initialization, just string comparisons (pretty sure)
    for bucket, check in string_matchers.items():
        if check(token_address):
            if debug_logs_enabled:
                await __log_bucket(token_address, bucket)
            db.set_bucket(token_address, bucket)
            return bucket
        elif debug_logs_enabled:
            await __log_not_bucket(token_address, bucket)

    # Dictionary order defines priority, independently of completion order.
    results = await gather_owned(
        _safe_check_bucket(name, _check_bucket_helper(name, check, token_address), paired=True)
        for name, check in calls_only.items()
    )
    for bucket, is_member in results:
        if is_member:
            if debug_logs_enabled:
                await __log_bucket(token_address, bucket)
            db.set_bucket(token_address, bucket)
            return bucket

    # These require both calls and contract initializations.
    # All checks run concurrently; the first match by priority wins.
    # Priority order preserves original semantics: "uni or uni-like lp"
    # beats "solidex" when both match.
    heavy_checks: list[tuple[str, Awaitable[bool]]] = [
        ("solidex", solidex.is_solidex_deposit(token_address, sync=False)),
        ("uni or uni-like lp", uniswap_multiplexer.is_uniswap_pool(token_address, sync=False)),
    ]
    if gearbox:
        heavy_checks.append(("gearbox", gearbox.is_diesel_token(token_address, sync=False)))
    heavy_checks.extend(
        [
            ("wrapped atoken v2", aave.is_wrapped_atoken_v2(token_address, sync=False)),
            ("wrapped atoken v3", aave.is_wrapped_atoken_v3(token_address, sync=False)),
            ("generic amm", is_generic_amm(token_address)),
            ("mooniswap lp", mooniswap.is_mooniswap_pool(token_address, sync=False)),
            ("compound", compound.is_compound_market(token_address, sync=False)),
            ("chainlink and band", _chainlink_and_band(token_address, block)),
        ]
    )
    if chainlink:
        heavy_checks.append(
            ("chainlink feed", chainlink.has_feed(token_address, block=block, sync=False))
        )
    if synthetix:
        heavy_checks.append(("synthetix", synthetix.is_synth(token_address, sync=False)))
    heavy_checks.append(("yearn or yearn-like", yearn.is_yearn_vault(token_address, sync=False)))
    if curve:
        heavy_checks.append(("curve lp", curve.get_pool(token_address, sync=False)))

    heavy_results = dict(
        await gather_owned(_safe_check_bucket(name, coro) for name, coro in heavy_checks)
    )

    # Pick the highest-priority match.
    # Special case: "uni or uni-like lp" overwrites "solidex" (original behavior).
    bucket = None
    if heavy_results.get("solidex"):
        bucket = "solidex"
    if heavy_results.get("uni or uni-like lp"):
        bucket = "uni or uni-like lp"
    if bucket is None:
        for name, _coro in heavy_checks[2:]:
            if heavy_results.get(name):
                bucket = name
                break

    if debug_logs_enabled:
        await __log_bucket(token_address, bucket)
    if bucket and bucket not in ("chainlink feed", "chainlink and band"):
        db.set_bucket(token_address, bucket)
    return bucket


# these require neither calls to the chain nor contract initialization, just string comparisons (pretty sure)
string_matchers = {
    "wrapped gas coin": lambda address: address == "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
    "stable usd": lambda address: address in STABLECOINS,
    "one to one": one_to_one.is_one_to_one_token,
    "wsteth": wsteth.is_wsteth,
    "creth": creth.is_creth,
    "belt lp": belt.is_belt_lp,
    "froyo": froyo.is_froyo,
    "rkp3r": rkp3r.is_rkp3r,
}

# these just require calls
calls_only = {
    "convex": convex.is_convex_lp,
    "atoken": aave.is_atoken,
    "balancer pool": balancer_multiplexer.is_balancer_pool,
    "ib token": ib.is_ib_token,
    "gelato": gelato.is_gelato_pool,
    "pendle lp": pendle.is_pendle_lp,
    "piedao lp": piedao.is_pie,
    "token set": tokensets.is_token_set,
    "ellipsis lp": ellipsis.is_eps_rewards_pool,
    "mstable feeder pool": mstablefeederpool.is_mstable_feeder_pool,
    "saddle": saddle.is_saddle_lp,
    "basketdao": basketdao.is_basketdao_index,
    "popsicle": popsicle.is_popsicle_lp,
    "reserve": reserve.is_rtoken,
    "stargate lp": stargate.is_stargate_lp,
    "curve gauge": curve_gauge.is_curve_gauge,
    "erc4626 vault": erc4626.is_erc4626_vault,
    "pickle pslp": exotic_tokens.is_pickle_pslp,
    "pool together v4 ticket": exotic_tokens.is_pool_together_v4_ticket,
    "xpremia": exotic_tokens.is_xpremia,
    "xtarot": exotic_tokens.is_xtarot,
    "tarot supply vault": exotic_tokens.is_tarot_supply_vault,
}


async def _safe_check_bucket(
    name: str, coro: Awaitable[Any], paired: bool = False
) -> tuple[str, bool]:
    """Treat unavailable contracts as nonmembers; propagate unexpected errors."""
    try:
        result = await coro
        return (str(result[0]), bool(result[1])) if paired else (name, bool(result))
    except Exception as e:
        if not isinstance(
            e, (ContractNotFound, ContractNotVerified, NonStandardERC20)
        ) and not call_reverted(e):
            raise
        logger.warning("%s when checking %s. This will probably not impact your run.", e, name)
        logger.warning(e, exc_info=True)
        return name, False


async def _chainlink_and_band(token_address, block) -> bool:
    """
    Check if a token is supported by both Chainlink and Band oracles.

    This function is primarily used for historical data on the Fantom network,
    where Band was used before Chainlink became available.

    Args:
        token_address: The address of the token to check.

    Examples:
        >>> is_supported = await _chainlink_and_band("0x6B175474E89094C44Da98b954EedeAC495271d0F")
        >>> print(is_supported)
        True

    See Also:
        - :func:`y.prices.chainlink.has_feed`
    """
    return (
        bool(chainlink)
        and await chainlink.has_feed(token_address, block=block, sync=False)
        and token_address in band
    )


async def _check_bucket_helper(
    bucket: str, check: Callable[[Address], Awaitable[bool]], address: Address
) -> tuple[str, bool]:
    """
    Asynchronously check if a token belongs to a specified bucket.

    This helper function is designed to be executed concurrently as part of the
    "calls-only" checks in :func:`check_bucket`. It invokes a callable that returns
    a boolean indicating whether the token meets the criterion for the specified bucket.
    If the result is not immediately boolean, it awaits the result further.

    Args:
        bucket: The name of the bucket to check.
        check: A callable that checks if the token belongs to the bucket.
        address: The address of the token to check.

    Examples:
        >>> async def dummy_check(addr):
        ...     return addr.startswith("0x")
        >>> result = await _check_bucket_helper("dummy", dummy_check, "0x123")
        >>> print(result)
        ('dummy', True)

    See Also:
        - :func:`check_bucket`
    """
    result = await check(address, sync=False)

    # TODO: debug why we have to re-await sometimes when @optional_async_diskcache is used
    if not isinstance(result, bool):
        if not iscoroutine(result):
            raise TypeError(f"{bucket} result must be boolean. You passed {result}")
        result = await result
    if not isinstance(result, bool):
        # if not iscoroutine(result):
        raise TypeError(f"{bucket} result must be boolean. You passed {result}")
        # result = await result
    return bucket, result


async def __log_bucket(token, bucket):
    symbol = await ERC20(token, asynchronous=True).symbol
    logger._log(DEBUG, "%s %s bucket is %s", (symbol, token, bucket))


async def __log_not_bucket(token, bucket):
    symbol = await ERC20(token, asynchronous=True).symbol
    logger._log(DEBUG, "%s %s bucket is not %s", (symbol, token, bucket))
