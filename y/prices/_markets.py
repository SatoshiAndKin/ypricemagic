"""Immutable pool snapshots and native, fee-inclusive exact-input swaps."""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from brownie import ZERO_ADDRESS

from y._decorators import stuck_coro_debugger
from y.constants import EEE_ADDRESS
from y.datatypes import QuoteAsset, QuoteStep
from y.prices._quote import bounded_map
from y.prices._rpc import BlockRef, optional_read, read, state, unavailable


@dataclass(frozen=True)
class Market:
    protocol: str
    pool: str
    tokens: tuple[str, ...]
    balances: tuple[int, ...]
    router: str = ""
    fee: int = 0
    pool_id: bytes = b""
    stable: bool = False
    factory: str = ""

    def depth(self, token: str) -> int:
        return self.balances[self.tokens.index(token)]


def address(value: Any) -> str:
    return str(getattr(value, "address", value)).lower()


@stuck_coro_debugger
async def discover(token: str, block: BlockRef) -> tuple[Market, ...]:
    """Reuse registry indexes. Process each protocol with one bounded worker pool.

    Registry loading remains owned by the registry. No route prefix or amount
    enters this function's cache key.
    """
    from y import convert
    from y.prices.dex.balancer import balancer_multiplexer
    from y.prices.dex.solidly import SolidlyRouterBase
    from y.prices.dex.uniswap import uniswap_multiplexer
    from y.prices.dex.velodrome import VelodromeRouterV2
    from y.prices.stable_swap.curve import curve

    if token == address(EEE_ADDRESS):
        return ()
    checksum = await convert.to_address_async(token)
    router: Any
    pools: Any
    vault: Any
    balancer_v1: Any
    balancer_v2: Any
    markets: list[Market] = []

    async def safely(
        function: Callable[[Any], Awaitable[Market | None]], value: Any
    ) -> Market | None:
        try:
            return await function(value)
        except Exception as exc:
            if not unavailable(exc):
                raise
            return None

    async def loaded(work: Awaitable[Any], default: Any) -> Any:
        try:
            return await work
        except Exception as exc:
            if not unavailable(exc):
                raise
            return default

    async def collect(iterator: AsyncIterator[Any]) -> list[Any]:
        return [item async for item in iterator]

    for router in uniswap_multiplexer.v2_routers.values():
        # The existing immutable token index contains deployment data, including
        # cached Sushi tuples. Avoid pools_for_token's task-per-pool filter.
        pools = await loaded(router.get_pools_for(checksum, block=block.number, sync=False), {})

        async def v2_snapshot(pool: Any) -> Market | None:
            if await pool.deploy_block(when_no_history_return_0=True, sync=False) > block.number:
                return None
            tokens = tuple(address(t) for t in await pool.__tokens__)
            if token not in tokens:
                return None
            reserves = await state(address(pool), "getReserves()(uint256,uint256,uint256)", block)
            if not reserves or not reserves[tokens.index(token)]:
                return None
            protocol, stable = "Uniswap V2", False
            if isinstance(router, SolidlyRouterBase):
                stable = bool(await state(pool.address, "stable()(bool)", block))
                protocol = "Velodrome V2" if isinstance(router, VelodromeRouterV2) else "Solidly"
            return Market(
                protocol,
                address(pool),
                tokens,
                tuple(map(int, reserves[:2])),
                address(router),
                stable=stable,
                factory=address(router.factory),
            )

        markets.extend(m for m in await bounded_map(lambda p: safely(v2_snapshot, p), pools) if m)

    for router in [uniswap_multiplexer.v3, *uniswap_multiplexer.v3_forks]:
        if router is None:
            continue
        pools = await loaded(collect(router.pools_for_token(checksum, block.number)), [])

        async def v3_snapshot(pool: Any) -> Market | None:
            tokens = (address(pool.token0), address(pool.token1))
            balances = tuple(
                [
                    int(await state(t, "balanceOf(address)(uint256)", block, address(pool)))
                    for t in tokens
                ]
            )
            if not balances[tokens.index(token)]:
                return None
            return Market(
                "Uniswap V3",
                address(pool),
                tokens,
                balances,
                address(router._quoter),
                int(pool.fee),
                factory=address(router._factory),
            )

        markets.extend(m for m in await bounded_map(lambda p: safely(v3_snapshot, p), pools) if m)

    if curve:
        pools = (await loaded(curve.__coin_to_pools__, {})).get(checksum, ())

        async def curve_snapshot(pool: Any) -> Market | None:
            if await pool.deploy_block(when_no_history_return_0=True, sync=False) > block.number:
                return None
            # Read coin addresses at the requested block, not a latest registry.
            tokens, balances = [], []
            for index in range(8):
                coin = await optional_read(address(pool), "coins(uint256)(address)", block, index)
                if not coin or address(coin) == address(ZERO_ADDRESS):
                    break
                tokens.append(address(coin))
                balances.append(
                    int(await state(address(pool), "balances(uint256)(uint256)", block, index))
                )
            if token not in tokens or not balances[tokens.index(token)]:
                return None
            return Market("Curve", address(pool), tuple(tokens), tuple(balances))

        markets.extend(
            m for m in await bounded_map(lambda p: safely(curve_snapshot, p), pools) if m
        )

    balancer_v2 = await loaded(balancer_multiplexer.__v2__, None)
    if balancer_v2:
        for vault in balancer_v2.vaults:
            if await vault.deploy_block(when_no_history_return_0=True, sync=False) > block.number:
                continue
            pools = await loaded(collect(vault.pools(block=block.number)), [])

            async def balancer_snapshot(pool: Any) -> Market | None:
                pool_id = bytes(await pool.__id__)
                tokens, balances, _ = await state(
                    address(vault),
                    "getPoolTokens(bytes32)(address[],uint256[],uint256)",
                    block,
                    pool_id,
                )
                tokens = tuple(map(address, tokens))
                if token not in tokens or not balances[tokens.index(token)]:
                    return None
                return Market(
                    "Balancer V2",
                    address(pool),
                    tokens,
                    tuple(map(int, balances)),
                    address(vault),
                    pool_id=pool_id,
                )

            markets.extend(
                m for m in await bounded_map(lambda p: safely(balancer_snapshot, p), pools) if m
            )

    balancer_v1 = await loaded(balancer_multiplexer.__v1__, None)
    if balancer_v1 and balancer_v1.exchange_proxy:
        from y.classes.common import ERC20
        from y.prices.dex.balancer.v1 import TOKENOUTS_TO_TRY

        pools = set()
        for other in TOKENOUTS_TO_TRY:
            if address(other) != token:
                split = await loaded(
                    balancer_v1._get_split(
                        checksum, other.address, await ERC20._get_scale_for(checksum), block.number
                    ),
                    None,
                )
                if split:
                    pools.update(address(swap["pool"]) for swap in split["swaps"])

        async def balancer_v1_snapshot(pool: str) -> Market | None:
            tokens = tuple(map(address, await state(pool, "getCurrentTokens()(address[])", block)))
            balances = tuple(
                [int(await state(pool, "getBalance(address)(uint256)", block, t)) for t in tokens]
            )
            return Market("Balancer V1", pool, tokens, balances)

        markets.extend(
            m
            for m in await bounded_map(lambda p: safely(balancer_v1_snapshot, p), sorted(pools))
            if m
        )

    if uniswap_multiplexer.v1 and token != address(EEE_ADDRESS):
        exchange = await optional_read(
            uniswap_multiplexer.v1.factory, "getExchange(address)(address)", block, token
        )
        if exchange and address(exchange) != address(ZERO_ADDRESS):
            balance = await loaded(state(token, "balanceOf(address)(uint256)", block, exchange), 0)
            if balance:
                markets.append(
                    Market(
                        "Uniswap V1",
                        address(exchange),
                        (token, address(EEE_ADDRESS)),
                        (int(balance), 0),
                    )
                )

    return tuple(sorted(markets, key=lambda m: (-m.depth(token), m.protocol, m.pool)))


