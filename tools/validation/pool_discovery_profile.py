"""Isolate pool construction, token resolution, and index materialization."""

import argparse
import asyncio
import hashlib
import os
import resource
import time
import tracemalloc
from collections import Counter
from pathlib import Path
from typing import Any

import a_sync
from common import write_json

from y.audit import AuditClient
from y.prices.dex.uniswap.v2 import UniswapRouterV2, UniswapV2Pool


def memory() -> dict[str, Any]:
    current, peak = tracemalloc.get_traced_memory()
    return {
        "rss_current_bytes": int(Path("/proc/self/statm").read_text().split()[1])
        * os.sysconf("SC_PAGE_SIZE"),
        "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "python_current_bytes": current if tracemalloc.is_tracing() else None,
        "python_peak_bytes": peak if tracemalloc.is_tracing() else None,
    }


async def main(count: int, allocations: bool) -> None:
    report = Path(os.environ["VALIDATION_REPORT"])
    client = AuditClient()
    initial_rpc = client.counts()
    token0 = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    token1 = "0x6b175474e89094c44da98b954eedeac495271d0f"
    if allocations:
        tracemalloc.start()
    rows: list[dict[str, Any]] = []

    def begin(phase: str) -> float:
        write_json(report / "pool-discovery-active.json", {"phase": phase, **memory()})
        return time.perf_counter()

    def finish(phase: str, started: float) -> None:
        rows.append({"phase": phase, "elapsed_seconds": time.perf_counter() - started, **memory()})
        write_json(report / "pool-discovery-phases.json", rows)

    started = begin("construction")
    pools = [
        UniswapV2Pool(f"0x{2**128 + index:040x}", token0, token1, 18_000_000, asynchronous=True)
        for index in range(count)
    ]
    finish("construction", started)

    router: Any = object.__new__(UniswapRouterV2)
    a_sync.ASyncGenericBase.__init__(router)
    router.asynchronous = True
    router.address, router.label = "pool-memory-probe", "pool-memory-probe"
    router.pools = pools

    started = begin("index_all_tokens")
    index = await UniswapRouterV2.pools_by_token.get(router)
    assert len(index[token0]) == len(index[token1]) == count
    assert all(value == token1 for value in index[token0].values())
    assert all(value == token0 for value in index[token1].values())
    finish("index_all_tokens", started)

    started = begin("warm_independent_results")
    for _ in range(3):
        result = await router.all_pools_for(token0, sync=False)
        assert result == index[token0] and result is not index[token0]
        result.clear()
        assert len(index[token0]) == count
    finish("warm_independent_results", started)

    # Count owners after timing. Do not collect objects or expire cache timers.
    methods: Counter[str] = Counter()
    property_values = 0
    digest = hashlib.sha256()
    for number, pool in enumerate(pools):
        cache = getattr(pool, "__async_property__").cache
        property_values += len(cache)
        assert pool.address.lower() == f"0x{2**128 + number:040x}"
        assert cache["token0"] == token0 and cache["token1"] == token1
        digest.update(f"{pool.address.lower()}|{token0}|{token1}|18000000".encode())
        for value in vars(pool).values():
            cls = type(value)
            if cls.__module__ in ("a_sync.a_sync.property", "a_sync.a_sync.method"):
                methods[f"{cls.__module__}.{cls.__name__}"] += 1
    rpc = {name: value - initial_rpc.get(name, 0) for name, value in client.counts().items()}
    assert not any(rpc.values()), rpc
    write_json(
        report / "pool-discovery-summary.json",
        {
            "complete": True,
            "pools": count,
            "phases": rows,
            "property_values": property_values,
            "bound_methods": dict(methods),
            "scheduled_callbacks": len(getattr(asyncio.get_running_loop(), "_scheduled")),
            "logical_rpc_counts": rpc,
            "metadata_sha256": digest.hexdigest(),
            "profiler": "tracemalloc without allocation census" if allocations else None,
            "boundary": "synthetic seeded pool metadata; no reserve or discovery RPC",
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pools", type=int, default=524288)
    parser.add_argument("--allocations", action="store_true")
    args = parser.parse_args()
    asyncio.get_event_loop().run_until_complete(main(args.pools, args.allocations))
