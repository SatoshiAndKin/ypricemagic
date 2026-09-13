"""Optional allocation census; never run in unprofiled timing comparisons."""

from asyncio import Task
from collections import Counter
import gc
from pathlib import Path
import resource
import sys
from threading import Event
import tracemalloc

from common import write_json


def sample(directory: Path, stop: Event) -> None:
    """Keep allocation evidence if the profiled process cannot reach teardown."""
    index = 0
    while not stop.wait(30):
        try:
            capture(directory, f"pending-{index}")
        except Exception as error:
            write_json(directory / f"sample-error-{index}.json", {"error": repr(error)})
        index += 1


def capture(directory: Path, phase: str) -> None:
    if not tracemalloc.is_tracing():
        return
    counts: Counter[str] = Counter()
    buffers: Counter[str] = Counter()
    tasks: Counter[str] = Counter()
    disk_cache_type = getattr(sys.modules.get("y._db.common"), "_DiskCachedMixin", ())
    # Count classes of interest without retaining the objects in the report.
    for value in gc.get_objects():
        cls = type(value)
        module = cls.__module__
        if isinstance(module, str) and module.startswith(
            ("y.", "a_sync", "dank_mids", "pytest_asyncio_cooperative", "_asyncio")
        ):
            name = f"{module}.{cls.__qualname__}"
            counts[name] += 1
            if isinstance(value, disk_cache_type):
                # These are storage slots, not lazy cache properties.
                for attribute in ("_objects", "_checkpoints"):
                    entries = getattr(value, attribute, None)
                    if isinstance(entries, (list, dict)):
                        buffers[f"{name}.{attribute}"] += len(entries)
        if isinstance(value, Task):
            coro = value.get_coro()
            name = getattr(coro, "__qualname__", type(coro).__qualname__)
            tasks[f"{name}:{'done' if value.done() else 'pending'}"] += 1
    queued = {}
    for module_name, attribute in (
        ("y._db.utils.price", "set_price"),
        ("y._db.utils.token", "set_bucket"),
        ("y._db.utils.contract", "set_deploy_block"),
        ("y._db.decorators", "ydb_write_threads"),
        ("y._db.utils.contract", "_deploy_block_write_executor"),
    ):
        owner = getattr(sys.modules.get(module_name), attribute, None)
        queue = getattr(owner, "_work_queue", owner)
        if queue is not None:
            queued[f"{module_name}.{attribute}"] = queue.qsize()
    current, peak = tracemalloc.get_traced_memory()
    snapshot = tracemalloc.take_snapshot()
    write_json(
        directory / f"allocations-{phase}.json",
        {
            "objects": dict(counts.most_common()),
            "tasks_by_coroutine": dict(tasks.most_common()),
            "historical_buffer_entries": dict(buffers.most_common()),
            "queued_database_operations": queued,
            "python_current_bytes": current,
            "python_peak_bytes": peak,
            "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "top_allocations": [
                {"traceback": str(item.traceback), "bytes": item.size, "count": item.count}
                for item in snapshot.statistics("traceback")[:50]
            ],
        },
    )
