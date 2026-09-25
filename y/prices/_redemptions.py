"""Immediate wallet-independent redemptions with explicit version contracts.

Unsupported versions and strategy-dependent or delayed exits return no quote.
See docs/amount-quotes.rst for the support and limit matrix.
"""

from collections.abc import AsyncGenerator
from contextlib import aclosing
from math import isqrt

from brownie import ZERO_ADDRESS
from eth_abi.abi import encode

from y._decorators import stuck_coro_debugger
from y.constants import EEE_ADDRESS, WRAPPED_GAS_COIN
from y.datatypes import QuoteAsset, QuoteStep
from y.exceptions import NonStandardERC20
from y.prices._markets import address
from y.prices._rpc import BlockRef, optional_read, read, unavailable


async def redeem(
    asset: QuoteAsset, block: BlockRef, ignored: frozenset[str]
) -> AsyncGenerator[tuple[QuoteStep, tuple[str, ...]], None]:
    """Yield lazy exits and close the adapter on selection or cancellation."""
    async with aclosing(_redeem_candidates(asset, block, ignored)) as candidates:
        while (candidate := await _next_redemption(candidates)) is not None:
            yield candidate


@stuck_coro_debugger
async def _next_redemption(
    candidates: AsyncGenerator[tuple[QuoteStep, tuple[str, ...]], None],
) -> tuple[QuoteStep, tuple[str, ...]] | None:
    # Decorate the pending read, not the generator: the upstream generator
    # decorator does not forward aclose to its wrapped iterator.
    return await anext(candidates, None)


