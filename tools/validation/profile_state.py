"""Optional allocation census; never run in unprofiled timing comparisons."""

import gc
import logging
import resource
import sys
import tracemalloc
from asyncio import Task
from collections import Counter
from collections.abc import Sized
from io import StringIO
from pathlib import Path
from threading import Event
from types import FunctionType
from typing import Any

from common import write_json


def original_function(value: Any) -> str:
    """Name the cache input through standard wrappers and Pony's callable wrapper."""
    seen = set()
    while id(value) not in seen:
        seen.add(id(value))
        wrapped = getattr(value, "__wrapped__", None)
        if (
            wrapped is None
            and isinstance(value, FunctionType)
            and value.__module__ == "pony.utils.utils"
            and value.__code__.co_name == "pony_wrapper"
        ):
            # Pony does not set __wrapped__ when it decorates a native callable.
            wrapped = next(
                (
                    cell.cell_contents
                    for name, cell in zip(value.__code__.co_freevars, value.__closure__ or ())
                    if name == "func"
                ),
                None,
            )
        if wrapped is None:
            break
        value = wrapped
    name = getattr(value, "__qualname__", type(value).__qualname__)
    return f"{value.__module__}.{name}"


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
    log_records: Counter[str] = Counter()
    property_state: Counter[str] = Counter()
    async_caches: list[dict[str, Any]] = []
    cachebox_caches: list[dict[str, Any]] = []
    disk_cache_type = getattr(sys.modules.get("y._db.common"), "_DiskCachedMixin", ())
    # Count classes of interest without retaining the objects in the report.
    for value in gc.get_objects():
        cls = type(value)
        module = cls.__module__
        if isinstance(module, str) and module.startswith(
            (
                "y.",
                "a_sync",
                "dank_mids",
                "evmspec",
                "pytest_asyncio_cooperative",
                "_asyncio",
                "logging",
                "_pytest.logging",
            )
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
        if module == "async_lru" and cls.__name__ == "_LRUCacheWrapper":
            # Inspect the installed cache owner, rather than infer ownership from
            # a completed task whose coroutine has already been released.
            entries = getattr(value, "_LRUCacheWrapper__cache")
            info = value.cache_info()
            wrapped = value.__wrapped__
            states: Counter[str] = Counter()
            results: Counter[str] = Counter()
            for entry in tuple(entries.values()):
                task = entry.task
                states["done" if task.done() else "pending"] += 1
                if task.done() and not task.cancelled():
                    result_type = type(task._result)
                    results[f"{result_type.__module__}.{result_type.__qualname__}"] += 1
            async_caches.append(
                {
                    "function": f"{wrapped.__module__}."
                    f"{getattr(wrapped, '__qualname__', type(wrapped).__qualname__)}",
                    "original_function": original_function(wrapped),
                    "hits": info.hits,
                    "misses": info.misses,
                    "maxsize": info.maxsize,
                    "entries": info.currsize,
                    "tasks": dict(states),
                    "result_types": dict(results),
                }
            )
        if (
            isinstance(value, FunctionType)
            and value.__code__.co_filename.endswith(
                ("/cachebox/utils.py", "/cachebox/_wrappers.py")
            )
            and value.__code__.co_name == "_wrapped"
        ):
            closure = {
                name: cell.cell_contents
                for name, cell in zip(value.__code__.co_freevars, value.__closure__ or ())
            }
            lock_owner = closure.get("locks", {})
            locks = getattr(lock_owner, "_entries", lock_owner)
            cache = closure.get("cache")
            cachebox_caches.append(
                {
                    "function": f"{value.__module__}.{value.__qualname__}",
                    "hits": closure.get("hits"),
                    "misses": closure.get("misses"),
                    "entries": len(cache) if isinstance(cache, Sized) else None,
                    "locks": len(locks),
                    "idle_locks": sum(lock.waiters == 0 for lock in tuple(locks.values())),
                    "exceptions": len(closure.get("exceptions", closure.get("pending_errors", {})))
                    + sum(
                        getattr(lock, "error", None) is not None for lock in tuple(locks.values())
                    ),
                }
            )
        if (
            module == "a_sync.async_property.cached"
            and cls.__name__ == "AsyncCachedPropertyInstanceState"
        ):
            property_state["instances"] += 1
            for attribute in ("cache", "locks", "tasks"):
                entries = getattr(value, attribute)
                property_state[attribute + "_entries"] += len(entries)
                for entry in entries.values():
                    if isinstance(entry, Task):
                        property_state[attribute + "_completed_tasks"] += entry.done()
                        property_state[attribute + "_pending_tasks"] += not entry.done()
        if isinstance(value, logging.LogRecord):
            log_records["records"] += 1
            log_records["with_exception_info"] += value.exc_info is not None
            log_records["with_exception_message"] += isinstance(value.msg, BaseException)
        if module == "_pytest.logging" and cls.__name__ == "LogCaptureHandler":
            records = getattr(value, "records", ())
            log_records["capture_handlers"] += 1
            log_records["captured_records"] += len(records)
            stream = getattr(value, "stream", None)
            if isinstance(stream, StringIO):
                # Count text without copying the capture buffer.
                log_records["captured_characters"] += stream.tell()
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
    pony = sys.modules.get("pony.orm.core")
    sql_cache = getattr(pony, "adapted_sql_cache", {})
    sql_cache_state = {
        "entries": len(sql_cache),
        "query_characters": sum(len(key[0]) for key in sql_cache),
        "adapted_query_characters": sum(len(value[0]) for value in sql_cache.values()),
    }
    current, peak = tracemalloc.get_traced_memory()
    snapshot = tracemalloc.take_snapshot()
    write_json(
        directory / f"allocations-{phase}.json",
        {
            "objects": dict(counts.most_common()),
            "tasks_by_coroutine": dict(tasks.most_common()),
            "historical_buffer_entries": dict(buffers.most_common()),
            "queued_database_operations": queued,
            "logging": dict(log_records),
            "cached_property_state": dict(property_state),
            "async_caches": sorted(async_caches, key=lambda row: row["entries"], reverse=True),
            "cachebox_caches": sorted(cachebox_caches, key=lambda row: row["locks"], reverse=True),
            "pony_adapted_sql_cache": sql_cache_state,
            "python_current_bytes": current,
            "python_peak_bytes": peak,
            "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "top_allocations": [
                {"traceback": str(item.traceback), "bytes": item.size, "count": item.count}
                for item in snapshot.statistics("traceback")[:50]
            ],
        },
    )
