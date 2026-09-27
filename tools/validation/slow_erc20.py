"""Recheck recorded full-suite timeouts sequentially with the configured deadline."""

import asyncio
import os
import time
import tomllib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from common import write_json
from price_waits import sample


async def main(check: Callable[[str, int], Awaitable[None]]) -> int:
    from y.prices._rpc import BlockRef

    config = tomllib.loads(Path("pyproject.toml").read_text())
    deadline = config["tool"]["pytest"]["ini_options"]["asyncio_task_timeout"]
    directory = Path(os.environ["VALIDATION_REPORT"])
    sampler = asyncio.create_task(sample(directory, time.monotonic()))
    rows: list[dict[str, Any]] = []
    try:
        for case in config["tool"]["validation"]["slow_erc20_cases"]:
            token, number = case["token"], case["block"]
            started = time.monotonic()
            row: dict[str, Any] = {"token": token, "block": number, "deadline_seconds": deadline}
            try:
                block = await BlockRef.resolve(number)
                row["block_hash"] = block.hash
                await asyncio.wait_for(check(token, number), timeout=deadline)
                await block.verify()
                row.update(status="pass", canonical_verified=True)
            except Exception as exc:
                row.update(status="failure", error=f"{type(exc).__name__}: {exc}")
            row["elapsed_seconds"] = time.monotonic() - started
            rows.append(row)
            write_json(directory / "slow-erc20.json", rows)
            print(row, flush=True)
    finally:
        sampler.cancel()
        await asyncio.gather(sampler, return_exceptions=True)
    return int(any(row["status"] != "pass" for row in rows))


def run() -> int:
    # Match conftest setup before multicall captures Brownie's provider.
    from brownie._config import CONFIG
    from brownie.network.main import connect

    connect(os.environ["BROWNIE_NETWORK"])
    CONFIG.settings["autofetch_sources"] = False
    # Collection builds synchronous block fixtures, before the loop starts.
    from tests.classes.test_erc20 import test_erc20_at_block

    return asyncio.get_event_loop().run_until_complete(main(test_erc20_at_block))


if __name__ == "__main__":
    raise SystemExit(run())
