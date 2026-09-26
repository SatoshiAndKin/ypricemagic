"""Historical quote and address regressions through production adapters and routing."""

import asyncio
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from dank_mids.brownie_patch import dank_web3
from eth_abi.abi import encode
from hexbytes import HexBytes

from tests.test_amount_quotes import BLOCK, TOKEN, USD, graph, market
from tests.test_pricing_correctness import Ready, instance, run_async_test
from y import convert
from y.classes.common import ERC20
from y.datatypes import QuoteAsset
from y.exceptions import yPriceMagicError
from y.prices import _markets, _routing, magic
from y.prices._rpc import BlockRef
from y.prices.dex.uniswap import v2, v3

LETTER_TOKEN = "0x000000000000000000000000000000000000aBcD"
OTHER_TOKEN = "0x000000000000000000000000000000000000deFa"
ROUTER = "0x0000000000000000000000000000000000000201"
SECOND_ROUTER = "0x0000000000000000000000000000000000000202"


def address_form(kind: str) -> Any:
    return {
        "checksum": convert.to_address(LETTER_TOKEN),
        "lower": LETTER_TOKEN.lower(),
        "bytes": bytes.fromhex(LETTER_TOKEN[2:]),
        "hexbytes": HexBytes(LETTER_TOKEN),
    }[kind]


def empty_quote_graph(monkeypatch: Any, empty: str, viable: bool) -> tuple[Any, list[str]]:
    pools = [replace(market("deep", depth=2), router=ROUTER)]
    if viable:
        pools.append(replace(market("later", depth=1), router=SECOND_ROUTER))
    service, _, _ = graph(monkeypatch, pools)
    monkeypatch.setattr(_routing, "swap", _markets.swap)
    monkeypatch.setattr(_routing, "quote_service", lambda: service)
    monkeypatch.setattr(BlockRef, "resolve", AsyncMock(return_value=BLOCK))
    monkeypatch.setattr(magic, "ERC20", lambda *a, **kw: SimpleNamespace(symbol=Ready("TOKEN")))
    calls: list[str] = []

    async def rpc(transaction: dict[str, Any], *, block_identifier: Any) -> bytes:
        assert block_identifier == BLOCK.identifier
        if transaction["to"].lower() == USD:
            return encode(["uint8"], [6])
        target = transaction["to"].lower()
        calls.append(target)
        from eth_utils.crypto import keccak

        assert transaction["data"] == keccak(text="getAmountsOut(uint256,address[])")[:4] + encode(
            ["uint256", "address[]"], [1000001, [TOKEN, USD]]
        )
        if target == ROUTER:
            return b"" if empty == "rpc" else encode(["uint256[]"], [[]])
        assert target == SECOND_ROUTER
        return encode(["uint256[]"], [[1000001, 997003]])

    monkeypatch.setattr(dank_web3.eth, "call", rpc)
    return service, calls


@run_async_test
@pytest.mark.parametrize("empty", ["rpc", "array"])
async def test_empty_v2_rpc_quote_tries_next_pool(monkeypatch: Any, empty: str) -> None:
    service, calls = empty_quote_graph(monkeypatch, empty, True)
    result = await service.price(TOKEN, BLOCK, Decimal("1.000001"))
    assert result is not None and result.quote is not None
    assert result.quote.input == QuoteAsset(TOKEN, 1000001, 6)
    assert result.quote.outputs == (QuoteAsset(USD, 997003, 6),)
    assert result.quote.total_usd == Decimal("0.997003")
    assert [step.contract for step in result.quote.steps] == ["later"]
    assert result.quote.steps[0].fees == "DEX fees included in native quote"
    assert calls == [ROUTER, SECOND_ROUTER]


@run_async_test
@pytest.mark.parametrize("empty", ["rpc", "array"])
@pytest.mark.parametrize("fail", [True, False])
async def test_empty_v2_public_exhaustion(monkeypatch: Any, empty: str, fail: bool) -> None:
    _, calls = empty_quote_graph(monkeypatch, empty, False)
    if fail:
        assert (
            await cast(Any, magic.get_price)(
                TOKEN, BLOCK.number, amount=Decimal("1.000001"), fail_to_None=True, sync=False
            )
            is None
        )
    else:
        with pytest.raises(yPriceMagicError):
            await cast(Any, magic.get_price)(
                TOKEN, BLOCK.number, amount=Decimal("1.000001"), sync=False
            )
    assert calls == [ROUTER]


@run_async_test
@pytest.mark.parametrize("empty", [None, [], ()])
async def test_decoded_empty_v2_quote_is_unavailable(monkeypatch: Any, empty: Any) -> None:
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=empty))
    assert await _markets.swap(market("pool"), QuoteAsset(TOKEN, 1, 6), USD, BLOCK) is None


@run_async_test
@pytest.mark.parametrize(
    "error", [TypeError("bad decoder"), RuntimeError("RPC failed"), asyncio.CancelledError()]
)
async def test_v2_unexpected_errors_propagate(monkeypatch: Any, error: BaseException) -> None:
    service, _ = empty_quote_graph(monkeypatch, "rpc", True)
    monkeypatch.setattr(dank_web3.eth, "call", AsyncMock(side_effect=error))
    with pytest.raises(type(error), match=str(error)):
        await service.price(TOKEN, BLOCK, Decimal("1.000001"))


