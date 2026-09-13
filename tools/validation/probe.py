"""Verify archive state and EIP-1898 access before running expensive checks."""

import json
import os
from pathlib import Path
import urllib.request
from typing import cast

from common import write_json


def main() -> None:
    url = os.environ["VALIDATION_RPC_URL"]

    def rpc(method: str, params: list[object]) -> object:
        request = urllib.request.Request(
            url,
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
            {"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        if "error" in result:
            raise RuntimeError(result["error"])
        return cast(object, result["result"])

    report: dict[str, object] = {"complete": False, "stage": "chain_id"}
    try:
        assert rpc("eth_chainId", []) == "0x1"
        blocks: list[dict[str, object]] = []
        for number in (16_830_000, 18_000_000):
            report.update(stage="historical_header", number=number, blocks=blocks)
            header = rpc("eth_getBlockByNumber", [hex(number), False])
            assert isinstance(header, dict)
            report.update(stage="historical_call", block_hash=header["hash"])
            value = rpc(
                "eth_call",
                [
                    {"to": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "data": "0x313ce567"},
                    {"blockHash": header["hash"], "requireCanonical": True},
                ],
            )
            assert isinstance(value, str) and int(value, 16) == 6
            blocks.append({"number": number, "hash": header["hash"], "usdc_decimals": 6})
        report.update(complete=True, stage="complete", blocks=blocks)
    except Exception as error:
        # Preserve the failing operation without recording the private endpoint.
        report["error_type"] = type(error).__name__
        raise
    finally:
        write_json(Path(os.environ["VALIDATION_REPORT"]) / "rpc-probe.json", report)


if __name__ == "__main__":
    main()
