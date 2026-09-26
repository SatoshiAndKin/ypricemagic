"""Measure synchronous Compound pricing and sample coroutine wait locations."""

import argparse
import asyncio
import json
import os
import signal
import time
from collections import Counter
from pathlib import Path
from typing import Any

from common import write_json

BUCKET_LABELS = frozenset(
    {
        "atoken",
        "balancer pool",
        "basketdao",
        "belt lp",
        "chainlink and band",
        "chainlink feed",
        "compound",
        "convex",
        "creth",
        "curve gauge",
        "curve lp",
        "ellipsis lp",
        "erc4626 vault",
        "froyo",
        "gearbox",
        "gelato",
        "generic amm",
        "ib token",
        "mooniswap lp",
        "mstable feeder pool",
        "one to one",
        "pendle lp",
        "pickle pslp",
        "piedao lp",
        "pool together v4 ticket",
        "popsicle",
        "reserve",
        "rkp3r",
        "saddle",
        "solidex",
        "stable usd",
        "stargate lp",
        "synthetix",
        "tarot supply vault",
        "token set",
        "uni or uni-like lp",
        "wrapped atoken v2",
        "wrapped atoken v3",
        "wrapped gas coin",
        "wsteth",
        "xpremia",
        "xtarot",
        "yearn or yearn-like",
    }
)


def locations(coro: Any) -> str:
    frames = []
    seen = set()
    while coro is not None and id(coro) not in seen:
        seen.add(id(coro))
        frame = getattr(coro, "cr_frame", getattr(coro, "gi_frame", None))
        if frame is not None:
            frames.append(f"{frame.f_code.co_filename}:{frame.f_lineno}:{frame.f_code.co_name}")
            if frame.f_code.co_filename.endswith("/y/prices/utils/buckets.py"):
                label = frame.f_locals.get("name", frame.f_locals.get("bucket"))
                if isinstance(label, str) and label in BUCKET_LABELS:
                    frames[-1] += f"[{label}]"
        coro = getattr(coro, "cr_await", getattr(coro, "gi_yieldfrom", None))
    return " -> ".join(frames)


async def sample(directory: Path, started: float) -> None:
    from dank_mids.controller import instances
    from dank_mids.retry_observer import (
        RetryEvent,
        register_retry_observer,
        unregister_retry_observer,
    )

    retries: Counter[str] = Counter()

    def retried(event: RetryEvent) -> None:
        # Keep scalar categories, never exceptions, tracebacks or request bodies.
        message = str(event.error)
        reason = next(
            (
                category
                for fragment, category in (
                    ("NotActivated", "unsupported opcode"),
                    ("InvalidFEOpcode", "legacy invalid opcode"),
                    ("historical state", "historical state unavailable"),
                    ("out of gas", "out of gas"),
                    ("execution reverted", "execution reverted"),
                )
                if fragment in message
            ),
            "other",
        )
        size = (event.metadata or {}).get("batch_size", "")
        key = f"{event.component}:{type(event.error).__name__}:size={size}:{reason}"
        retries[key if key in retries or len(retries) < 64 else "other"] += 1

    register_retry_observer(retried)
    try:
        await _sample(directory, started, instances, retries)
    finally:
        unregister_retry_observer(retried)


async def _sample(directory: Path, started: float, instances: Any, retries: Counter[str]) -> None:
    with (directory / "waits.jsonl").open("w") as stream:
        while True:
            tasks = Counter(locations(task.get_coro()) for task in asyncio.all_tasks())
            controllers = [c for group in instances.values() for c in group]
            stream.write(
                json.dumps(
                    {
                        "elapsed_seconds": time.monotonic() - started,
                        "tasks": dict(tasks.most_common()),
                        "retries": dict(retries),
                        "logical_rpc_counts": {
                            name: sum(getattr(c, name).latest + 1 for c in controllers)
                            for name in (
                                "call_uid",
                                "multicall_uid",
                                "request_uid",
                                "jsonrpc_batch_uid",
                            )
                        },
                    }
                )
                + "\n"
            )
            stream.flush()
            await asyncio.sleep(30)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token", default="0x6C8c6b02E7b2BE14d4fA6022Dfd6d75921D90E4E")
    parser.add_argument("--blocks", nargs="+", type=int, default=[7720735])
    parser.add_argument("--deadline", type=int, default=1800)
    args = parser.parse_args()
    from y.prices.lending.compound import CToken

    directory = Path(os.environ["VALIDATION_REPORT"])
    started = time.monotonic()
    loop = asyncio.get_event_loop()
    sampler = loop.create_task(sample(directory, started))
    rows = []

    def deadline(signum: int, frame: Any) -> None:
        raise TimeoutError(f"pricing exceeded diagnostic deadline {args.deadline}s")

    signal.signal(signal.SIGALRM, deadline)
    try:
        token: Any = CToken(args.token)
        for block in args.blocks:
            row: dict[str, Any] = {"token": args.token, "block": block}
            call_started = time.monotonic()
            signal.alarm(args.deadline)
            try:
                row["underlying_per_ctoken"] = token.underlying_per_ctoken(block)
                price = token.get_price(block)
                row.update(price=None if price is None else price.price, status="pass")
                assert price is not None
            except Exception as exc:
                row.update(status="failure", error=f"{type(exc).__name__}: {exc}")
            finally:
                signal.alarm(0)
            row["elapsed_seconds"] = time.monotonic() - call_started
            rows.append(row)
            write_json(directory / "price-waits.json", rows)
            print(json.dumps(row), flush=True)
    finally:
        sampler.cancel()
        loop.run_until_complete(asyncio.gather(sampler, return_exceptions=True))
    return int(any(row["status"] != "pass" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
