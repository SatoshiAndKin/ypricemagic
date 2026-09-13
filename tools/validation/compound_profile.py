"""Profile the synchronous Compound case active during the contained baseline OOM."""

import argparse
import faulthandler
import gc
import os
from pathlib import Path
import signal
import threading
import time
import tracemalloc
from typing import Any

from common import write_json
from profile_state import capture, sample


def main(blocks: list[int] | None) -> None:
    from tests.fixtures import blocks_for_contract
    from y.prices.lending.compound import CToken

    directory = Path(os.environ["VALIDATION_REPORT"])
    token = "0x6C8c6b02E7b2BE14d4fA6022Dfd6d75921D90E4E"
    ctoken: Any = CToken(token)
    if blocks is None:
        blocks = blocks_for_contract(token)
    # Record the test's selection so later profiles can use the exact same blocks.
    write_json(directory / "compound-input.json", {"token": token, "blocks": blocks})
    gc.collect()
    tracemalloc.start()
    capture(directory, "before")
    stop = threading.Event()
    sampler = threading.Thread(target=sample, args=(directory, stop), daemon=True)
    sampler.start()
    started = time.monotonic()
    completed: list[int] = []
    error = None
    try:
        for block in blocks:
            write_json(
                directory / "compound-progress.json",
                {"token": token, "block": block, "completed_blocks": completed},
            )
            ctoken.underlying_per_ctoken(block)
            price = ctoken.get_price(block)
            assert price, "Failed to fetch price."
            completed.append(block)
            capture(directory, f"block-{block}")
    except BaseException as caught:
        error = f"{type(caught).__name__}: {caught}"
        raise
    finally:
        stop.set()
        sampler.join()
        capture(directory, "after")
        current, peak = tracemalloc.get_traced_memory()
        write_json(
            directory / "compound-summary.json",
            {
                "complete": len(completed) == len(blocks),
                "completed_blocks": completed,
                "error": error,
                "elapsed_seconds": time.monotonic() - started,
                "python_retained_bytes": current,
                "python_peak_bytes": peak,
                "profiled": True,
            },
        )


if __name__ == "__main__":
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocks", type=int, nargs=5)
    main(parser.parse_args().blocks)
