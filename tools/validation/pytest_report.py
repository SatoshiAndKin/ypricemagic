"""Stream scalar pytest outcomes and phase measurements without retaining Items."""

import asyncio
import faulthandler
import json
import os
import resource
import signal
import sys
import time
import tracemalloc
from pathlib import Path
from typing import Any


class Report:
    def __init__(self, directory: Path, allocations: bool) -> None:
        self.directory = directory
        self.started = time.monotonic()
        self.stream = (directory / "pytest-events.jsonl").open("w")
        self.counts: dict[str, int] = {}
        if allocations:
            tracemalloc.start()

    def pytest_sessionstart(self, session: Any) -> None:
        import tomllib

        faulthandler.register(signal.SIGUSR1, all_threads=True)
        config = tomllib.loads(Path("pyproject.toml").read_text())
        if "mypyc" in config.get("tool", {}):
            from check_compiled import main

            main()
        self.event("sessionstart")

    def event(self, phase: str, **extra: Any) -> None:
        try:
            tasks = len(asyncio.all_tasks(asyncio.get_event_loop()))
        except RuntimeError:
            tasks = 0
        record = {
            "phase": phase,
            "elapsed_seconds": time.monotonic() - self.started,
            "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            "live_tasks": tasks,
            **extra,
        }
        caches = {}
        routing = sys.modules.get("y.prices._routing")
        rpc = sys.modules.get("y.prices._rpc")
        routing_info = getattr(getattr(routing, "quote_service", None), "cache_info", None)
        if routing is not None and routing_info is not None and routing_info().currsize:
            service = routing.quote_service()
            for name in ("market_cache", "result_cache"):
                cache = getattr(service, name)
                caches[name] = {"values": len(cache.values), "flights": len(cache.flights)}
        state_info = getattr(getattr(rpc, "state_cache", None), "cache_info", None)
        if rpc is not None and state_info is not None and state_info().currsize:
            cache = rpc.state_cache()
            caches["state_cache"] = {"values": len(cache.values), "flights": len(cache.flights)}
        record["cache_occupancy"] = caches
        dank = sys.modules.get("dank_mids")
        instances = getattr(dank, "instances", None)
        if instances is not None:
            controllers = [controller for group in instances.values() for controller in group]
            # Match AuditClient.counts: IDs start at -1. These are logical calls
            # and generated batches, not a measurement of HTTP wire requests.
            record["logical_rpc_counts"] = {
                name: sum(getattr(controller, name).latest + 1 for controller in controllers)
                for name in ("call_uid", "multicall_uid", "request_uid", "jsonrpc_batch_uid")
            }
        if tracemalloc.is_tracing():
            record["python_current_bytes"], record["python_peak_bytes"] = (
                tracemalloc.get_traced_memory()
            )
        self.stream.write(json.dumps(record) + "\n")
        self.stream.flush()

    def pytest_collection_finish(self, session: Any) -> None:
        from profile_state import capture

        capture(self.directory, "collection")
        self.event("collection", count=len(session.items))

    def pytest_runtest_logreport(self, report: Any) -> None:
        key = report.when + ":" + report.outcome
        self.counts[key] = self.counts.get(key, 0) + 1
        # Longrepr contains rendered strings, not traceback objects or fixtures.
        self.event(
            report.when,
            test=report.nodeid,
            outcome=report.outcome,
            duration=report.duration,
            error=str(report.longrepr) if report.failed else None,
            error_message=(
                str(
                    getattr(getattr(report.longrepr, "reprcrash", None), "message", report.longrepr)
                )
                if report.failed
                else None
            ),
        )

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        from profile_state import capture

        capture(self.directory, "sessionfinish")
        self.event("sessionfinish", exit_code=int(exitstatus), counts=self.counts)
        (self.directory / "pytest-summary.json").write_text(
            json.dumps(
                {
                    "exit_code": int(exitstatus),
                    "counts": self.counts,
                    "collected": session.testscollected,
                },
                indent=2,
            )
            + "\n"
        )
        self.stream.close()


def pytest_configure(config: Any) -> None:
    if (directory := os.environ.get("VALIDATION_REPORT")) and str(config.rootdir) == "/work":
        config.pluginmanager.register(
            Report(Path(directory), os.environ.get("VALIDATION_ALLOCATIONS") == "1"),
            "validation-report-writer",
        )
