"""Verify every configured module, and save its extension path."""

import importlib
import os
import tomllib
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path

from common import write_json


def main() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text())
    modules = {}
    for source in config["tool"]["mypyc"]["files"]:
        name = source.removesuffix(".py").replace("/", ".")
        path = importlib.import_module(name).__file__
        assert path is not None and any(path.endswith(s) for s in EXTENSION_SUFFIXES), (name, path)
        modules[name] = path
    write_json(Path(os.environ["VALIDATION_REPORT"]) / "compiled-modules.json", modules)


if __name__ == "__main__":
    main()
