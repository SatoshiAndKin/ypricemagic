"""CLI imports preserve logging; explicit debugging enables diagnostics."""

import importlib
import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.test_amount_quotes import TOKEN


@pytest.fixture
def y_logger() -> Iterator[logging.Logger]:
    logger = logging.getLogger("y")
    level, handlers, propagate = logger.level, tuple(logger.handlers), logger.propagate
    try:
        yield logger
    finally:
        for handler in tuple(logger.handlers):
            if handler not in handlers:
                logger.removeHandler(handler)
                handler.close()
        logger.handlers[:] = handlers
        logger.setLevel(level)
        logger.propagate = propagate


@pytest.mark.parametrize("level", [logging.WARNING, logging.INFO, logging.DEBUG])
def test_audit_cli_preserves_configured_logging(
    monkeypatch: Any, y_logger: logging.Logger, tmp_path: Path, level: int
) -> None:
    y_logger.setLevel(level)
    handler = logging.NullHandler()
    y_logger.addHandler(handler)
    handlers = tuple(y_logger.handlers)

    # Execute the real module bodies even if another test already imported them.
    importlib.reload(importlib.import_module("y.prices.utils.debug"))
    cli = importlib.reload(importlib.import_module("y.cli"))
    assert y_logger.level == level
    assert tuple(y_logger.handlers) == handlers

    paths = tuple(tmp_path / name for name in ("manifest.json", "audit.json", "audit.csv"))
    calls: list[tuple[Path, Path, Path]] = []

    def run_manifest(manifest: Path, json_report: Path, csv_report: Path) -> int:
        calls.append((manifest, json_report, csv_report))
        return 2

    monkeypatch.setattr("y.audit.run_manifest", run_manifest)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ypricemagic",
            "audit-prices",
            str(paths[0]),
            "--json",
            str(paths[1]),
            "--csv",
            str(paths[2]),
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        cli.main()
    assert stopped.value.code == 2
    assert calls == [paths]
    assert y_logger.level == level
    assert tuple(y_logger.handlers) == handlers


@pytest.mark.parametrize("existing_handler", [False, True])
def test_explicit_price_debug_enables_logging_and_reuses_handler(
    monkeypatch: Any, y_logger: logging.Logger, existing_handler: bool
) -> None:
    debug = importlib.import_module("y.prices.utils.debug")
    y_logger.setLevel(logging.WARNING)
    y_logger.handlers.clear()
    y_logger.propagate = False
    if existing_handler:
        y_logger.addHandler(logging.NullHandler())
    handlers = tuple(y_logger.handlers)
    calls: list[tuple[str, int, bool]] = []

    def price(token: str, block: int, *, skip_cache: bool) -> float:
        assert y_logger.isEnabledFor(logging.DEBUG)
        calls.append((token, block, skip_cache))
        return 1.25

    monkeypatch.setattr(debug.y, "get_price", price)
    for _ in range(2):
        assert debug.debug_price(TOKEN, 18_000_000) == 1.25
    assert calls == [(TOKEN, 18_000_000, True), (TOKEN, 18_000_000, True)]
    assert y_logger.level == logging.DEBUG
    assert len(y_logger.handlers) == 1
    if existing_handler:
        assert tuple(y_logger.handlers) == handlers
    else:
        assert isinstance(y_logger.handlers[0], logging.StreamHandler)
