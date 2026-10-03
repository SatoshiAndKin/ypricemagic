"""Oracle reads must see the requested state before other simulations mutate it."""

import asyncio
import importlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from typing import Any, cast

from eth_abi.abi import decode, encode
from web3 import HTTPProvider, Web3

from tests.test_amount_quotes import BLOCK
from tests.test_pricing_correctness import run_async_test

ORACLE = "0x0000000000000000000000000000000000000101"
MARKET = "0x0000000000000000000000000000000000000102"
PRICE = 352206497921880


@run_async_test
async def test_oracle_read_isolated_from_concurrent_interest_accrual(monkeypatch: Any) -> None:
    from dank_mids import setup_dank_w3_from_sync
    from multicall import Call

    module = importlib.import_module("y.prices.lending.compound")
    calls: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))

            def respond(request: dict[str, Any]) -> dict[str, Any]:
                method = request["method"]
                if method == "eth_chainId":
                    result = "0x1"
                elif method == "web3_clientVersion":
                    result = "controlled-rpc"
                elif method == "eth_getCode":
                    result = "0x6000"
                else:
                    assert method == "eth_call", request
                    calls.append(request)
                    tx, block = request["params"][:2]
                    assert block == hex(BLOCK.number)
                    payload = bytes.fromhex(tx["data"][2:])
                    if payload[:4] == bytes.fromhex("399542e9"):
                        _, inner = decode(["bool", "(address,bytes)[]"], payload[4:])
                        accrues_interest = any(
                            target.lower() == MARKET.lower() for target, _ in inner
                        )
                        outputs = [
                            (
                                True,
                                encode(
                                    ["uint256"],
                                    [
                                        (
                                            PRICE + 3 * accrues_interest
                                            if target.lower() == ORACLE.lower()
                                            else 100
                                        )
                                    ],
                                ),
                            )
                            for target, _ in inner
                        ]
                        result = (
                            "0x"
                            + encode(
                                ["uint256", "bytes32", "(bool,bytes)[]"],
                                [BLOCK.number, bytes(32), outputs],
                            ).hex()
                        )
                    else:
                        result = (
                            "0x"
                            + encode(
                                ["uint256"], [PRICE if tx["to"].lower() == ORACLE.lower() else 100]
                            ).hex()
                        )
                return {"jsonrpc": "2.0", "id": request["id"], "result": result}

            response = [respond(item) for item in body] if isinstance(body, list) else respond(body)
            output = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        w3 = setup_dank_w3_from_sync(Web3(HTTPProvider(f"http://127.0.0.1:{server.server_port}")))
        monkeypatch.setattr(module, "dank_web3", w3, raising=False)

        def configured_call(target: str, function: Any, block_id: Any = None) -> Call:
            # multicall's annotation accepts only sync Web3, while its runtime
            # supports the AsyncWeb3 returned by Dank's setup helper.
            return Call(target, function, _w3=cast(Web3, w3), block_id=block_id)

        monkeypatch.setattr(module, "Call", configured_call)
        result = await asyncio.gather(
            *(
                configured_call(MARKET, "exchangeRateCurrent()(uint256)", block_id=BLOCK.number)
                for _ in range(4)
            ),
            module._read(ORACLE, ["getUnderlyingPrice(address)(uint256)", MARKET], BLOCK.number),
        )
        assert result == [100, 100, 100, 100, PRICE]
        direct = [call for call in calls if call["params"][0]["to"].lower() == ORACLE.lower()]
        assert len(direct) == 1
        assert any(call["params"][0]["data"].startswith("0x399542e9") for call in calls)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
