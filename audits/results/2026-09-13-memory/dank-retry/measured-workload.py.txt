"""Measure live HTTP retry ownership with a fixed concurrent workload.

Run each timing sample without --allocations. Allocation runs are separate so
tracemalloc overhead cannot affect the final timing comparison.
"""

import argparse
import asyncio
from collections import Counter
import json
import logging
from pathlib import Path
from threading import RLock
import time
import tracemalloc
from types import SimpleNamespace
import weakref

from aiohttp import ClientResponseError

from dank_mids import _requests
from dank_mids._requests import RPCRequest
from dank_mids.helpers._codec import decode_raw


class Payload:
    def __init__(self, size):
        self.buffer = bytearray(size)


class Controller:
    max_jsonrpc_batch_size = 1000
    endpoint = "http://example.invalid"

    def __init__(self, operation):
        self._loop = asyncio.get_running_loop()
        self.pools_closed_lock = RLock()
        self.pending_rpc_calls = []
        self.make_request = operation


def resident_memory():
    values = {}
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith(("VmRSS:", "VmHWM:")):
            key, number, unit = line.split()
            assert unit == "kB"
            values[key.removesuffix(":")] = int(number) * 1024
    return values


async def measure(concurrency, retries, payload_bytes, allocations):
    logging.disable(logging.CRITICAL)
    if allocations:
        tracemalloc.start()
    memory_before = resident_memory()
    python_before = tracemalloc.get_traced_memory()[0] if allocations else None
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    all_waiting, release = asyncio.Event(), asyncio.Event()
    counts, references = Counter(), []
    waiting = 0
    expected = decode_raw(b'{"jsonrpc":"2.0","id":"same","result":"0x1"}')

    async def operation(method, params, request_id):
        nonlocal waiting
        assert method == "eth_blockNumber" and params == []
        counts[request_id] += 1
        if counts[request_id] <= retries:
            payload = Payload(payload_bytes)
            references.append(weakref.ref(payload))
            raise ClientResponseError(
                SimpleNamespace(real_url="http://example.invalid"), (), status=408
            )
        waiting += 1
        if waiting == concurrency:
            all_waiting.set()
        await release.wait()
        return expected

    controller = Controller(operation)
    requests = [
        RPCRequest(controller, "eth_blockNumber", [], uid=str(index))
        for index in range(concurrency)
    ]
    tasks = [asyncio.create_task(request.make_request()) for request in requests]
    try:
        await asyncio.wait_for(all_waiting.wait(), 30)
        await asyncio.sleep(0)
        memory_pending = resident_memory()
        result = {
            "concurrency": concurrency,
            "retries": retries,
            "payload_bytes": payload_bytes,
            "attempts": sum(counts.values()),
            "retained_failed_payloads": sum(ref() is not None for ref in references),
            "pending_tasks": sum(not task.done() for task in asyncio.all_tasks()),
            "memory_before": memory_before,
            "memory_pending": memory_pending,
            "elapsed_to_pending_seconds": time.perf_counter() - started_wall,
            "cpu_to_pending_seconds": time.process_time() - started_cpu,
            "tracemalloc_enabled": allocations,
            "python_before_bytes": python_before,
            "python_pending_bytes": tracemalloc.get_traced_memory() if allocations else None,
            "request_module": _requests.__file__,
        }
        assert counts == Counter({str(index): retries + 1 for index in range(concurrency)})
        release.set()
        results = await asyncio.gather(*tasks)
        assert all(response is expected for response in results)
        assert all(request._fut.result() is expected for request in requests)
        result["total_elapsed_seconds"] = time.perf_counter() - started_wall
        result["total_cpu_seconds"] = time.process_time() - started_cpu
        result["memory_completed"] = resident_memory()
        return result
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        if allocations:
            tracemalloc.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allocations", action="store_true")
    args = parser.parse_args()
    result = asyncio.run(measure(64, 16, 128 * 1024, args.allocations))
    args.output.write_text(json.dumps(result, indent=2) + "\n")
