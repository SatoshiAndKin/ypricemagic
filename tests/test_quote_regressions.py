"""Regression cases for request-wide fallback and native quote contracts."""

from collections import Counter
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from web3.exceptions import ContractLogicError

from tests.test_amount_quotes import BLOCK, CHILD, TOKEN, USD, graph, market
from tests.test_pricing_correctness import run_async_test
from y.datatypes import QuoteAsset, QuoteStep
from y.prices import _markets, _redemptions, _rpc
from y.prices._routing import QuoteService


@run_async_test
async def test_wrapper_dead_ends_do_not_retry_edges_in_other_prefixes(monkeypatch: Any) -> None:
    tokens = [f"0x{i:040x}" for i in range(100, 109)]
    wrappers = [f"0x{i:040x}" for i in range(200, 208)]
    pools = [
        market(f"pool-{level}-{choice}", first=token, second=wrapper)
        for level, (token, wrapper) in enumerate(zip(tokens, wrappers))
        for choice in range(2)
    ]
    service, seen, _ = graph(monkeypatch, pools)
    monkeypatch.setattr(service, "redeem", QuoteService.redeem.__get__(service))
    redemptions: Counter[str] = Counter()

    async def redeem(asset: QuoteAsset, *args: Any) -> Any:
        if asset.token not in wrappers:
            return None
        redemptions[asset.token] += 1
        output = replace(asset, token=tokens[wrappers.index(asset.token) + 1])
        return (
            QuoteStep(
                "redemption",
                "ERC4626",
                asset.token,
                asset,
                (output,),
                "previewRedeem",
                "included",
                "unverified",
            ),
            (),
        )

    monkeypatch.setattr(_redemptions, "redeem", redeem)
    assert await service.price(tokens[0], BLOCK, 1) is None
    attempts = Counter((pool, token, output) for pool, token, _, output in seen)
    assert len(attempts) == 16
    assert set(attempts.values()) == {1}
    assert redemptions == Counter({wrapper: 1 for wrapper in wrappers})


@run_async_test
@pytest.mark.parametrize("sale,redemption,expected", [(2, 1, 2), (1, 2, 2), (2, 2, 2)])
async def test_intermediate_wrapper_compares_both_exits(
    monkeypatch: Any, sale: int, redemption: int, expected: int
) -> None:
    service, seen, _ = graph(
        monkeypatch,
        [market("input", second=CHILD), market("sale", first=CHILD)],
        {"sale": sale},
    )
    monkeypatch.setattr(service, "redeem", QuoteService.redeem.__get__(service))

    async def redeem(asset: QuoteAsset, *args: Any) -> Any:
        if asset.token != CHILD:
            return None
        return (
            QuoteStep(
                "redemption",
                "ERC4626",
                CHILD,
                asset,
                (replace(asset, token=USD, amount=asset.amount * redemption),),
                "previewRedeem",
                "included",
                "unverified",
            ),
            (),
        )

    monkeypatch.setattr(_redemptions, "redeem", redeem)
    result = await service.price(TOKEN, BLOCK, 100)
    assert result is not None and result.quote is not None
    assert result.quote.total_usd == 100 * expected
    assert [row[0] for row in seen] == ["input", "sale"]
    assert result.quote.steps[-1].kind == ("redemption" if redemption > sale else "swap")


@run_async_test
@pytest.mark.parametrize(
    "protocol,fee,spacing", [("Uniswap V3", 3000, None), ("Slipstream", 0, 60)]
)
async def test_v3_quote_encodes_the_protocol_pool_key(
    monkeypatch: Any, protocol: str, fee: int, spacing: int | None
) -> None:
    from y.contracts import Contract

    quote = AsyncMock(return_value=(997000, [], [], 1))
    monkeypatch.setattr(
        Contract,
        "coroutine",
        AsyncMock(return_value=SimpleNamespace(quoteExactInput=SimpleNamespace(coroutine=quote))),
    )
    monkeypatch.setattr(_markets, "read", AsyncMock(return_value=6))
    pool = _markets.Market(
        protocol=protocol,
        pool="pool",
        router="quoter",
        fee=fee,
        tick_spacing=spacing,
        tokens=(TOKEN, USD),
        balances=(0, 0),
    )
    result = await _markets.swap(pool, QuoteAsset(TOKEN, 1000000, 6), USD, BLOCK)
    assert result is not None and result.outputs == (QuoteAsset(USD, 997000, 6),)
    path, amount = quote.call_args.args
    assert amount == 1000000
    assert path == bytes.fromhex(TOKEN[2:]) + (fee if spacing is None else spacing).to_bytes(
        3, "big", signed=spacing is not None
    ) + bytes.fromhex(USD[2:])
    assert quote.call_args.kwargs["block_identifier"] == {
        "blockHash": BLOCK.hash,
        "requireCanonical": True,
    }