@run_async_test
@pytest.mark.parametrize("kind", ["checksum", "lower", "bytes", "hexbytes"])
async def test_v2_index_normalizes_metadata_lookup(monkeypatch: Any, kind: str) -> None:
    first = v2.UniswapV2Pool(
        "0x0000000000000000000000000000000000000311",
        token0=ERC20(LETTER_TOKEN),
        token1=ERC20(OTHER_TOKEN),
        deploy_block=100,
        asynchronous=True,
    )
    second = v2.UniswapV2Pool(
        "0x0000000000000000000000000000000000000312",
        token0=ERC20(LETTER_TOKEN),
        token1=ERC20(USD),
        deploy_block=101,
        asynchronous=True,
    )
    monkeypatch.setattr(
        v2.UniswapRouterV2, "__pools__", property(lambda self: Ready([first, second]))
    )
    router = instance(v2.UniswapRouterV2)
    router.address = ROUTER
    router._supports_factory_helper = False
    router.factory = ROUTER
    monkeypatch.setattr(v2, "contract_creation_block_async", AsyncMock(return_value=90))
    # Only native reserves are controlled; indexing, deployment filtering and liquidity stay real.
    monkeypatch.setattr(first, "get_reserves", AsyncMock(return_value=(123456, 654321, 0)))
    monkeypatch.setattr(second, "get_reserves", AsyncMock(return_value=(987654, 456789, 0)))
    token = address_form(kind)
    expected = {first: convert.to_address(OTHER_TOKEN), second: convert.to_address(USD)}
    assert await router.all_pools_for(token, sync=False) == expected
    index = await router.__pools_by_token__
    copied = await router.get_pools_for(token, 100, sync=False)
    assert copied == expected
    copied.clear()
    assert await router.all_pools_for(token, sync=False) == expected
    assert await router.__pools_by_token__ is index
    assert [p async for p in router.pools_for_token(token, block=99)] == []
    assert [p async for p in router.pools_for_token(token, block=100)] == [first]
    assert [p async for p in router.pools_for_token(token, block=101)] == [first, second]
    assert [p async for p in router.pools_for_token(token, block=None)] == [first, second]
    assert [
        p async for p in router.pools_for_token(token, block=101, _ignore_pools=(str(first),))
    ] == [second]
    assert await router.check_liquidity(token, 89, sync=False) == 0
    assert await router.check_liquidity(token, 99, sync=False) == 0
    assert await router.check_liquidity(token, 100, sync=False) == 123456
    assert await router.check_liquidity(token, 101, sync=False) == 987654
    assert (
        await router.check_liquidity(token, 101, ignore_pools=(str(second),), sync=False) == 123456
    )
    assert await router.check_liquidity(token, 101, ignore_pools=(first, second), sync=False) == 0


@run_async_test
@pytest.mark.parametrize("protocol", ["Uniswap V3", "Slipstream"])
@pytest.mark.parametrize("kind", ["checksum", "lower", "bytes", "hexbytes"])
@pytest.mark.parametrize("block_number,skip_cache", [(None, False), (BLOCK.number, True)])
async def test_v3_entry_normalizes_before_real_routing(
    monkeypatch: Any, protocol: str, kind: str, block_number: int | None, skip_cache: bool
) -> None:
    token = LETTER_TOKEN.lower()
    factory = convert.to_address(OTHER_TOKEN)
    pools = [
        replace(market("wrong-factory", first=token, depth=9, protocol=protocol), factory=ROUTER),
        replace(
            market("excluded", first=token, depth=8, protocol=protocol), factory=factory.lower()
        ),
        replace(market("chosen", first=token, depth=2, protocol=protocol), factory=factory.lower()),
        replace(
            market("shallow", first=token, depth=1, protocol=protocol), factory=factory.lower()
        ),
    ]
    service, seen, _ = graph(monkeypatch, pools, {"chosen": 2, "shallow": 9})
    monkeypatch.setattr(_routing, "quote_service", lambda: service)
    resolve = AsyncMock(return_value=BLOCK)
    monkeypatch.setattr(BlockRef, "resolve", resolve)
    price = AsyncMock(wraps=service.price)
    monkeypatch.setattr(service, "price", price)
    adapter = instance(v3.UniswapV3)
    adapter._factory = factory
    result = await adapter.get_price(
        address_form(kind),
        block_number,
        ignore_pools=("excluded",),
        skip_cache=skip_cache,
        sync=False,
    )
    assert result is not None and float(result) == 2
    assert seen == [("chosen", token, 1000000, USD)]
    resolve.assert_awaited_once_with(block_number)
    price.assert_awaited_once_with(
        convert.to_address(token),
        BLOCK,
        None,
        ignored=frozenset({"excluded"}),
        dependencies=(),
        skip_cache=skip_cache,
        first_markets=(factory.lower(),),
    )


@run_async_test
@pytest.mark.parametrize("token", ["invalid", b"\x01" * 21])
async def test_v3_invalid_address_fails_before_routing(monkeypatch: Any, token: Any) -> None:
    route = AsyncMock()
    monkeypatch.setattr(_routing, "liquidity_price", route)
    adapter = instance(v3.UniswapV3)
    adapter._factory = ROUTER
    with pytest.raises(ValueError):
        await adapter.get_price(token, BLOCK.number, sync=False)
    route.assert_not_awaited()