async def _redeem_candidates(
    asset: QuoteAsset, block: BlockRef, ignored: frozenset[str]
) -> AsyncGenerator[tuple[QuoteStep, tuple[str, ...]], None]:
    token, shares = asset.token, asset.amount
    if token in ignored:
        return

    async def output(underlying: str, amount: int) -> QuoteAsset:
        underlying = address(underlying)
        decimals = (
            18
            if underlying == address(EEE_ADDRESS)
            else await read(underlying, "decimals()(uint8)", block)
        )
        if decimals is None:
            raise NonStandardERC20(underlying, "missing decimals")
        return QuoteAsset(underlying, amount, int(decimals))

    async def one(
        protocol: str, underlying: str, amount: int, method: str, fees: str, limits: str
    ) -> tuple[QuoteStep, tuple[str, ...]] | None:
        if amount <= 0:
            return None
        return (
            QuoteStep(
                "redemption",
                protocol,
                token,
                asset,
                (await output(underlying, amount),),
                method,
                fees,
                limits,
            ),
            (),
        )

    if token in (address(EEE_ADDRESS), address(WRAPPED_GAS_COIN)):
        native = token == address(EEE_ADDRESS)
        candidate = await one(
            "Wrapped native asset",
            str(WRAPPED_GAS_COIN) if native else str(EEE_ADDRESS),
            shares,
            "deposit()" if native else "withdraw(uint256)",
            "none",
            "holder balance unverified",
        )
        if candidate is not None:
            yield candidate
        return

    if block.chain == 1 and token == "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0":
        amount = int(await read(token, "getStETHByWstETH(uint256)(uint256)", block, shares))
        candidate = await one(
            "Lido wstETH",
            "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",
            amount,
            "unwrap(uint256) / getStETHByWstETH(uint256)",
            "none",
            "immediate stETH output; ETH exit is not modeled",
        )
        if candidate is not None:
            yield candidate
        return

    underlying = await optional_read(token, "asset()(address)", block)
    if underlying and address(underlying) != address(ZERO_ADDRESS):
        # ERC4626 previews include fees but deliberately exclude holder/global
        # limits. A missing/reverted preview is never replaced by accounting NAV.
        amount = await optional_read(token, "previewRedeem(uint256)(uint256)", block, shares)
        if amount is None:
            return
        candidate = await one(
            "ERC4626",
            underlying,
            int(amount),
            "previewRedeem(uint256)",
            "withdrawal fees included in previewRedeem",
            "preview excludes limits; maxRedeem and holder eligibility unverified",
        )
        if candidate is not None:
            yield candidate
        return

    version = await optional_read(token, "apiVersion()(string)", block)
    if version in ("0.4.3", "0.4.4", "0.4.5", "0.4.6"):
        underlying = await read(token, "token()(address)", block)
        supply = int(await read(token, "totalSupply()(uint256)", block))
        if not supply or shares > supply:
            return
        assets = int(await read(token, "totalAssets()(uint256)", block))
        profit = int(await read(token, "lockedProfit()(uint256)", block))
        degradation = int(await read(token, "lockedProfitDegradation()(uint256)", block))
        report = int(await read(token, "lastReport()(uint256)", block))
        ratio = (block.timestamp - report) * degradation
        locked = profit - profit * ratio // 10**18 if ratio < 10**18 else 0
        amount = shares * (assets - locked) // supply
        idle = await optional_read(token, "totalIdle()(uint256)", block)
        if idle is None:  # 0.4.3-0.4.5 read idle from the token balance.
            idle = await read(underlying, "balanceOf(address)(uint256)", block, token)
        if amount > int(idle):
            return  # Strategy withdrawals can realize unmodeled losses.
        candidate = await one(
            f"Yearn V2 {version}",
            underlying,
            amount,
            "withdraw(uint256) idle-liquidity share value",
            "no withdrawal fee for this idle-only exit",
            f"output <= idle assets ({idle}); holder balance unverified",
        )
        if candidate is not None:
            yield candidate
        return

    underlying = await optional_read(token, "UNDERLYING_ASSET_ADDRESS()(address)", block)
    if underlying:
        from y.prices.lending.aave import v2_pools, v3_pools

        pool = address(await read(token, "POOL()(address)", block))
        versions = {address(p): 2 for p in v2_pools} | {address(p): 3 for p in v3_pools}
        if pool not in versions or pool in ignored:
            return
        config = int(await read(pool, "getConfiguration(address)(uint256)", block, underlying))
        if not (config >> 56 & 1) or (versions[pool] == 3 and config >> 60 & 1):
            return
        if versions[pool] == 2 and await read(pool, "paused()(bool)", block):
            return
        cash = int(await read(underlying, "balanceOf(address)(uint256)", block, token))
        if shares > cash:
            return
        candidate = await one(
            f"Aave V{versions[pool]}",
            underlying,
            shares,
            "withdraw(address,uint256,address)",
            "none",
            f"active, unpaused reserve; cash={cash}; collateral and holder eligibility unverified",
        )
        if candidate is not None:
            yield candidate
        return

    if await optional_read(token, "isCToken()(bool)", block):
        comptroller = await read(token, "comptroller()(address)", block)
        if block.chain != 1 or address(comptroller) != "0x3d9819210a31b4961b30ef54be2aed79b9c9cd3b":
            return
        underlying = await optional_read(token, "underlying()(address)", block) or EEE_ADDRESS
        rate = int(await read(token, "exchangeRateCurrent()(uint256)", block))
        amount = shares * rate // 10**18
        cash = int(await read(token, "getCash()(uint256)", block))
        if amount > cash:
            return
        candidate = await one(
            "Compound V2 cToken",
            underlying,
            amount,
            "redeem(uint256) / exchangeRateCurrent()",
            "none in Compound V2",
            f"cash={cash}; comptroller and holder eligibility unverified",
        )
        if candidate is not None:
            yield candidate
        return

    lp = await optional_read(token, "lp_token()(address)", block)
    if lp and address(lp) != address(ZERO_ADDRESS):
        from y.contracts import Contract

        contract = await Contract.coroutine(token)
        # Restrict the one-for-one model to fungible Curve liquidity gauges.
        name = contract._build["contractName"]
        if "LiquidityGauge" not in name or not hasattr(contract, "withdraw"):
            return
        cash = int(await read(lp, "balanceOf(address)(uint256)", block, token))
        if shares > cash:
            return
        candidate = await one(
            f"Curve {name}",
            lp,
            shares,
            "withdraw(uint256)",
            "none",
            f"LP backing={cash}; holder balance unverified",
        )
        if candidate is not None:
            yield candidate
        return

    operator = await optional_read(token, "operator()(address)", block)
    if (
        block.chain == 1
        and operator
        and address(operator) == "0xf403c135812408bfbe8713b5a23a04b3d48aae31"
    ):
        if address(operator) in ignored:
            return
        length = int(await read(operator, "poolLength()(uint256)", block))
        for index in range(length):
            lp, deposit, gauge, _, _, shutdown = await read(
                operator,
                "poolInfo(uint256)(address,address,address,address,address,bool)",
                block,
                index,
            )
            if address(deposit) != token:
                continue
            if address(gauge) in ignored:
                return
            staker = await read(operator, "staker()(address)", block)
            if address(staker) in ignored:
                return
            backing = (
                int(await read(lp, "balanceOf(address)(uint256)", block, operator))
                if shutdown
                else int(await read(gauge, "balanceOf(address)(uint256)", block, staker))
                + int(await read(lp, "balanceOf(address)(uint256)", block, staker))
            )
            if shares > backing:
                return
            candidate = await one(
                "Convex Booster V1 deposit token",
                lp,
                shares,
                f"withdraw({index},uint256)",
                "none",
                f"LP backing={backing}; holder balance unverified",
            )
            if candidate is not None:
                yield candidate
            return

    # Only the established Uniswap/Sushi V2 burn contract is modeled here.
    factory = await optional_read(token, "factory()(address)", block)
    if (
        block.chain == 1
        and factory
        and address(factory)
        in (
            "0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f",
            "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac",
        )
    ):
        tokens = [await read(token, f"token{i}()(address)", block) for i in (0, 1)]
        supply = int(await read(token, "totalSupply()(uint256)", block))
        if not supply or shares >= supply:
            return
        fee_to = await read(factory, "feeTo()(address)", block)
        if address(fee_to) != address(ZERO_ADDRESS):
            k_last = int(await read(token, "kLast()(uint256)", block))
            if k_last:
                reserves = await read(token, "getReserves()(uint112,uint112,uint32)", block)
                root, last = isqrt(int(reserves[0]) * int(reserves[1])), isqrt(k_last)
                if root > last:
                    supply += supply * (root - last) // (root * 5 + last)
        balances = [int(await read(t, "balanceOf(address)(uint256)", block, token)) for t in tokens]
        outputs = tuple([await output(t, shares * b // supply) for t, b in zip(tokens, balances)])
        if any(not o.amount for o in outputs):
            return
        yield QuoteStep(
            "redemption",
            "Uniswap/Sushi V2 LP",
            token,
            asset,
            outputs,
            "burn(address)",
            "protocol liquidity fee included in diluted supply",
            "total supply checked; holder LP balance unverified",
        ), (token,)
        return

    pool_id = await optional_read(token, "getPoolId()(bytes32)", block)
    if pool_id:
        vault = await read(token, "getVault()(address)", block)
        if address(vault) in ignored:
            return
        tokens, balances, last_change = await read(
            vault, "getPoolTokens(bytes32)(address[],uint256[],uint256)", block, pool_id
        )
        # Proportional exit kind 1 for Weighted/Stable; kind 2 for ComposableStable.
        weights = await optional_read(token, "getNormalizedWeights()(uint256[])", block)
        amplification = await optional_read(
            token, "getAmplificationParameter()(uint256,bool,uint256)", block
        )
        if not weights and not amplification:
            return
        kind = 2 if token in tuple(map(address, tokens)) else 1
        collector = await read(vault, "getProtocolFeesCollector()(address)", block)
        fee = await read(collector, "getSwapFeePercentage()(uint256)", block)
        burned, amounts = await read(
            token,
            "queryExit(bytes32,address,address,uint256[],uint256,uint256,bytes)(uint256,uint256[])",
            block,
            pool_id,
            ZERO_ADDRESS,
            ZERO_ADDRESS,
            balances,
            last_change,
            fee,
            encode(["uint256", "uint256"], [kind, shares]),
        )
        if int(burned) != shares or len(amounts) != len(tokens):
            return
        outputs = tuple([await output(t, int(a)) for t, a in zip(tokens, amounts) if int(a)])
        yield QuoteStep(
            "redemption",
            "Balancer V2 proportional LP exit",
            token,
            asset,
            outputs,
            "queryExit",
            "fees included by pool queryExit",
            "native query limits; holder balance unverified",
        ), (token,)
        return

    from y.prices.stable_swap.curve import curve

    curve_pool = await curve.get_pool(token, sync=False) if curve else None
    if curve_pool is not None:
        pool_address = address(curve_pool)
        if pool_address in ignored:
            return
        from y.contracts import Contract

        contract = await Contract.coroutine(pool_address)
        if not hasattr(contract, "calc_withdraw_one_coin"):
            return
        from y.prices._markets import curve_pool_state

        snapshot = await curve_pool_state(pool_address, block)
        if snapshot is None:
            return
        coins = snapshot.tokens
        supply = int(await read(token, "totalSupply()(uint256)", block))
        if shares >= supply:
            return
        for coin in sorted(coins):
            try:
                amount = int(
                    await contract.calc_withdraw_one_coin.coroutine(
                        shares, coins.index(coin), block_identifier=block.identifier
                    )
                )
                if amount <= 0:
                    continue
                coin_output = await output(coin, amount)
            except Exception as exc:
                if not unavailable(exc):
                    raise
                continue
            yield QuoteStep(
                "redemption",
                "Curve single-coin LP withdrawal",
                pool_address,
                asset,
                (coin_output,),
                "calc_withdraw_one_coin",
                "withdrawal imbalance fees included",
                "LP supply and native quote limits checked; holder eligibility unverified",
            ), (pool_address,)
        return

    return
