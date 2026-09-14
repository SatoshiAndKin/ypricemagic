"""Measure persisted bulk data and unused pool handles in separate processes."""

import argparse
import gc
import hashlib
import json
import os
import resource
import time
import tracemalloc
from pathlib import Path
from typing import Any

from multicall import Call
from pony.orm import db_session

from tests.test_bulk_memory import cached_sql_characters, insert, sqlite_database
from y.prices.dex.uniswap.v2 import UniswapV2Pool


def memory() -> dict[str, Any]:
    current, peak = tracemalloc.get_traced_memory()
    return {
        "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "python_current_bytes": current if tracemalloc.is_tracing() else None,
        "python_peak_bytes": peak if tracemalloc.is_tracing() else None,
        "profiler": "tracemalloc; exclude timings" if tracemalloc.is_tracing() else None,
    }


def bulk(directory: Path) -> dict[str, Any]:
    batches, batch_size, payload_bytes = 128, 32, 16384
    expected = hashlib.sha256()
    before = cached_sql_characters()
    path = Path("/data", f"bulk-{directory.name}.sqlite")
    with sqlite_database(path) as database:
        started = time.perf_counter()
        for batch in range(batches):
            values = []
            for index in range(batch * batch_size, (batch + 1) * batch_size):
                data = index.to_bytes(4, "big") * (payload_bytes // 4)
                expected.update(data)
                values.append((index, data, "payload", 1, None, 1))
            insert(database, values)
        del values, data
        elapsed = time.perf_counter() - started
        metrics = memory()
        actual = hashlib.sha256()
        count = 0
        with db_session:
            for index, data, notes, amount, created, parent in database.execute(
                "SELECT id,payload,notes,amount,created,parent FROM bulkmemory ORDER BY id"
            ):
                assert index == count
                assert (notes, amount, created, parent) == ("payload", 1, None, 1)
                assert data == index.to_bytes(4, "big") * (payload_bytes // 4)
                actual.update(data)
                count += 1
        assert count == batches * batch_size
        assert actual.digest() == expected.digest()
    return {
        **metrics,
        "elapsed_seconds": elapsed,
        "batches": batches,
        "batch_size": batch_size,
        "rows": count,
        "payload_bytes_per_row": payload_bytes,
        "persisted_sha256": actual.hexdigest(),
        "retained_sql_characters": cached_sql_characters() - before,
        "boundary": "bulk persistence only; no real RPC timing",
    }


def pools() -> dict[str, Any]:
    count = 131072
    token0 = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
    token1 = "0x6b175474e89094c44da98b954eedeac495271d0f"
    addresses = [f"0x{2**128 + index:040x}" for index in range(count)]
    before = sum(isinstance(value, Call) for value in gc.get_objects())
    started = time.perf_counter()
    created = [
        UniswapV2Pool(address, token0, token1, 18_000_000, asynchronous=True)
        for address in addresses
    ]
    elapsed = time.perf_counter() - started
    metrics = memory()
    # Collect scalar evidence after the timing and allocation measurement.
    # This census does not force garbage collection.
    handles = sum(isinstance(value, Call) for value in gc.get_objects()) - before
    actual = hashlib.sha256()
    expected = hashlib.sha256()
    for address, pool in zip(addresses, created):
        cache = getattr(pool, "__async_property__").cache
        assert pool.address.lower() == address
        assert (cache["token0"], cache["token1"], pool._deploy_block) == (
            token0,
            token1,
            18_000_000,
        )
        actual.update(
            f"{pool.address.lower()}|{cache['token0']}|{cache['token1']}|{pool._deploy_block}".encode()
        )
        expected.update(f"{address}|{token0}|{token1}|18000000".encode())
    assert actual.digest() == expected.digest()
    return {
        **metrics,
        "elapsed_seconds": elapsed,
        "pools": len(created),
        "reserve_call_handles_created": handles,
        "metadata_sha256": actual.hexdigest(),
        "boundary": "unused pool construction only; no reserve RPC is invoked",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workload", choices=("bulk", "pools"))
    parser.add_argument("--allocations", action="store_true")
    args = parser.parse_args()
    directory = Path(os.environ["VALIDATION_REPORT"])
    if args.allocations:
        tracemalloc.start()
    result = bulk(directory) if args.workload == "bulk" else pools()
    (directory / f"{args.workload}.json").write_text(json.dumps(result, indent=2) + "\n")
