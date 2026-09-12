"""Liquidity-based price estimation. This does not maximize route prices."""

from dataclasses import dataclass, field, replace
from decimal import Decimal, localcontext
from functools import lru_cache
from typing import Any

from y._decorators import stuck_coro_debugger
from y.constants import EEE_ADDRESS, STABLECOINS, WRAPPED_GAS_COIN
from y.datatypes import (
    PriceResult,
    PriceStep,
    QuoteAsset,
    QuoteDetails,
    QuoteStep,
    UsdPrice,
)
from y.prices._candidates import valid_price
from y.prices._markets import Market, address, discover, swap
from y.prices._quote import SharedCache, to_base_units
from y.prices._rpc import BlockRef, state, unavailable


@dataclass(frozen=True)
class Estimate:
    outputs: tuple[QuoteAsset, ...]
    value: Decimal
    steps: tuple[QuoteStep, ...]
    prices: tuple[PriceStep, ...]
    used: frozenset[str]


@dataclass(frozen=True)
class _Node:
    asset: QuoteAsset
    steps: tuple[QuoteStep, ...]
    visited: frozenset[str]
    used: frozenset[str]
    redemption: Estimate | None = None
    examined: bool = False


@dataclass
class SearchContext:
    """One request's failed transitions and exact native swap observations."""

    rejected: set[tuple[str, str, str]] = field(default_factory=set)
    rejected_redemptions: set[str] = field(default_factory=set)
    swaps: dict[tuple[str, str, str, int], QuoteStep] = field(default_factory=dict)


def priced_steps(steps: tuple[QuoteStep, ...], value: Decimal) -> tuple[PriceStep, ...]:
    """Attach the value of this one route branch to its input quantities."""
    return tuple(
        PriceStep(
            step.input.token,
            UsdPrice(value / step.input.readable),
            f"{step.protocol} {step.contract} via {step.method}",
        )
        for step in steps
    )


