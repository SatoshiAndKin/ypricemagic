"""Fixed-block public pricing workload; preserve exact results for comparison."""

import argparse
import asyncio
from dataclasses import asdict
import gc
import json
import os
from pathlib import Path
import resource
from time import perf_counter
import tracemalloc
from typing import Any

from common import write_json
from profile_state import capture


async def main(allocations: bool) -> None:
    from y.audit import AuditClient
    from y.prices.magic import get_price
    from y.prices._routing import quote_service
    from y.prices._rpc import state_cache

    lookup: Any = get_price
    token = "0x6B3595068778DD592e39A122f4f5a5cF09C90fE2"
    block = 18_000_000
    report = Path(os.environ["VALIDATION_REPORT"])
    client = AuditClient()
    gc.collect()
    if allocations:
        tracemalloc.start()
    started = perf_counter()
    capture(report, "before")
    complete = False
    calls = 0
    with (report / "public-prices.jsonl").open("w") as stream:

        async def price(phase: str, number: int, amount: int) -> Any:
            nonlocal calls
            begin = perf_counter()
            calls += 1
            row: dict[str, Any] = {
                "phase": phase,
                "token": token,
                "block": number,
                "amount": amount,
            }
            try:
                result = await lookup(token, number, amount=amount, sync=False)
                assert result is not None and result.quote is not None
                row["result"] = asdict(result)
                return result
            except BaseException as exc:
                row["error"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                row.update(
                    elapsed_seconds=perf_counter() - begin, logical_rpc_counts=client.counts()
                )
                stream.write(json.dumps(row, default=str) + "\n")
                stream.flush()

        try:
            first = await price("cold", block, 1)
            await price("warm", block, 2)
            repeated = await price("repeated_amount", block, 1)
            assert asdict(first) == asdict(repeated)
            assert first.path is not repeated.path
            del first, repeated
            results = await asyncio.gather(*(price("concurrent", block, 3) for _ in range(64)))
            assert len({id(result.path) for result in results}) == 64
            assert all(asdict(result) == asdict(results[0]) for result in results)
            del results
            for index in range(32):
                await price("historical", block - index - 1, 1)
            complete = True
        finally:
            gc.collect()
            capture(report, "after")
            current, peak = tracemalloc.get_traced_memory()
            service = quote_service()
            write_json(
                report / "public-summary.json",
                {
                    "complete": complete,
                    "calls": calls,
                    "elapsed_seconds": perf_counter() - started,
                    "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                    "live_tasks": len(asyncio.all_tasks()),
                    "logical_rpc_counts": client.counts(),
                    "cache_entries": {
                        "markets": len(service.market_cache.values),
                        "results": len(service.result_cache.values),
                        "state": len(state_cache().values),
                    },
                    "python_retained_bytes": current if allocations else None,
                    "python_peak_bytes": peak if allocations else None,
                    "profiler": "tracemalloc; exclude timings" if allocations else None,
                },
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allocations", action="store_true")
    asyncio.get_event_loop().run_until_complete(main(parser.parse_args().allocations))
