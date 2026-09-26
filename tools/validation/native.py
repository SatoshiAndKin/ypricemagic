"""Fixed-block native checks retained from PR 43 validation."""

import asyncio
import faulthandler
import json
import os
import signal
from contextlib import aclosing
from pathlib import Path
from typing import Any

from brownie import web3
from eth_abi.abi import decode, encode
from eth_abi.packed import encode_packed
from eth_utils.address import to_checksum_address
from eth_utils.crypto import keccak

from y.datatypes import QuoteAsset
from y.prices._markets import Market, curve_pool_state, swap
from y.prices._redemptions import redeem
from y.prices._rpc import BlockRef

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
BAL = "0xba100000625a3754423978a60c9317c58a424e3d"


def direct(to: Any, sig: str, types: Any, args: Any, outputs: Any, block: Any) -> Any:
    return decode(
        outputs,
        web3.eth.call(
            {"to": to_checksum_address(to), "data": keccak(text=sig)[:4] + encode(types, args)},
            block_identifier=block,
        ),
    )


async def first_redemption(asset: QuoteAsset, block: BlockRef) -> Any:
    async with aclosing(redeem(asset, block, frozenset())) as candidates:
        return await anext(candidates, None)


async def main() -> int:
    results = []
    historical = await BlockRef.resolve(10100000)
    pool = "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc"
    router = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
    row: dict[str, Any] = {
        "case": "V2 before Router02 deployment",
        "block": historical.number,
        "hash": historical.hash,
        "pool": pool,
        "router": router,
        "amount_in": 10**9,
    }
    try:
        pool_code = web3.eth.get_code(to_checksum_address(pool), historical.number)
        router_code = web3.eth.get_code(to_checksum_address(router), historical.number)
        row.update(pool_code_bytes=len(pool_code), router_code_bytes=len(router_code))
        assert pool_code and not router_code
        actual = await swap(
            Market("Uniswap V2", pool, (USDC, WETH), (0, 0), router),
            QuoteAsset(USDC, 10**9, 6),
            WETH,
            historical,
        )
        assert actual is None
        await historical.verify()
        row.update(adapter_result=None, canonical_verified=True, status="pass")
    except Exception as exc:
        row.update(status="failure", error=f"{type(exc).__name__}: {exc}")
    results.append(row)
    print(json.dumps(row), flush=True)
    block = await BlockRef.resolve(18000000)
    cases = [
        (
            "V2",
            Market(
                "Uniswap V2",
                "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc",
                (USDC, WETH),
                (0, 0),
                "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
            ),
            QuoteAsset(USDC, 10**9, 6),
            WETH,
        ),
        (
            "V3",
            Market(
                "Uniswap V3",
                "0x88e6a0c2ddd26feeb64f039a2c41296fcb3f5640",
                (USDC, WETH),
                (0, 0),
                "0xb27308f9f90d607463bb33ea1bebb41c27ce5ab6",
                500,
            ),
            QuoteAsset(USDC, 10**9, 6),
            WETH,
        ),
        (
            "Curve",
            Market(
                "Curve",
                "0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7",
                (DAI, USDC, "0xdac17f958d2ee523a2206206994597c13d831ec7"),
                (0, 0, 0),
            ),
            QuoteAsset(USDC, 10**9, 6),
            DAI,
        ),
    ]
    for name, market, asset, out in cases:
        try:
            if name == "V2":
                expected = direct(
                    market.router,
                    "getAmountsOut(uint256,address[])",
                    ["uint256", "address[]"],
                    [asset.amount, [asset.token, out]],
                    ["uint256[]"],
                    block.number,
                )[0][-1]
            elif name == "V3":
                path = encode_packed(
                    ["address", "uint24", "address"], [asset.token, market.fee, out]
                )
                expected = direct(
                    market.router,
                    "quoteExactInput(bytes,uint256)",
                    ["bytes", "uint256"],
                    [path, asset.amount],
                    ["uint256"],
                    block.number,
                )[0]
            else:
                expected = direct(
                    market.pool,
                    "get_dy(int128,int128,uint256)",
                    ["int128", "int128", "uint256"],
                    [1, 0, asset.amount],
                    ["uint256"],
                    block.number,
                )[0]
            actual = await swap(market, asset, out, block)
            assert actual is not None
            assert actual.outputs[0].amount == expected
            results.append(
                {
                    "case": name,
                    "block": block.number,
                    "hash": block.hash,
                    "amount_in": asset.amount,
                    "amount_out": expected,
                    "status": "pass",
                }
            )
        except Exception as exc:
            results.append(
                {"case": name, "status": "failure", "error": f"{type(exc).__name__}: {exc}"}
            )
        print(json.dumps(results[-1]), flush=True)
    vault = "0x83f20f44975d03b1b09e64809b757c47f942beea"
    try:
        expected = direct(
            vault, "previewRedeem(uint256)", ["uint256"], [10**21], ["uint256"], block.number
        )[0]
        redemption = await first_redemption(QuoteAsset(vault, 10**21, 18), block)
        assert redemption is not None
        assert redemption[0].outputs[0].amount == expected
        results.append(
            {
                "case": "ERC4626 sDAI",
                "block": block.number,
                "hash": block.hash,
                "shares": 10**21,
                "assets": expected,
                "status": "pass",
            }
        )
    except Exception as exc:
        results.append(
            {"case": "ERC4626 sDAI", "status": "failure", "error": f"{type(exc).__name__}: {exc}"}
        )
    print(json.dumps(results[-1]), flush=True)
    for pool in (
        "0xa2b47e3d5c44877cca798226b7b8118f9bfb7a56",
        "0x45f783cce6b7ff23b2ab2d70e416cdb7d6055f51",
    ):
        snapshot = await curve_pool_state(pool, block)
        expected = direct(pool, "coins(int128)", ["int128"], [0], ["address"], block.number)[
            0
        ].lower()
        assert snapshot is not None
        assert snapshot.tokens[0] == expected
        results.append(
            {
                "case": "Curve int128 getter",
                "pool": pool,
                "block": block.number,
                "hash": block.hash,
                "first_coin": expected,
                "status": "pass",
            }
        )
    await block.verify()
    Path(os.environ["VALIDATION_REPORT"], "native.json").write_text(json.dumps(results, indent=2))
    return int(any(row["status"] != "pass" for row in results))


faulthandler.register(signal.SIGUSR1, all_threads=True)
raise SystemExit(asyncio.get_event_loop().run_until_complete(main()))
