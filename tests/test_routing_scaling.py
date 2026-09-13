"""Run the real cached Sushi graph through discovery and the greedy router.

Native state and quote RPCs are controlled. Timings measure Python scheduling
and cache reuse, not archive-node or production latency.
"""

import asyncio
import importlib
import json
import os
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from tests.test_amount_quotes import BLOCK
from tests.test_pricing_correctness import Ready, instance, run_async_test
from y.datatypes import PriceResult, QuoteAsset, QuoteStep, UsdPrice
from y.prices import _markets, _routing
from y.prices._routing import QuoteService
from y.prices._rpc import BlockRef


@run_async_test
async def test_cached_sushi_topology_bounds_tasks_and_shares_block_data(
    monkeypatch: Any, tmp_path: Any
) -> None:
    from y.prices.dex.uniswap.v2 import UniswapRouterV2

    data = json.loads((Path(__file__).parent / "data/sushi-mainnet-topology.json").read_text())
    rows = data["pools"]
    assert len(rows) == 4771
    weth = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    token = "0x6b3595068778dd592e39a122f4f5a5cf09c90fe2"
    active = peak = reads = quotes = 0

    class Pool:
        def __init__(self, row: Any) -> None:
            self.address = row[0].lower()
            self.tokens = tuple(t.lower() for t in row[1:3])
            self.__tokens__ = Ready(tuple(row[1:3]))

        def __str__(self) -> Any:
            return self.address

        async def deploy_block(self, **kwargs: Any) -> Any:
            return 1

    pools = [Pool(row) for row in rows]
    by_address = {pool.address: pool for pool in pools}
    router = instance(UniswapRouterV2)
    router.factory, router.address = data["factory"], "router"
    router._supports_factory_helper = False
    router.special_paths = {}
    monkeypatch.setattr(UniswapRouterV2, "__pools__", property(lambda _: Ready(pools)))
    # Discovery calls the existing all_pools_for and pools_by_token methods.
    multiplexer = SimpleNamespace(v2_routers={"sushi": router}, v3=None, v3_forks=[], v1=None)
    module = importlib.import_module("y.prices.dex.uniswap")
    monkeypatch.setattr(module, "uniswap_multiplexer", multiplexer)
    balancer = importlib.import_module("y.prices.dex.balancer")
    monkeypatch.setattr(
        balancer, "balancer_multiplexer", SimpleNamespace(__v1__=Ready(None), __v2__=Ready(None))
    )
    monkeypatch.setattr(importlib.import_module("y.prices.stable_swap.curve"), "curve", None)

    async def state(pool: Any, signature: Any, block: Any, *args: Any) -> Any:
        nonlocal active, peak, reads
        active += 1
        peak = max(peak, active)
        reads += 1
        try:
            await asyncio.sleep(0)
            # Controlled reserves favor gas-asset pairs. The topology itself is
            # the complete cached mainnet Sushi graph.
            reserve = 10**24 if weth in by_address[pool].tokens else 10**22
            return (reserve, reserve, 0)
        finally:
            active -= 1

    async def swap(pool: Any, asset: Any, output: Any, block: Any) -> Any:
        nonlocal quotes
        quotes += 1
        return QuoteStep(
            "swap",
            pool.protocol,
            pool.pool,
            asset,
            (QuoteAsset(output, asset.amount * 997 // 1000, 18),),
            "controlled native RPC",
            "0.3%",
            "controlled",
        )

    async def usd(address: Any, block: Any) -> Any:
        return PriceResult(UsdPrice(2000), []) if address == weth else None

    monkeypatch.setattr(_markets, "state", state)
    monkeypatch.setattr(_markets, "deployed", AsyncMock(return_value=True))
    monkeypatch.setattr(_routing, "state", AsyncMock(return_value=18))
    monkeypatch.setattr(_routing, "swap", swap)
    monkeypatch.setattr(BlockRef, "verify", AsyncMock())
    service = QuoteService()
    monkeypatch.setattr(service, "usd", usd)
    monkeypatch.setattr(service, "redeem", AsyncMock(return_value=None))
    durations = {}
    started = perf_counter()
    first = await service.price(token, BLOCK, 1)
    durations["cold_seconds"] = perf_counter() - started
    count = reads
    assert first is not None and first.quote is not None
    assert first.quote.total_usd == 1994
    assert count == sum(token in pool.tokens for pool in pools)
    assert peak <= 64 and active == 0
    assert quotes == 1

    for label, amount in (("warm_seconds", 2), ("repeated_amount_seconds", 1)):
        started = perf_counter()
        result = await service.price(token, BLOCK, amount)
        durations[label] = perf_counter() - started
        assert result is not None and result.quote is not None
        assert result.quote.total_usd == amount * 1994
    assert reads == count and quotes == 2
    started = perf_counter()
    results = await asyncio.gather(*(service.price(token, BLOCK, 3) for _ in range(64)))
    durations["concurrent_seconds"] = perf_counter() - started
    for result in results:
        assert result is not None and result.quote is not None
        assert result.quote.total_usd == 5982
    assert reads == count and quotes == 3
    assert not service.result_cache.flights
    report = dict(
        durations,
        pools=len(pools),
        input_pools=count,
        peak_operations=peak,
        liquidity_reads=reads,
        quote_calls=quotes,
        boundary="controlled native RPC; cached production Sushi topology",
    )
    # Turn over both caches with distinct canonical historical blocks. Never
    # clear a cache or restart the process to achieve bounded retained state.
    started = perf_counter()
    blocks = int(service.market_cache.values.maxsize) + 32
    for index in range(blocks):
        historical = BlockRef(
            BLOCK.chain,
            BLOCK.number - index - 1,
            f"0x{index + 1:064x}",
            BLOCK.timestamp - 12 * (index + 1),
        )
        result = await service.price(token, historical, 1)
        assert result is not None and result.quote is not None
        assert result.quote.total_usd == 1994
        assert result.quote.block_hash == historical.hash
        assert result.quote.steps[0].outputs[0].amount == 997 * 10**15
        assert len(service.market_cache.values) <= service.market_cache.values.maxsize
        assert len(service.result_cache.values) <= service.result_cache.values.maxsize
        assert not service.market_cache.flights and not service.result_cache.flights
    assert reads == count * (blocks + 1)
    assert quotes == blocks + 3
    assert peak <= 64 and active == 0
    report.update(
        historical_blocks=blocks,
        historical_seconds=perf_counter() - started,
        final_market_entries=len(service.market_cache.values),
        final_result_entries=len(service.result_cache.values),
        total_liquidity_reads=reads,
        total_quote_calls=quotes,
    )
    report_dir = Path(os.environ.get("VALIDATION_REPORT", str(tmp_path)))
    (report_dir / "scaling.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
