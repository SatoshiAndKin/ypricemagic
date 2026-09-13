"""Capture periodic allocations for the centrally selected memory workload."""

import os
from pathlib import Path
import threading
import tomllib
import tracemalloc

import pytest

from profile_state import sample


def main() -> int:
    config = tomllib.loads(Path("pyproject.toml").read_text())
    directory = Path(os.environ["VALIDATION_REPORT"])
    tracemalloc.start()
    stop = threading.Event()
    sampler = threading.Thread(target=sample, args=(directory, stop), daemon=True)
    sampler.start()
    try:
        return int(pytest.main(config["tool"]["validation"]["memory_tests"]))
    finally:
        stop.set()
        sampler.join()


if __name__ == "__main__":
    raise SystemExit(main())