@run_async_test
async def test_reorg_cannot_cache_number_based_state_under_another_hash(monkeypatch: Any) -> None:
    other = replace(BLOCK, hash="0x" + "cd" * 32)
    current = other
    calls = []

    async def call(transaction: Any, *, block_identifier: Any) -> bytes:
        block_id = block_identifier
        calls.append(block_id)
        if isinstance(block_id, dict):
            assert block_id == {"blockHash": BLOCK.hash, "requireCanonical": True}
            if current != BLOCK:
                raise RuntimeError("block is not canonical")
            return (111).to_bytes(32, "big")
        return (222 if current == other else 111).to_bytes(32, "big")

    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=call)))
    monkeypatch.setattr(_rpc, "state_cache", lambda: cache)
    from y.prices._quote import SharedCache

    cache: SharedCache[Any] = SharedCache(10)
    with pytest.raises(RuntimeError, match="not canonical"):
        await _rpc.state(TOKEN, "totalSupply()(uint256)", BLOCK)
    assert not cache.values
    current = BLOCK
    assert await _rpc.state(TOKEN, "totalSupply()(uint256)", BLOCK) == 111
    assert await _rpc.state(TOKEN, "totalSupply()(uint256)", BLOCK) == 111
    assert len(calls) == 2


@run_async_test
@pytest.mark.parametrize("coin_type", ["uint256", "int128"])
@pytest.mark.parametrize("balance_type", ["uint256", "int128"])
async def test_curve_getter_versions_share_the_same_hash_snapshot(
    monkeypatch: Any, coin_type: str, balance_type: str
) -> None:
    from y.prices._quote import SharedCache

    calls = []
    cache: SharedCache[Any] = SharedCache(10)
    monkeypatch.setattr(_markets, "state_cache", lambda: cache)

    async def read(pool: str, signature: str, block: Any, index: int) -> Any:
        assert block == BLOCK
        calls.append((signature, index))
        if index >= 2:
            raise ContractLogicError("execution reverted")
        if signature == f"coins({coin_type})(address)":
            return (TOKEN, USD)[index]
        if signature == f"balances({balance_type})(uint256)":
            return (1000000, 2000000)[index]
        raise ContractLogicError("execution reverted")

    monkeypatch.setattr(_rpc, "read", read)
    monkeypatch.setattr(_markets, "read", read)
    snapshot = await _markets.curve_pool_state(CHILD, BLOCK)
    assert snapshot is not None
    assert snapshot.tokens == (TOKEN, USD)
    assert snapshot.depth(TOKEN) == 1000000
    assert snapshot.depth(USD) == 2000000
    count = len(calls)
    assert await _markets.curve_pool_state(CHILD, BLOCK) == snapshot
    assert len(calls) == count


@run_async_test
async def test_curve_getter_detection_propagates_rpc_failure(monkeypatch: Any) -> None:
    from y.prices._quote import SharedCache

    cache: SharedCache[Any] = SharedCache(10)
    monkeypatch.setattr(_markets, "state_cache", lambda: cache)
    monkeypatch.setattr(_rpc, "read", AsyncMock(side_effect=RuntimeError("RPC failed")))
    with pytest.raises(RuntimeError, match="RPC failed"):
        await _markets.curve_pool_state(CHILD, BLOCK)
    assert not cache.values


@run_async_test
async def test_terminal_feed_and_values_use_the_same_fork_hash(monkeypatch: Any) -> None:
    import importlib

    from tests.test_pricing_correctness import instance

    module = importlib.import_module("y.prices.chainlink")
    oracle = instance(module.Chainlink)
    oracle.asynchronous = True
    oracle.registry = "0x0000000000000000000000000000000000000200"
    oracle._feeds = []
    oracle._feeds_from_events = None
    other = replace(BLOCK, hash="0x" + "cd" * 32)
    calls = []
    monkeypatch.setattr(module, "deployed", AsyncMock(return_value=True))

    async def read(contract: str, signature: str, block: Any, *args: Any) -> Any:
        calls.append((contract.lower(), signature, block.hash))
        if signature.startswith("getFeed"):
            return TOKEN if block == BLOCK else CHILD
        if signature.startswith("latestTimestamp"):
            return BLOCK.timestamp
        if signature.startswith("latestAnswer"):
            return 100000000 if block == BLOCK else 200000000
        assert signature == "decimals()(uint256)"
        return 8

    monkeypatch.setattr(module, "read", read)
    monkeypatch.setattr(_rpc, "read", read)
    assert await oracle.get_price(USD, BLOCK, sync=False) == 1
    assert await oracle.get_price(USD, other, sync=False) == 2
    count = len(calls)
    assert await oracle.get_price(USD, BLOCK, sync=False) == 1
    assert len(calls) == count
    for contract, signature, block_hash in calls:
        if not signature.startswith("getFeed"):
            assert contract == (TOKEN if block_hash == BLOCK.hash else CHILD)
    assert {block_hash for _, _, block_hash in calls} == {BLOCK.hash, other.hash}


@run_async_test
async def test_cached_quote_still_requires_a_canonical_block(monkeypatch: Any) -> None:
    service, seen, _ = graph(monkeypatch, [market("sale")])
    assert await service.price(TOKEN, BLOCK, 100) is not None
    monkeypatch.setattr(type(BLOCK), "verify", AsyncMock(side_effect=RuntimeError("block changed")))
    with pytest.raises(RuntimeError, match="block changed"):
        await service.price(TOKEN, BLOCK, 100)
    assert len(seen) == 1
