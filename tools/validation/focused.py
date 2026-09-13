"""Run centrally declared focused pytest targets without changing full-suite settings."""

from pathlib import Path
import tomllib

import pytest

if __name__ == "__main__":
    config = tomllib.loads(Path("pyproject.toml").read_text())
    raise SystemExit(pytest.main(config["tool"]["validation"]["focused_tests"]))