@stuck_coro_debugger
async def swap(market: Market, asset: QuoteAsset, output: str, block: BlockRef) -> QuoteStep | None:
    """Pass the full integer amount to the pool's native quote method."""
    token, amount, protocol = asset.token, asset.amount, market.protocol
    pool = market.pool
    method = ""
    limits = "native quote limits; holder balance and allowance unverified"
    if protocol == "Uniswap V2":
        method = "getAmountsOut(uint256,address[])"
        amounts = await read(market.router, method + "(uint256[])", block, amount, [token, output])
        result = int(amounts[-1])
    elif protocol in ("Solidly", "Velodrome V2"):
        route: tuple[Any, ...] = (token, output, market.stable)
        if protocol == "Velodrome V2":
            route = (*route, market.factory)
            method = "getAmountsOut(uint256,(address,address,bool,address)[])"
        else:
            method = "getAmountsOut(uint256,(address,address,bool)[])"
        result = int(
            (await read(market.router, method + "(uint256[])", block, amount, [route]))[-1]
        )
    elif protocol == "Uniswap V3":
        from eth_abi.packed import encode_packed

        from y.contracts import Contract

        method = "quoteExactInput(bytes,uint256)"
        quoter = await Contract.coroutine(market.router)
        quoted = await quoter.quoteExactInput.coroutine(
            encode_packed(["address", "uint24", "address"], [token, market.fee, output]),
            amount,
            block_identifier=block.number,
        )
        result = int(quoted if isinstance(quoted, int) else quoted[0])
    elif protocol == "Curve":
        from y.contracts import Contract

        method = "get_dy"
        contract = await Contract.coroutine(pool)
        result = int(
            await contract.get_dy.coroutine(
                market.tokens.index(token),
                market.tokens.index(output),
                amount,
                block_identifier=block.number,
            )
        )
    elif protocol == "Balancer V2":
        method = "queryBatchSwap(uint8,(bytes32,uint256,uint256,uint256,bytes)[],address[],(address,bool,address,bool))"
        deltas = await read(
            market.router,
            method + "(int256[])",
            block,
            0,
            [(market.pool_id, 0, 1, amount, b"")],
            [token, output],
            (ZERO_ADDRESS, False, ZERO_ADDRESS, False),
        )
        if len(deltas) != 2 or int(deltas[0]) != amount:
            return None
        result = -int(deltas[1])
    elif protocol == "Balancer V1":
        balance_in, balance_out = market.depth(token), market.depth(output)
        fee = int(await read(pool, "getSwapFee()(uint256)", block))
        max_ratio = int(await read(pool, "MAX_IN_RATIO()(uint256)", block))
        if (
            not await read(pool, "isPublicSwap()(bool)", block)
            or amount > (balance_in * max_ratio + 5 * 10**17) // 10**18
        ):
            return None
        method = "calcOutGivenIn(uint256,uint256,uint256,uint256,uint256,uint256)"
        weight_in = await read(pool, "getDenormalizedWeight(address)(uint256)", block, token)
        weight_out = await read(pool, "getDenormalizedWeight(address)(uint256)", block, output)
        result = int(
            await read(
                pool,
                method + "(uint256)",
                block,
                balance_in,
                weight_in,
                balance_out,
                weight_out,
                amount,
                fee,
            )
        )
    elif protocol == "Uniswap V1":
        method = "getTokenToEthInputPrice(uint256)"
        result = int(await read(pool, method + "(uint256)", block, amount))
    else:
        raise ValueError(f"unknown swap protocol {protocol}")
    if result <= 0:
        return None
    decimals = (
        18
        if output == address(EEE_ADDRESS)
        else int(await read(output, "decimals()(uint8)", block))
    )
    return QuoteStep(
        "swap",
        protocol,
        pool,
        asset,
        (QuoteAsset(output, result, decimals),),
        method,
        "DEX fees included in native quote",
        limits,
    )
