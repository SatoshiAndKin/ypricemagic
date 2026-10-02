"""Run the centrally configured cold pool state regressions."""

import tomllib
from pathlib import Path

import pytest

if __name__ == "__main__":
    config = tomllib.loads(Path("pyproject.toml").read_text())
    raise SystemExit(pytest.main(config["tool"]["validation"]["cold_state_tests"]))
