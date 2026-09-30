"""Run the owning cache regressions against an installed native distribution."""

import argparse
import hashlib
import importlib.machinery
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import cachebox
import cachebox._core
import pytest
from common import write_json


class Reports:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.outcomes: list[dict[str, Any]] = []

    def pytest_runtest_logreport(self, report: Any) -> None:
        self.outcomes.append(
            {
                "test": report.nodeid,
                "phase": report.when,
                "outcome": report.outcome,
                "seconds": report.duration,
                "error": report.longreprtext if report.failed else None,
            }
        )
        write_json(self.directory / "cache-tests.json", self.outcomes)

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        write_json(
            self.directory / "cache-tests-summary.json",
            {"collected": session.testscollected, "exit_code": int(exitstatus)},
        )


def main(full: bool) -> int:
    directory = Path(os.environ["VALIDATION_REPORT"])
    subprocess.run([sys.executable, "-m", "pip", "check"], check=True)
    with (directory / "cache-test-dependencies.txt").open("w") as stream:
        subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], stdout=stream, check=True)
    core = Path(cachebox._core.__file__)
    assert any(str(core).endswith(suffix) for suffix in importlib.machinery.EXTENSION_SUFFIXES)
    write_json(
        directory / "cache-installed.json",
        {
            "version": cachebox.__version__,
            "core": str(core),
            "core_sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
            "python_sources": {
                str(path.relative_to(core.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted(core.parent.rglob("*.py"))
            },
        },
    )
    tests = directory / "cachebox-tests"
    shutil.copytree(Path("/work/python/tests"), tests / "python/tests")
    shutil.copyfile(Path("/work/pyproject.toml"), tests / "pyproject.toml")
    config = tomllib.loads((tests / "pyproject.toml").read_text())
    # The dependency owns the test selection and required asyncio plugin.
    # Application plugins do not belong in this isolated dependency test run.
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.chdir(tests)
    selected = [] if full else config["tool"]["validation"]["focused_tests"]
    return int(pytest.main(selected, plugins=[Reports(directory)]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true")
    raise SystemExit(main(parser.parse_args().full))
