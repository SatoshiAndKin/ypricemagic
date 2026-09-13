"""Optional allocation census; never run in unprofiled timing comparisons."""

from collections import Counter
import gc
from pathlib import Path
import tracemalloc

from common import write_json


def capture(directory: Path, phase: str) -> None:
    if not tracemalloc.is_tracing():
        return
    counts: Counter[str] = Counter()
    # Count classes of interest without retaining the objects in the report.
    for value in gc.get_objects():
        cls = type(value)
        if cls.__module__.startswith(("y.", "a_sync", "dank_mids", "pytest_asyncio_cooperative")):
            counts[f"{cls.__module__}.{cls.__qualname__}"] += 1
    snapshot = tracemalloc.take_snapshot()
    write_json(
        directory / f"allocations-{phase}.json",
        {
            "objects": dict(counts.most_common()),
            "top_allocations": [
                {"traceback": str(item.traceback), "bytes": item.size, "count": item.count}
                for item in snapshot.statistics("traceback")[:50]
            ],
        },
    )
