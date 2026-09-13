"""Fixed-block native checks retained from PR 43 validation."""

import os
import faulthandler
import signal
from typing import Any
import asyncio
import json
from dataclasses import asdict
from math import isqrt
from pathlib import Path
from eth_abi.abi import encode, decode
from eth_utils.crypto import keccak
from eth_utils.address import to_checksum_address
from brownie import web3
from y.prices._rpc import BlockRef
from y.prices._markets import Market, swap
from y.prices._redemptions import redeem
from y.datatypes import QuoteAsset

ZERO = "0x0000000000000000000000000000000000000000"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
DAI = "0x6b175474e89094c44da98b954eedeac495271d0f"
BAL = "0xba100000625a3754423978a60c9317c58a424e3d"
BPT = "0x5c6ee304399dbdb9c8ef030ab642b10820db8f56"
VAULT = "0xba12222222228d8ba445958a75a0704d566bf2c8"
BLOCK = 18000000


def direct(to: Any, sig: str, types: Any = (), args: Any = (), outputs: Any = ("uint256",)) -> Any:
    return decode(
        outputs,
        web3.eth.call(
            {"to": to_checksum_address(to), "data": keccak(text=sig)[:4] + encode(types, args)},
            block_identifier=BLOCK,
        ),
    )


async def main() -> int:
    block = await BlockRef.resolve(BLOCK)
    rows = []

    async def check(name: str, asset: QuoteAsset, expected: Any, call: Any) -> None:
        row = {"case": name, "block": block.number, "hash": block.hash, "input": asdict(asset)}
        try:
            actual = await call()
            step = actual[0] if isinstance(actual, tuple) else actual
            assert step is not None, "adapter returned unavailable"
            outputs = {o.token: o.amount for o in step.outputs}
            assert outputs == expected, (outputs, expected)
            row.update(status="pass", expected=expected, quote=asdict(step))
        except Exception as exc:
            row.update(status="failure", error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
        print(json.dumps(row, default=str), flush=True)
        Path(os.environ["VALIDATION_REPORT"], "native-reviewed.json").write_text(
            json.dumps(rows, indent=2, default=str)
        )

    pool_id = direct(BPT, "getPoolId()", outputs=["bytes32"])[0]
    amount = 10**20
    deltas = direct(
        VAULT,
        "queryBatchSwap(uint8,(bytes32,uint256,uint256,uint256,bytes)[],address[],(address,bool,address,bool))",
        [
            "uint8",
            "(bytes32,uint256,uint256,uint256,bytes)[]",
            "address[]",
            "(address,bool,address,bool)",
        ],
        [0, [(pool_id, 0, 1, amount, b"")], [BAL, WETH], (ZERO, False, ZERO, False)],
        ["int256[]"],
    )[0]
    asset = QuoteAsset(BAL, amount, 18)
    market = Market("Balancer V2", BPT, (BAL, WETH), (0, 0), VAULT, pool_id=pool_id)
    await check(
        "Balancer V2 swap", asset, {WETH: -deltas[1]}, lambda: swap(market, asset, WETH, block)
    )
    asset = QuoteAsset(BPT, 10**18, 18)
    tokens, balances, last = direct(
        VAULT,
        "getPoolTokens(bytes32)",
        ["bytes32"],
        [pool_id],
        ["address[]", "uint256[]", "uint256"],
    )
    collector = direct(VAULT, "getProtocolFeesCollector()", outputs=["address"])[0]
    fee = direct(collector, "getSwapFeePercentage()")[0]
    burned, amounts = direct(
        BPT,
        "queryExit(bytes32,address,address,uint256[],uint256,uint256,bytes)",
        ["bytes32", "address", "address", "uint256[]", "uint256", "uint256", "bytes"],
        [
            pool_id,
            ZERO,
            ZERO,
            balances,
            last,
            fee,
            encode(["uint256", "uint256"], [1, asset.amount]),
        ],
        ["uint256", "uint256[]"],
    )
    assert burned == asset.amount
    await check(
        "Balancer V2 LP exit",
        asset,
        {t.lower(): a for t, a in zip(tokens, amounts) if a},
        lambda: redeem(asset, block, frozenset()),
    )
    for name, token, shares, decimals in [
        ("Compound cDAI", "0x5d3a536e4d6dbd6114cc1ead35777bab948e3643", 10**10, 8),
        ("Aave V2 aUSDC", "0xbcca60bb61934080951369a648fb03df4f96263c", 10**9, 6),
        ("Lido wstETH", "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0", 10**18, 18),
        ("Curve steCRV gauge", "0x182b723a58739a9c974cfdb385ceadb237453c28", 10**18, 18),
        ("Convex cvx3crv", "0x30d9410ed1d5da1f6c8391af5338c93ab8d4035c", 10**18, 18),
        ("Curve 3crv withdrawal", "0x6c3f90f043a72fa612cbac8115ee7e52bde6e490", 10**21, 18),
    ]:
        asset = QuoteAsset(token, shares, decimals)
        if name.startswith("Compound"):
            underlying = direct(token, "underlying()", outputs=["address"])[0]
            expected = {underlying: shares * direct(token, "exchangeRateCurrent()")[0] // 10**18}
        elif name.startswith("Aave"):
            expected = {direct(token, "UNDERLYING_ASSET_ADDRESS()", outputs=["address"])[0]: shares}
        elif name.startswith("Lido"):
            expected = {
                "0xae7ab96520de3a18e5e111b5eaab095312d7fe84": direct(
                    token, "getStETHByWstETH(uint256)", ["uint256"], [shares]
                )[0]
            }
        elif name.startswith("Curve 3"):
            expected = {
                DAI: direct(
                    "0xbebc44782c7db0a1a60cb6fe97d0b483032ff1c7",
                    "calc_withdraw_one_coin(uint256,int128)",
                    ["uint256", "int128"],
                    [shares, 0],
                )[0]
            }
        elif name.startswith("Curve ste"):
            expected = {direct(token, "lp_token()", outputs=["address"])[0]: shares}
        else:
            expected = {"0x6c3f90f043a72fa612cbac8115ee7e52bde6e490": shares}
        await check(name, asset, expected, lambda: redeem(asset, block, frozenset()))
    await block.verify()
    return int(any(row["status"] != "pass" for row in rows))


faulthandler.register(signal.SIGUSR1, all_threads=True)
raise SystemExit(asyncio.get_event_loop().run_until_complete(main()))
