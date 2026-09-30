"""Measure repeated reads of the exact archive state that failed in the full suite."""

import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

from common import write_json


def main() -> None:
    url = os.environ["VALIDATION_RPC_URL"]
    block_hash = "0x55398e14c16d33e5a5e60408ef0c6a80d8c6a6e4c351dae17a83cf66c383ecff"
    address = "0xd0f001dbC3B5C3cFd5d2584f8C2cBD998c4D61e1"
    rows: list[dict[str, Any]] = []
    report = Path(os.environ["VALIDATION_REPORT"]) / "rpc-state-probe.json"
    for attempt in range(20):
        start = time.monotonic()
        request = urllib.request.Request(
            url,
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": attempt,
                    "method": "eth_getCode",
                    "params": [address, {"blockHash": block_hash, "requireCanonical": True}],
                }
            ).encode(),
            {"Content-Type": "application/json"},
        )
        row: dict[str, Any] = {"attempt": attempt}
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                decoded = json.load(response)
            if "error" in decoded:
                row["error"] = decoded["error"]
            else:
                code = bytes.fromhex(decoded["result"].removeprefix("0x"))
                row.update(length=len(code), sha256=hashlib.sha256(code).hexdigest())
        except Exception as exc:
            row["exception_type"] = type(exc).__name__
        row["elapsed"] = time.monotonic() - start
        rows.append(row)
        write_json(
            report, {"complete": False, "hash": block_hash, "address": address, "rows": rows}
        )
        print(json.dumps(row), flush=True)
        time.sleep(1)
    write_json(report, {"complete": True, "hash": block_hash, "address": address, "rows": rows})


if __name__ == "__main__":
    main()