class QuoteService:
    """Own caches, never mutate cached paths or pool collections."""

    def __init__(self) -> None:
        self.market_cache: SharedCache[tuple[Market, ...]] = SharedCache(4096, immutable=True)
        self.result_cache: SharedCache[PriceResult | None] = SharedCache(2048)

    async def markets(self, token: str, block: BlockRef, skip_cache: bool) -> tuple[Market, ...]:
        return await self.market_cache.get(
            (block.chain, block.hash, token), lambda: discover(token, block)
        )

    async def usd(self, token: str, block: BlockRef) -> PriceResult | None:
        """Use historical USD feeds for terminal assets, including stablecoins."""
        from y import convert
        from y.prices import band, chainlink

        terminal = token in {address(t) for t in (*STABLECOINS, EEE_ADDRESS, WRAPPED_GAS_COIN)}
        if not terminal:
            return None
        checksum = await convert.to_address_async(token)
        oracle: Any
        for name, oracle in (("Chainlink", chainlink), ("Band", band)):
            if not oracle:
                continue
            try:
                price = await oracle.get_price(checksum, block, sync=False)
            except Exception as exc:
                if not unavailable(exc):
                    raise
                continue
            if valid_price(price):
                return PriceResult(
                    UsdPrice(float(price)),
                    [
                        PriceStep(
                            token, UsdPrice(float(price)), f"{name} historical USD for {token}"
                        )
                    ],
                )
        return None

    @stuck_coro_debugger
    async def estimate(
        self,
        asset: QuoteAsset,
        block: BlockRef,
        ignored: frozenset[str],
        ancestors: frozenset[str],
        skip_cache: bool,
        require_trade: bool = True,
        first_markets: tuple[str, ...] = (),
        swaps_left: int = 11,
        search: SearchContext | None = None,
    ) -> Estimate | None:
        if search is None:
            search = SearchContext()
        if asset.token in ancestors:
            return None
        if not require_trade:
            price = await self.usd(asset.token, block)
            if price is not None:
                return Estimate(
                    (asset,),
                    asset.readable * Decimal(str(float(price))),
                    (),
                    tuple(price.path),
                    ignored,
                )
        # Alternative quotes have independent pool state. Only the selected
        # alternative's exclusions propagate to the next redemption output.
        direct = await self.route(
            asset, block, ignored, ancestors, skip_cache, first_markets, swaps_left, search
        )
        redemption = await self.redeem(
            asset, block, ignored, ancestors, skip_cache, swaps_left, search
        )
        if redemption is not None and (direct is None or redemption.value > direct.value):
            return redemption
        return direct

    @stuck_coro_debugger
    async def redeem(
        self,
        asset: QuoteAsset,
        block: BlockRef,
        ignored: frozenset[str],
        ancestors: frozenset[str],
        skip_cache: bool,
        swaps_left: int,
        search: SearchContext,
    ) -> Estimate | None:
        from y.prices._redemptions import redeem

        if (
            asset.token in ignored
            or asset.token in search.rejected_redemptions
            or len(ancestors) >= 32
        ):
            return None
        try:
            redemption = await redeem(asset, block, ignored)
        except Exception as exc:
            if not unavailable(exc):
                raise
            search.rejected_redemptions.add(asset.token)
            return None
        if redemption is None:
            search.rejected_redemptions.add(asset.token)
            return None
        step, changed_pools = redemption
        used = ignored | frozenset(changed_pools) | {step.contract}
        outputs: dict[str, QuoteAsset] = {}
        for output in step.outputs:
            if output.amount:
                existing = outputs.get(output.token)
                outputs[output.token] = replace(
                    output, amount=output.amount + (existing.amount if existing else 0)
                )
        if not outputs:
            search.rejected_redemptions.add(asset.token)
            return None
        total = Decimal(0)
        steps = [replace(step, outputs=tuple(outputs[t] for t in sorted(outputs)))]
        prices: list[PriceStep] = []
        final_outputs: list[QuoteAsset] = []
        for token in sorted(outputs):
            child = await self.estimate(
                outputs[token],
                block,
                used,
                ancestors | {asset.token},
                skip_cache,
                require_trade=False,
                swaps_left=swaps_left,
                search=search,
            )
            if child is None:
                search.rejected_redemptions.add(asset.token)
                return None
            total += child.value
            steps.extend(child.steps)
            prices.extend(child.prices)
            final_outputs.extend(child.outputs)
            used = child.used
        return Estimate(
            aggregate(final_outputs),
            total,
            tuple(steps),
            (*priced_steps((step,), total), *prices),
            used,
        )

    @stuck_coro_debugger
    async def route(
        self,
        asset: QuoteAsset,
        block: BlockRef,
        ignored: frozenset[str],
        ancestors: frozenset[str],
        skip_cache: bool,
        first_markets: tuple[str, ...],
        swaps_left: int,
        search: SearchContext,
    ) -> Estimate | None:
        # Local traversal state never resets the request's rejected transitions.
        attempted: set[tuple[str, str, str]] = set()
        stack = [_Node(asset, (), ancestors | {asset.token}, ignored)]

        def select(candidate: Estimate) -> Estimate:
            # All candidates include the same input prefix. Each wrapper gets
            # the better complete exit, with direct sale winning equal values.
            for parent in reversed(stack):
                if parent.redemption is not None and parent.redemption.value > candidate.value:
                    candidate = parent.redemption
            return candidate

        while stack:
            node = stack[-1]
            if node.steps and not node.examined:
                price = await self.usd(node.asset.token, block)
                if price is not None:
                    value = node.asset.readable * Decimal(str(float(price)))
                    return select(
                        Estimate(
                            (node.asset,),
                            value,
                            node.steps,
                            (*priced_steps(node.steps, value), *price.path),
                            node.used,
                        )
                    )
                redemption = await self.redeem(
                    node.asset,
                    block,
                    node.used,
                    node.visited - {node.asset.token},
                    skip_cache,
                    swaps_left - len(node.steps),
                    search,
                )
                if redemption is not None:
                    redemption = replace(
                        redemption,
                        steps=(*node.steps, *redemption.steps),
                        prices=(*priced_steps(node.steps, redemption.value), *redemption.prices),
                    )
                node = replace(node, redemption=redemption, examined=True)
                stack[-1] = node
            selected = False
            if len(node.steps) < swaps_left:
                markets = await self.markets(node.asset.token, block, skip_cache)
                for market in markets:
                    if market.pool in node.used:
                        continue
                    if (
                        not node.steps
                        and first_markets
                        and not any(
                            key in (market.protocol, market.router, market.factory)
                            for key in first_markets
                        )
                    ):
                        continue
                    for output in sorted(market.tokens):
                        key = (market.pool, node.asset.token, output)
                        if output in node.visited or key in attempted or key in search.rejected:
                            continue
                        attempted.add(key)
                        step = await self.swap(market, node.asset, output, block, search)
                        if step is None:
                            continue
                        stack.append(
                            _Node(
                                step.outputs[0],
                                (*node.steps, step),
                                node.visited | {output},
                                node.used | {market.pool},
                            )
                        )
                        selected = True
                        break
                    if selected:
                        break
            if not selected:
                if node.redemption is not None:
                    return select(node.redemption)
                stack.pop()
                if node.steps:
                    entering = node.steps[-1]
                    search.rejected.add((entering.contract, entering.input.token, node.asset.token))
        return await self.explicit(
            asset, block, ignored, ancestors, skip_cache, first_markets, search
        )

    @stuck_coro_debugger
    async def swap(
        self,
        market: Market,
        asset: QuoteAsset,
        output: str,
        block: BlockRef,
        search: SearchContext,
    ) -> QuoteStep | None:
        edge = (market.pool, asset.token, output)
        key = (*edge, asset.amount)
        # Explicit registered routes can reuse a validated prefix even when
        # automatic traversal reached its swap ceiling. No native retry occurs.
        if key in search.swaps:
            return search.swaps[key]
        if edge in search.rejected:
            return None
        try:
            step = await swap(market, asset, output, block)
        except Exception as exc:
            if not unavailable(exc):
                raise
            step = None
        if step is None:
            search.rejected.add(edge)
        else:
            search.swaps[key] = step
        return step

    async def explicit(
        self,
        asset: QuoteAsset,
        block: BlockRef,
        ignored: frozenset[str],
        ancestors: frozenset[str],
        skip_cache: bool,
        first_markets: tuple[str, ...],
        search: SearchContext,
    ) -> Estimate | None:
        """Retain registered protocol routes without enumerating pool combinations."""
        from y.prices.dex.uniswap import uniswap_multiplexer

        router: Any
        for router in sorted(uniswap_multiplexer.v2_routers.values(), key=address):
            if (
                first_markets
                and address(router) not in first_markets
                and "Uniswap V2" not in first_markets
            ):
                continue
            paths = router.special_paths
            path = next(
                (tuple(map(address, p)) for t, p in paths.items() if address(t) == asset.token), ()
            )
            if (
                not path
                or path[0] != asset.token
                or len(set(path)) != len(path)
                or set(path) & ancestors
            ):
                continue
            current, used, steps = asset, ignored, []
            for output in path[1:]:
                step = None
                for market in await self.markets(current.token, block, skip_cache):
                    if (
                        market.router != address(router)
                        or market.pool in used
                        or output not in market.tokens
                    ):
                        continue
                    step = await self.swap(market, current, output, block, search)
                    if step is not None:
                        used = used | {market.pool}
                        break
                if step is None:
                    break
                steps.append(step)
                current = step.outputs[0]
            else:
                price = await self.usd(current.token, block)
                if price is not None:
                    value = current.readable * Decimal(str(float(price)))
                    return Estimate(
                        (current,),
                        value,
                        tuple(steps),
                        (*priced_steps(tuple(steps), value), *price.path),
                        used,
                    )
        return None

    async def price(
        self,
        token: str,
        block: BlockRef,
        amount: int | Decimal | None,
        *,
        ignored: frozenset[str] = frozenset(),
        dependencies: tuple[tuple[str, int], ...] = (),
        skip_cache: bool = False,
        first_markets: tuple[str, ...] = (),
    ) -> PriceResult | None:
        token = address(token)
        decimals = (
            18
            if token == address(EEE_ADDRESS)
            else int(await state(token, "decimals()(uint8)", block))
        )
        asset = QuoteAsset(
            token, to_base_units(1 if amount is None else amount, decimals), decimals
        )
        key = (
            block.chain,
            block.hash,
            token,
            asset.amount,
            "spot" if amount is None else "sale",
            tuple(sorted(ignored)),
            dependencies,
            first_markets,
        )

        async def calculate() -> PriceResult | None:
            with localcontext() as context:
                context.prec = 100
                estimate = await self.estimate(
                    asset,
                    block,
                    ignored,
                    frozenset(address(t) for t, _ in dependencies),
                    skip_cache,
                    first_markets=first_markets,
                )
                if estimate is None:
                    return None
                if not valid_price(estimate.value / asset.readable):
                    return None
                price = UsdPrice(estimate.value / asset.readable)
                paths = [
                    PriceStep(
                        token,
                        price,
                        (
                            "Liquidity-based sale estimate"
                            if amount is not None
                            else "Liquidity-based price estimate"
                        ),
                    )
                ]
                paths.extend(replace(step) for step in estimate.prices)
                details = (
                    QuoteDetails(
                        asset,
                        estimate.outputs,
                        estimate.value,
                        block.number,
                        block.hash,
                        estimate.steps,
                    )
                    if amount is not None
                    else None
                )
                return PriceResult(price, paths, details)

        result = await self.result_cache.get(key, calculate, skip_cache=skip_cache)
        await block.verify()
        return result


def aggregate(assets: list[QuoteAsset]) -> tuple[QuoteAsset, ...]:
    outputs: dict[str, QuoteAsset] = {}
    for asset in assets:
        previous = outputs.get(asset.token)
        outputs[asset.token] = replace(
            asset, amount=asset.amount + (previous.amount if previous else 0)
        )
    return tuple(outputs[token] for token in sorted(outputs))


@lru_cache(maxsize=1)
def quote_service() -> QuoteService:
    return QuoteService()


@stuck_coro_debugger
async def liquidity_price(
    token: str,
    block: int | None,
    *,
    amount: int | Decimal | None = None,
    ignore_pools: tuple[object, ...] = (),
    skip_cache: bool = False,
    first_markets: tuple[str, ...] = (),
) -> PriceResult | None:
    from y.prices.magic import _price_request

    resolved = await BlockRef.resolve(block)
    dependencies = tuple(
        d for d in _price_request.get().dependencies if address(d[0]) != address(token)
    )
    return await quote_service().price(
        token,
        resolved,
        amount,
        ignored=frozenset(map(address, ignore_pools)),
        dependencies=dependencies,
        skip_cache=skip_cache,
        first_markets=first_markets,
    )
