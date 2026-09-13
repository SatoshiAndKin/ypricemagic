"""Measure retained function fixtures at unchanged cooperative concurrency."""

import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    directory = Path("/tmp/cooperative-profile")
    directory.mkdir()
    (directory / "pytest.ini").write_text("""[pytest]
testpaths = workload.py
max_asyncio_tasks = 100
asyncio_task_timeout = 600
addopts = -p no:pytest_ethereum
""")
    (directory / "workload.py").write_text("""
import asyncio
import gc
import json
import os
from pathlib import Path
import resource
from time import perf_counter
from weakref import ref
import pytest

references = []
active = 0
peak = 0
started = perf_counter()

class Payload:
    def __init__(self):
        self.data = bytearray(128 * 1024)

@pytest.fixture
async def payload():
    value = Payload()
    references.append(ref(value))
    yield value

@pytest.mark.asyncio_cooperative
@pytest.mark.parametrize("index", range(4000))
async def test_work(index, payload):
    global active, peak
    active += 1
    peak = max(peak, active)
    await asyncio.sleep(0.001)
    assert len(payload.data) == 128 * 1024
    active -= 1

def test_retained_state():
    gc.collect()
    report = {
        "requests": len(references), "retained_fixtures": sum(r() is not None for r in references),
        "peak_concurrency": peak, "active": active,
        "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "elapsed_seconds": perf_counter() - started,
        "live_tasks": len(asyncio.all_tasks(asyncio.get_event_loop())),
    }
    Path(os.environ["VALIDATION_REPORT"], "cooperative-profile.json").write_text(json.dumps(report, indent=2) + "\\n")
    assert active == 0 and peak == 100
    assert report["retained_fixtures"] == 0
""")
    return subprocess.call([sys.executable, "-m", "pytest"], cwd=directory)


if __name__ == "__main__":
    raise SystemExit(main())
