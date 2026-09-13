"""Run the same recorded Sushi workload against either pricing revision."""

import argparse
import gc
import importlib.util
import json
import os
from pathlib import Path
import resource
import tempfile
import tracemalloc
from time import perf_counter

from pytest import MonkeyPatch


def main(allocations: bool) -> None:
    spec = importlib.util.spec_from_file_location(
        "validation_scaling", "/runner/workloads/test_routing_scaling.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    gc.collect()
    if allocations:
        tracemalloc.start()
    started = perf_counter()
    with MonkeyPatch.context() as patch, tempfile.TemporaryDirectory() as temporary:
        module.test_cached_sushi_topology_bounds_tasks_and_shares_block_data(patch, Path(temporary))
    gc.collect()
    report = Path(os.environ["VALIDATION_REPORT"], "scaling.json")
    result = json.loads(report.read_text())
    current, peak = tracemalloc.get_traced_memory()
    result.update(
        elapsed_seconds=perf_counter() - started,
        rss_peak_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        python_retained_bytes=current if allocations else None,
        python_peak_bytes=peak if allocations else None,
        profiler="tracemalloc; exclude timings" if allocations else None,
    )
    report.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allocations", action="store_true")
    main(parser.parse_args().allocations)
