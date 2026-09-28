"""Run the centrally configured historical repair regressions."""

import tomllib
from pathlib import Path

import pytest

if __name__ == "__main__":
    config = tomllib.loads(Path("pyproject.toml").read_text())
    raise SystemExit(pytest.main(config["tool"]["validation"]["repair_tests"]))
