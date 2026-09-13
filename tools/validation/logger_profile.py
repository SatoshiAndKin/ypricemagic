"""Compare diagnostic retention without changing workload concurrency."""

import argparse
import asyncio
import gc
import json
import logging
import os
from pathlib import Path
import resource
import tracemalloc
from time import perf_counter
from weakref import ref


async def main(allocations: bool) -> None:
    from y.utils.logging import get_price_logger

    logger = logging.getLogger("y.prices")
    logger.setLevel(logging.DEBUG)
    gc.collect()
    if allocations:
        tracemalloc.start()
    initial, _ = tracemalloc.get_traced_memory()
    started = perf_counter()
    references = []
    tasks = []
    for block in range(10_000):
        price_logger = get_price_logger(
            "0x0000000000000000000000000000000000000101", block, start_task=True
        )
        references.append(ref(price_logger))
        if task := getattr(price_logger, "debug_task", None):
            tasks.append(ref(task))
        # Let each batch start its diagnostic tasks at the same request concurrency.
        if block % 100 == 0:
            await asyncio.sleep(0)
        price_logger.close()
    del price_logger, task
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    result = {
        "requests": len(references),
        "elapsed_seconds": perf_counter() - started,
        "retained_loggers": sum(r() is not None for r in references),
        "retained_diagnostic_tasks": sum(r() is not None for r in tasks),
        "live_tasks": len(asyncio.all_tasks()),
        "python_retained_bytes": current - initial if allocations else None,
        "python_peak_bytes": peak if allocations else None,
        "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "profiler": (
            "tracemalloc; exclude this run from timing comparisons" if allocations else None
        ),
    }
    Path(os.environ["VALIDATION_REPORT"], "logger-profile.json").write_text(
        json.dumps(result, indent=2) + "\n"
    )
    print(json.dumps(result))
    # Cleanup happens only after measurement; it is not a claimed memory fix.
    for reference in tasks:
        if task := reference():
            task.cancel()
    await asyncio.sleep(0)
    assert result["retained_loggers"] == 0
    assert result["retained_diagnostic_tasks"] == 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allocations", action="store_true")
    args = parser.parse_args()
    asyncio.get_event_loop().run_until_complete(main(args.allocations))
