"""Bound reserve reads without changing block identity or candidate ordering."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from dank_mids.brownie_patch import dank_web3
from eth_abi.abi import encode

from tests.test_pricing_correctness import run_async_test
from y.prices import _rpc
from y.prices._quote import bounded_async_map

ADDRESSES = tuple(f"0x{i:040x}" for i in range(1, 4))
BLOCK = _rpc.BlockRef(1, 20_000_000, "0x" + "12" * 32, 1)


@run_async_test
async def test_reserves_retain_native_values_order_and_canonical_hash(monkeypatch: Any) -> None:
    _rpc.reserve_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    values = [(11, 22, 33), (0, 0, 9), (2**112 - 1, 5, 17)]
    read = AsyncMock(
        return_value=(BLOCK.number, 0, [(True, encode(["uint256"] * 3, v)) for v in values])
    )
    monkeypatch.setattr(_rpc, "_reserve_aggregate", read)
    assert await _rpc.reserves_batch(ADDRESSES, BLOCK) == tuple(values)
    assert await _rpc.reserves_batch(ADDRESSES, BLOCK) == tuple(values)
    assert read.await_count == 1
    args = read.call_args.args
    assert args[2] is BLOCK and args[2].identifier == {
        "blockHash": BLOCK.hash,
        "requireCanonical": True,
    }
    assert [item[0].lower() for item in args[4]] == list(ADDRESSES)
    changed = _rpc.BlockRef(1, BLOCK.number, "0x" + "13" * 32, 1)
    assert await _rpc.reserves_batch(ADDRESSES, changed) == tuple(values)
    assert read.await_count == 2


@run_async_test
async def test_failed_aggregate_member_uses_native_read_and_transient_failure_is_not_cached(
    monkeypatch: Any,
) -> None:
    _rpc.reserve_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    read = AsyncMock(return_value=(BLOCK.number, 0, [(False, b"")]))
    monkeypatch.setattr(_rpc, "_reserve_aggregate", read)
    fallback = AsyncMock(side_effect=[ConnectionError("offline"), (3, 4, 5)])
    monkeypatch.setattr(_rpc, "state", fallback)
    with pytest.raises(ConnectionError, match="offline"):
        await _rpc.reserves_batch(ADDRESSES[:1], BLOCK)
    assert await _rpc.reserves_batch(ADDRESSES[:1], BLOCK) == ((3, 4, 5),)
    assert read.await_count == 2
    assert fallback.call_args.args == (
        ADDRESSES[0],
        "getReserves()(uint256,uint256,uint256)",
        BLOCK,
    )


@run_async_test
async def test_before_multicall_deployment_uses_native_getters(monkeypatch: Any) -> None:
    _rpc.reserve_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=False))
    read = AsyncMock(side_effect=AssertionError("aggregate before deployment"))
    monkeypatch.setattr(_rpc, "_reserve_aggregate", read)
    fallback = AsyncMock(side_effect=[(i, i + 1, 3) for i in range(3)])
    monkeypatch.setattr(_rpc, "state", fallback)
    assert await _rpc.reserves_batch(ADDRESSES, BLOCK) == ((0, 1, 3), (1, 2, 3), (2, 3, 3))
    read.assert_not_called()


@run_async_test
@pytest.mark.parametrize("outputs", [(19_999_999, 0, []), (20_000_000, 0, [])])
async def test_aggregate_block_and_result_count_must_match(monkeypatch: Any, outputs: Any) -> None:
    _rpc.reserve_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    monkeypatch.setattr(_rpc, "_reserve_aggregate", AsyncMock(return_value=outputs))
    with pytest.raises(RuntimeError, match="different block or result count"):
        await _rpc.reserves_batch(ADDRESSES, BLOCK)


@run_async_test
async def test_async_batches_bound_work_keep_order_and_cancel_owned_tasks() -> None:
    started: list[int] = []
    finished: list[int] = []
    gates = [asyncio.Event() for _ in range(9)]

    async def source() -> AsyncIterator[int]:
        for i in range(9):
            yield i

    async def work(i: int) -> int:
        started.append(i)
        try:
            await gates[i].wait()
            return i
        finally:
            finished.append(i)

    iterator = cast(AsyncGenerator[int, None], bounded_async_map(work, source(), workers=3))

    async def next_item() -> int:
        return await anext(iterator)

    first = asyncio.create_task(next_item())
    while len(started) < 3:
        await asyncio.sleep(0)
    assert started == [0, 1, 2]
    gates[2].set()
    gates[1].set()
    await asyncio.sleep(0)
    assert not first.done()
    gates[0].set()
    assert await first == 0
    second = asyncio.create_task(next_item())
    assert await second == 1
    await asyncio.sleep(0)
    await iterator.aclose()
    assert sorted(finished) == [0, 1, 2, 3]
    assert started == [0, 1, 2, 3]


@run_async_test
async def test_explicit_aggregate_transport_retains_canonical_hash(monkeypatch: Any) -> None:
    from types import SimpleNamespace

    encoded = encode(["uint256", "uint256", "(bool,bytes)[]"], [BLOCK.number, 0, [(True, b"abc")]])
    provider = SimpleNamespace(
        make_request=AsyncMock(return_value={"result": "0x" + encoded.hex()})
    )
    monkeypatch.setattr(
        _rpc,
        "dank_web3",
        SimpleNamespace(eth=SimpleNamespace(w3=SimpleNamespace(provider=provider))),
    )
    result = await _rpc._reserve_aggregate(
        ADDRESSES[0],
        "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])",
        BLOCK,
        False,
        [],
    )
    assert result == (BLOCK.number, 0, ((True, b"abc"),))
    method, params = provider.make_request.call_args.args
    assert method == "eth_call"
    assert params[1] == BLOCK.identifier
    assert params[0]["to"].lower() == ADDRESSES[0]
    assert params[0]["data"].startswith("0x")


@run_async_test
async def test_reserve_gas_splitting_preserves_every_pair(monkeypatch: Any) -> None:
    _rpc.reserve_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    calls = []

    async def aggregate(address: Any, signature: Any, block: Any, success: Any, args: Any) -> Any:
        targets = [item[0].lower() for item in args]
        calls.append(targets)
        if len(targets) > 1:
            raise ValueError("out of gas")
        value = int(targets[0], 16)
        return BLOCK.number, 0, [(True, encode(["uint256"] * 3, [value, 2, 3]))]

    monkeypatch.setattr(_rpc, "_reserve_aggregate", aggregate)
    assert await _rpc.reserves_batch(ADDRESSES, BLOCK) == ((1, 2, 3), (2, 2, 3), (3, 2, 3))
    assert calls == [
        list(ADDRESSES),
        [ADDRESSES[0]],
        list(ADDRESSES[1:]),
        [ADDRESSES[1]],
        [ADDRESSES[2]],
    ]


@run_async_test
async def test_balance_batches_keep_order_hash_and_individual_failure_contract(
    monkeypatch: Any,
) -> None:
    _rpc.balance_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    requests = ((ADDRESSES[0], ADDRESSES[2]), (ADDRESSES[1], ADDRESSES[2]))
    aggregate = AsyncMock(
        return_value=(BLOCK.number, 0, [(True, encode(["uint256"], [19])), (False, b"")])
    )
    monkeypatch.setattr(_rpc, "_reserve_aggregate", aggregate)
    fallback = AsyncMock(side_effect=[ConnectionError("offline"), 0])
    monkeypatch.setattr(_rpc, "state", fallback)
    with pytest.raises(ConnectionError, match="offline"):
        await _rpc.balances_batch(requests, BLOCK)
    assert await _rpc.balances_batch(requests, BLOCK) == (19, 0)
    assert await _rpc.balances_batch(requests, BLOCK) == (19, 0)
    assert aggregate.await_count == 2
    assert fallback.call_args.args == (
        ADDRESSES[1],
        "balanceOf(address)(uint256)",
        BLOCK,
        ADDRESSES[2],
    )
    args = aggregate.call_args.args
    assert args[2] is BLOCK
    assert [call[0].lower() for call in args[4]] == [request[0] for request in requests]
    changed = _rpc.BlockRef(1, BLOCK.number, "0x" + "13" * 32, 1)
    with pytest.raises(RuntimeError, match="different block or result count"):
        await _rpc.balances_batch(requests[:1], changed)


@run_async_test
@pytest.mark.parametrize("error", ["provider offline", {"code": -32000, "message": "bad"}])
async def test_aggregate_unrelated_errors_propagate(monkeypatch: Any, error: Any) -> None:
    from types import SimpleNamespace

    provider = SimpleNamespace(make_request=AsyncMock(return_value={"error": error}))
    monkeypatch.setattr(
        _rpc,
        "dank_web3",
        SimpleNamespace(eth=SimpleNamespace(w3=SimpleNamespace(provider=provider))),
    )
    with pytest.raises(ValueError):
        await _rpc._reserve_aggregate(ADDRESSES[0], "totalSupply()(uint256)", BLOCK)
    assert provider.make_request.await_count == 1


@run_async_test
async def test_code_batch_matches_response_ids_and_canonical_hash(monkeypatch: Any) -> None:
    from types import SimpleNamespace

    from msgspec import json

    counter = iter(range(3))
    encoded = []

    def encode_request(method: str, params: Any) -> bytes:
        encoded.append((method, params))
        return json.encode(
            {"jsonrpc": "2.0", "id": next(counter), "method": method, "params": params}
        )

    provider = SimpleNamespace(
        encode_rpc_request=encode_request, endpoint_uri="test", get_request_kwargs=lambda: {}
    )
    monkeypatch.setattr(
        _rpc,
        "dank_web3",
        SimpleNamespace(eth=SimpleNamespace(w3=SimpleNamespace(provider=provider))),
    )
    post = AsyncMock(
        return_value=json.encode(
            [{"id": 2, "result": "0x01"}, {"id": 0, "result": "0x"}, {"id": 1, "result": "0x00"}]
        )
    )
    monkeypatch.setattr(_rpc, "async_make_post_request", post)
    assert await _rpc._codes_batch(ADDRESSES, BLOCK) == (False, True, True)
    assert encoded == [("eth_getCode", [address, BLOCK.identifier]) for address in ADDRESSES]
    assert len(json.decode(post.call_args.args[1])) == 3
    post.return_value = json.encode([{"id": 3, "result": "0x01"}] * 3)
    counter = iter(range(3))
    with pytest.raises(RuntimeError, match="different response IDs"):
        await _rpc._codes_batch(ADDRESSES, BLOCK)


@run_async_test
async def test_rate_limit_recovery_and_exhaustion_remain_transient(monkeypatch: Any) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    request = AsyncMock(side_effect=[ValueError({"code": 429}), 17])
    assert await _rpc._retry_state_read(request) == 17
    assert request.await_count == 2
    request = AsyncMock(side_effect=ValueError({"code": 429}))
    with pytest.raises(ConnectionError, match="rate limit"):
        await _rpc._retry_state_read(request)
    assert request.await_count == 5


@run_async_test
@pytest.mark.parametrize(
    "output", [encode(["bool", "bool"], [True, False]), b"", encode(["uint256", "uint256"], [2, 0])]
)
async def test_code_probe_preserves_hash_values_and_checks_shape(
    monkeypatch: Any, output: bytes
) -> None:
    from web3 import AsyncHTTPProvider

    provider = AsyncHTTPProvider("test")
    request = AsyncMock(return_value={"result": "0x" + output.hex()})
    monkeypatch.setattr(provider, "make_request", request)
    monkeypatch.setattr(dank_web3.eth.w3, "provider", provider)
    if len(output) != 64 or output[:32] == (2).to_bytes(32):
        with pytest.raises(RuntimeError):
            await _rpc._code_presence(ADDRESSES[:2], BLOCK)
    else:
        assert await _rpc._code_presence(ADDRESSES[:2], BLOCK) == (True, False)
    method, params = request.call_args.args
    assert method == "eth_call"
    assert params[1] == BLOCK.identifier
    assert params[2] == {_rpc._CODE_PROBE: {"code": _rpc._CODE_RUNTIME}}
    assert params[0]["data"] == "0x" + "".join(address[2:].zfill(64) for address in ADDRESSES[:2])


@run_async_test
@pytest.mark.parametrize(
    "error,fallback", [("state overrides are not supported", True), ("bad state", False)]
)
async def test_code_probe_falls_back_only_for_unsupported_providers(
    monkeypatch: Any, error: str, fallback: bool
) -> None:
    from web3 import AsyncHTTPProvider

    provider = AsyncHTTPProvider("test")
    request = AsyncMock(return_value={"error": {"code": -32602, "message": error}})
    monkeypatch.setattr(provider, "make_request", request)
    monkeypatch.setattr(dank_web3.eth.w3, "provider", provider)
    native = AsyncMock(return_value=(True, False, True))
    monkeypatch.setattr(_rpc, "_codes_batch", native)
    if fallback:
        assert await _rpc._code_presence(ADDRESSES, BLOCK) == (True, False, True)
        assert await _rpc._code_presence(ADDRESSES, BLOCK) == (True, False, True)
        assert request.await_count == 1
        assert native.await_count == 2
        assert native.call_args.args == (ADDRESSES, BLOCK)
    else:
        with pytest.raises(ValueError, match="bad state"):
            await _rpc._code_presence(ADDRESSES, BLOCK)
        native.assert_not_called()
