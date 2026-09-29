"""Sequential fixed-block checks for the PR 43 historical pricing repairs."""

import asyncio
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from common import write_json
from web3.exceptions import ContractLogicError

from y.constants import EEE_ADDRESS
from y.datatypes import QuoteAsset
from y.prices._markets import Market, discover, swap
from y.prices._rpc import BlockRef, deployed, read
from y.prices.lending.compound import CToken
from y.prices.synthetix import synthetix

USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
WETH = "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2"
ROUTER = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d"
POOL = "0xb4e16d0168e52d35cacd2c6185b44281ec28c9dc"
QUOTER = "0xb27308f9f90d607463bb33ea1bebb41c27ce5ab6"


async def main() -> int:
    report = Path(os.environ["VALIDATION_REPORT"]) / "native-historical.json"
    rows: list[dict[str, Any]] = []

    async def record(name: str, number: int, work: Any) -> None:
        block = await BlockRef.resolve(number)
        row: dict[str, Any] = {"case": name, "number": number, "hash": block.hash}
        try:
            row["evidence"] = await work(block)
            await block.verify()
            row["status"] = "pass"
        except Exception as exc:
            row.update(status="failure", error_type=type(exc).__name__, error=str(exc))
        rows.append(row)
        write_json(report, {"complete": False, "rows": rows})
        print(json.dumps(row, default=str), flush=True)

    async def v2(block: BlockRef) -> Any:
        pool_code, router_code = await deployed(POOL, block), await deployed(ROUTER, block)
        market = Market("Uniswap V2", POOL, (USDC, WETH), (0, 0), ROUTER)
        result = await swap(market, QuoteAsset(USDC, 10**6, 6), WETH, block)
        assert pool_code
        if block.number == 10_100_000:
            assert not router_code and result is None
        else:
            native = await read(
                ROUTER, "getAmountsOut(uint256,address[])(uint256[])", block, 10**6, [USDC, WETH]
            )
            assert router_code and result is not None
            assert result.outputs[0].amount == native[-1]
        return {
            "pool_code": pool_code,
            "router_code": router_code,
            "quote": asdict(result) if result else None,
        }

    await record("V2 Router02 unavailable", 10_100_000, v2)
    await record("V2 later successful quote", 18_000_000, v2)

    async def v1(block: BlockRef) -> Any:
        token = "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2"
        markets = await discover(token, block, ("Uniswap V1",))
        assert len(markets) == 1
        first = await swap(markets[0], QuoteAsset(token, 10**18, 18), EEE_ADDRESS.lower(), block)
        assert first is not None
        exits = await discover(EEE_ADDRESS.lower(), block)
        assert len(exits) == 1
        second = await swap(exits[0], first.outputs[0], USDC, block)
        assert second is not None and second.outputs[0].amount == 356324373
        return [asdict(first), asdict(second)]

    await record("MKR V1 native two-leg USDC sale", 9_990_134, v1)

    for name, token, pool, output, number, expected in (
        (
            "MLN partial fill rejected",
            "0xec67005c4e498ec7f55e092bd1d35cbc47c91892",
            "0xd950cd33195a1ad36c416eecf6b3317eccba77e1",
            WETH,
            26_063_967,
            None,
        ),
        (
            "CRV full input",
            "0xd533a949740bb3306d119cc777fa900ba034cd52",
            "0x07b1c12be0d62fe548a2b4b025ab7a5ca8def21e",
            "0xdac17f958d2ee523a2206206994597c13d831ec7",
            26_063_944,
            269190,
        ),
        (
            "YFI full input",
            "0x0bc529c00c6401aef6d220be8c6ea1667f6ad93e",
            "0x04916039b1f59d9745bf6e0a21f191d1e0a84287",
            WETH,
            26_065_255,
            720711902814369320,
        ),
    ):

        async def v3(block: BlockRef) -> Any:
            fee = int(await read(pool, "fee()(uint24)", block))
            market = Market("Uniswap V3", pool, (token, output), (0, 0), QUOTER, fee)
            result = await swap(market, QuoteAsset(token, 10**18, 18), output, block)
            if expected is None:
                assert result is None
            else:
                assert result is not None and result.outputs[0].amount == expected
            return asdict(result) if result else None

        await record(name, number, v3)

    for name, token, number, expected_price in (
        ("historical sUSD", "0x57ab1e02fee23774580c119740129eac7081e9d3", 10_837_752, 1),
        (
            "historical sDEFI",
            "0xe1afe1fd76fd88f78cbf599ea1846231b8ba3b6b",
            11_000_000,
            2915.99587083,
        ),
    ):

        async def synth(block: BlockRef) -> Any:
            price = await cast(Any, synthetix).get_price(token, block.number, sync=False)
            assert price == expected_price
            return {"price": price}

        await record(name, number, synth)

    for name, token, number, expected_raw, decimals in (
        (
            "Cream BBTC ETH-denominated oracle",
            "0x7ea9c63e216d5565c3940a2b3d150e59c2907db3",
            11_212_982,
            339710892300000000000000000000,
            8,
        ),
        (
            "Cream HFIL ETH-denominated oracle",
            "0xd5103afcd0b3fa865997ef2984c66742c51b2a8b",
            11_297_588,
            57340480000000000,
            18,
        ),
        (
            "IronBank EUR USD-denominated oracle",
            "0x00e5c0774a5f065c285068170b20393925c84bf3",
            12_867_424,
            1178470000000000000,
            18,
        ),
    ):

        async def compound(block: BlockRef) -> Any:
            controller = await read(token, "comptroller()(address)", block)
            oracle = await read(controller, "oracle()(address)", block)
            raw = await read(oracle, "getUnderlyingPrice(address)(uint256)", block, token)
            assert raw == expected_raw
            expected = raw / 10 ** (36 - decimals)
            eth_answer = None
            if name.startswith("Cream"):
                feed = "0x5f4ec3df9cbd43714fe2740f5e3616155c5b8419"
                eth_answer = await read(feed, "latestAnswer()(int256)", block)
                feed_decimals = await read(feed, "decimals()(uint8)", block)
                expected *= eth_answer / 10**feed_decimals
            actual = await cast(Any, CToken(token, asynchronous=True)).get_underlying_price(
                block.number
            )
            assert actual == expected, (actual, expected)
            return {
                "controller": controller,
                "oracle": oracle,
                "raw": raw,
                "eth_usd_answer": eth_answer,
                "expected_usd": expected,
                "actual_usd": actual,
            }

        await record(name, number, compound)

    async def resilient(block: BlockRef) -> Any:
        token = "0xd8add9b41d4e1cd64edad8722ab0ba8d35536657"
        controller = await read(token, "comptroller()(address)", block)
        oracle = await read(controller, "oracle()(address)", block)
        try:
            await read(oracle, "getUnderlyingPrice(address)(uint256)", block, token)
        except ContractLogicError as exc:
            reason = exc.args[0]
            assert reason == "execution reverted: invalid resilient oracle price"
        else:
            raise AssertionError("expected the historical oracle to reject its sources")
        actual = await cast(Any, CToken(token, asynchronous=True)).get_underlying_price(
            block.number
        )
        assert actual is None
        return {"oracle": oracle, "native_revert": reason, "adapter": actual}

    await record("Venus unavailable resilient oracle", 0x12C94EC, resilient)

    async def inverse(block: BlockRef) -> Any:
        token = "0x0bc08f2433965ea88d977d7bfded0917f3a0f60b"
        oracle = "0xe8929afd47064efd36a7fb51da3f8c5eb40c4cb4"
        feed, decimals = await read(oracle, "feeds(address)(address,uint8)", block, token)
        aggregator = await read(feed, "aggregator()(address)", block)
        assert int(aggregator, 16) == 0
        ctoken = cast(Any, CToken(token, asynchronous=True))
        assert await ctoken.get_underlying_price(block.number) is None
        price = await ctoken.get_price(block.number)
        assert price is not None and float(price) == 0.0014653492066322037
        return {
            "oracle": oracle,
            "feed": feed,
            "aggregator": aggregator,
            "price": float(price),
        }

    await record("Inverse retired Chainlink feed", 16_871_536, inverse)

    async def pie(block: BlockRef) -> Any:
        from y.prices import magic

        price = await cast(Any, magic.get_price)(
            "0x9a48bd0ec040ea4f1d3147c025cd4076a2e71e3e", block.number, skip_cache=True, sync=False
        )
        assert float(price) == 1.0002097895742665
        return {"price": float(price)}

    await record("PieDAO native balances and historical feeds", 15_000_000, pie)

    write_json(report, {"complete": True, "rows": rows})
    return int(any(row["status"] != "pass" for row in rows))


if __name__ == "__main__":
    raise SystemExit(asyncio.get_event_loop().run_until_complete(main()))
