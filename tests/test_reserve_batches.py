"""Bound reserve reads without changing block identity or candidate ordering."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientResponseError
from dank_mids.brownie_patch import dank_web3
from eth_abi.abi import encode
from hexbytes import HexBytes
from multicall import Call

from tests.test_pricing_correctness import run_async_test
from y.prices import _rpc
from y.prices._quote import bounded_async_map

ADDRESSES = tuple(f"0x{i:040x}" for i in range(1, 4))
BLOCK = _rpc.BlockRef(1, 20_000_000, "0x" + "12" * 32, 1)


@run_async_test
async def test_full_balance_getter_batch_retains_every_value_and_limit(monkeypatch: Any) -> None:
    _rpc.balance_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    requests = tuple((ADDRESSES[0], f"0x{index:040x}") for index in range(6250))
    outputs = [(True, encode(["uint256"], [index])) for index in range(6250)]
    aggregate = AsyncMock(return_value=(BLOCK.number, 0, outputs))
    monkeypatch.setattr(_rpc, "_reserve_aggregate", aggregate)
    assert await _rpc.balances_batch(requests, BLOCK) == tuple(range(6250))
    assert aggregate.call_args.args[2] is BLOCK
    assert len(aggregate.call_args.args[4]) == 6250
    with pytest.raises(ValueError, match="6250"):
        await _rpc.balances_batch((*requests, requests[0]), BLOCK)


@run_async_test
async def test_full_code_batches_preserve_order_and_bound_transport_chunks(
    monkeypatch: Any,
) -> None:
    _rpc.code_cache.cache_clear()
    addresses = tuple(f"0x{index:040x}" for index in range(16385))
    observed: list[tuple[str, ...]] = []

    async def presence(chunk: tuple[str, ...], block: _rpc.BlockRef) -> tuple[bool, ...]:
        assert block is BLOCK
        observed.append(chunk)
        return tuple(bool(int(address, 16) % 2) for address in chunk)

    monkeypatch.setattr(_rpc, "_code_presence", presence)
    assert await _rpc.deployed_batch(addresses, BLOCK) == tuple(
        bool(index % 2) for index in range(16385)
    )
    assert sorted(map(len, observed)) == [1, 8192, 8192]


@run_async_test
async def test_full_reserve_getter_batch_retains_every_value_and_limit(monkeypatch: Any) -> None:
    _rpc.reserve_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    addresses = tuple(f"0x{index:040x}" for index in range(7500))
    values = tuple((index, index + 1, 2**255 + index) for index in range(7500))
    outputs = [(True, encode(["uint256"] * 3, value)) for value in values]
    aggregate = AsyncMock(return_value=(BLOCK.number, 0, outputs))
    monkeypatch.setattr(_rpc, "_reserve_aggregate", aggregate)
    assert await _rpc.reserves_batch(addresses, BLOCK) == values
    assert aggregate.call_args.args[2] is BLOCK
    assert len(aggregate.call_args.args[4]) == 7500
    with pytest.raises(ValueError, match="7500"):
        await _rpc.reserves_batch((*addresses, addresses[0]), BLOCK)


@run_async_test
@pytest.mark.parametrize("kind", ["reserves", "balances", "vault"])
@pytest.mark.parametrize("status", [413, 400])
async def test_native_batches_split_payload_limits_and_propagate_other_http_errors(
    monkeypatch: Any, kind: str, status: int
) -> None:
    _rpc.reserve_cache.cache_clear()
    _rpc.balance_cache.cache_clear()
    _rpc.vault_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    types = {
        "reserves": ["uint256"] * 3,
        "balances": ["uint256"],
        "vault": ["address[]", "uint256[]", "uint256"],
    }[kind]
    value = {
        "reserves": (123, 456, 789),
        "balances": (123,),
        "vault": ((ADDRESSES[1],), (123,), 789),
    }[kind]
    payload = encode(types, value)
    error = ClientResponseError(cast(Any, None), (), status=status)
    aggregate = AsyncMock(
        side_effect=[
            error,
            (BLOCK.number, 0, [(True, payload)]),
            (BLOCK.number, 0, [(True, payload)]),
        ]
    )
    monkeypatch.setattr(_rpc, "_reserve_aggregate", aggregate)
    if kind == "reserves":
        work = _rpc.reserves_batch(ADDRESSES[:2], BLOCK)
        expected: Any = (value, value)
    elif kind == "balances":
        work = _rpc.balances_batch(
            ((ADDRESSES[0], ADDRESSES[1]), (ADDRESSES[0], ADDRESSES[2])), BLOCK
        )
        expected = (123, 123)
    else:
        work = _rpc.pool_tokens_batch(ADDRESSES[0], (bytes(32), bytes.fromhex("ab" * 32)), BLOCK)
        expected = (value, value)
    if status == 400:
        with pytest.raises(ClientResponseError) as raised:
            await work
        assert raised.value is error and aggregate.await_count == 1
    else:
        assert await work == expected
        assert [len(call.args[4]) for call in aggregate.await_args_list] == [2, 1, 1]
        assert all(call.args[2] is BLOCK for call in aggregate.await_args_list)


@run_async_test
async def test_code_probe_splits_payload_limits_at_the_same_hash(monkeypatch: Any) -> None:
    from web3 import AsyncHTTPProvider

    provider = AsyncHTTPProvider("test")
    request = AsyncMock(
        side_effect=[
            ClientResponseError(cast(Any, None), (), status=413),
            {"result": "0x" + encode(["bool"], [True]).hex()},
            {"result": "0x" + encode(["bool", "bool"], [False, True]).hex()},
        ]
    )
    monkeypatch.setattr(provider, "make_request", request)
    monkeypatch.setattr(dank_web3.eth.w3, "provider", provider)
    assert await _rpc._code_presence(ADDRESSES, BLOCK) == (True, False, True)
    assert [len(call.args[1][0]["data"][2:]) // 64 for call in request.await_args_list] == [3, 1, 2]
    assert all(call.args[1][1] == BLOCK.identifier for call in request.await_args_list)


@run_async_test
async def test_vault_batches_preserve_dynamic_values_order_and_hash(monkeypatch: Any) -> None:
    _rpc.vault_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    ids = tuple(index.to_bytes(32, "big") for index in range(3))
    values: tuple[tuple[list[str], list[int], int], ...] = (
        ([ADDRESSES[0]], [2**255], 19),
        ([], [], 0),
        (list(ADDRESSES), [0, 123, 456], 21),
    )
    outputs = [(True, encode(["address[]", "uint256[]", "uint256"], value)) for value in values]
    aggregate = AsyncMock(return_value=(BLOCK.number, 0, outputs))
    monkeypatch.setattr(_rpc, "_reserve_aggregate", aggregate)
    expected = tuple(
        (tuple(tokens), tuple(balances), changed) for tokens, balances, changed in values
    )
    assert await _rpc.pool_tokens_batch(ADDRESSES[0], ids, BLOCK) == expected
    assert await _rpc.pool_tokens_batch(ADDRESSES[0], ids, BLOCK) == expected
    assert aggregate.await_count == 1
    args = aggregate.call_args.args
    assert args[2] is BLOCK
    assert len(args[4]) == 3 and all(target.lower() == ADDRESSES[0] for target, _ in args[4])
    changed = _rpc.BlockRef(1, BLOCK.number, "0x" + "ab" * 32, 1)
    assert await _rpc.pool_tokens_batch(ADDRESSES[0], ids, changed) == expected
    assert aggregate.await_count == 2


@run_async_test
@pytest.mark.parametrize("success,output", [(False, b""), (True, b"\x00")])
async def test_vault_member_fallback_propagates_transient_failure_and_recovers(
    monkeypatch: Any, success: bool, output: bytes
) -> None:
    _rpc.vault_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    aggregate = AsyncMock(return_value=(BLOCK.number, 0, [(success, output)]))
    monkeypatch.setattr(_rpc, "_reserve_aggregate", aggregate)
    fallback = AsyncMock(side_effect=[ConnectionError("offline"), ((ADDRESSES[1],), (123,), 9)])
    monkeypatch.setattr(_rpc, "state", fallback)
    pool_id = bytes(32)
    with pytest.raises(ConnectionError, match="offline"):
        await _rpc.pool_tokens_batch(ADDRESSES[0], (pool_id,), BLOCK)
    assert await _rpc.pool_tokens_batch(ADDRESSES[0], (pool_id,), BLOCK) == (
        ((ADDRESSES[1],), (123,), 9),
    )
    assert aggregate.await_count == 2
    assert fallback.call_args.args == (
        ADDRESSES[0],
        "getPoolTokens(bytes32)(address[],uint256[],uint256)",
        BLOCK,
        pool_id,
    )


@run_async_test
async def test_vault_batch_before_multicall_deployment_and_limit(monkeypatch: Any) -> None:
    _rpc.vault_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=False))
    fallback = AsyncMock(return_value=((), (), 0))
    monkeypatch.setattr(_rpc, "state", fallback)
    assert await _rpc.pool_tokens_batch(ADDRESSES[0], (bytes(32),), BLOCK) == (((), (), 0),)
    with pytest.raises(ValueError, match="128"):
        await _rpc.pool_tokens_batch(ADDRESSES[0], (bytes(32),) * 129, BLOCK)
    assert fallback.await_count == 1


@run_async_test
@pytest.mark.parametrize("outputs", [(BLOCK.number - 1, 0, []), (BLOCK.number, 0, [])])
async def test_vault_aggregate_block_and_count_must_match(monkeypatch: Any, outputs: Any) -> None:
    _rpc.vault_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    monkeypatch.setattr(_rpc, "_reserve_aggregate", AsyncMock(return_value=outputs))
    with pytest.raises(RuntimeError, match="different block or result count"):
        await _rpc.pool_tokens_batch(ADDRESSES[0], (bytes(32),), BLOCK)


@run_async_test
async def test_vault_batch_splits_provider_rejection_without_changing_hash(
    monkeypatch: Any,
) -> None:
    _rpc.vault_cache.cache_clear()
    monkeypatch.setattr(_rpc, "deployed", AsyncMock(return_value=True))
    payload = encode(["address[]", "uint256[]", "uint256"], [[ADDRESSES[1]], [123], 9])
    aggregate = AsyncMock(
        side_effect=[
            ValueError("out of gas"),
            (BLOCK.number, 0, [(True, payload)]),
            (BLOCK.number, 0, [(True, payload)]),
        ]
    )
    monkeypatch.setattr(_rpc, "_reserve_aggregate", aggregate)
    ids = (bytes(32), bytes.fromhex("ab" * 32))
    assert (
        await _rpc.pool_tokens_batch(ADDRESSES[0], ids, BLOCK)
        == (((ADDRESSES[1],), (123,), 9),) * 2
    )
    assert [len(item.args[4]) for item in aggregate.await_args_list] == [2, 1, 1]
    assert all(item.args[2] is BLOCK for item in aggregate.await_args_list)


@pytest.mark.parametrize("count", [0, 1, 17, 4096])
@pytest.mark.parametrize("rpc_wrapper", [False, True])
def test_canonical_aggregate_decoder_matches_native_codec(count: int, rpc_wrapper: bool) -> None:
    signature = "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])"
    call = Call(ADDRESSES[0], signature)
    members = tuple(
        (bool(index % 2), bytes([index % 256]) * (index % 99)) for index in range(count)
    )
    payload = encode(["uint256", "uint256", "(bool,bytes)[]"], [2**256 - 1, 2**255, members])
    if rpc_wrapper:
        payload = HexBytes(payload)
    assert _rpc._decode_batch_output(payload, call) == Call.decode_output(payload, call.signature)
    assert _rpc._canonical_aggregate(payload) == (2**256 - 1, 2**255, members)
    result = _rpc._canonical_aggregate(payload)
    assert result is not None and all(type(value) is bytes for _, value in result[2])


@pytest.mark.parametrize(
    "mutation",
    [
        "short",
        "truncated",
        "offset",
        "size",
        "tuple_offset",
        "bool",
        "bytes_offset",
        "length",
        "padding",
        "trailing",
    ],
)
def test_noncanonical_aggregate_preserves_native_fallback(monkeypatch: Any, mutation: str) -> None:
    call = Call(
        ADDRESSES[0],
        "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])",
    )
    payload = bytearray(
        encode(["uint256", "uint256", "(bool,bytes)[]"], [123, 456, [(True, b"a")]])
    )
    if mutation == "short":
        del payload[64:]
    elif mutation == "truncated":
        del payload[-1:]
    elif mutation == "trailing":
        payload.extend(bytes(32))
    else:
        position, value = {
            "offset": (64, 128),
            "size": (96, 2**256 - 1),
            "tuple_offset": (128, 64),
            "bool": (160, 2),
            "bytes_offset": (192, 96),
            "length": (224, 2**256 - 1),
            "padding": (256, 1),
        }[mutation]
        payload[position : position + 32] = value.to_bytes(32, "big")
    data = bytes(payload)
    expected = Call.decode_output(data, call.signature)
    native = Call.decode_output
    observed = []

    def fallback(*args: Any) -> Any:
        observed.append(args)
        return native(*args)

    monkeypatch.setattr(Call, "decode_output", fallback)
    assert _rpc._decode_batch_output(data, call) == expected
    assert len(observed) == 1


@pytest.mark.parametrize(
    "signature,words",
    [("getReserves()(uint256,uint256,uint256)", 3), ("balanceOf(address)(uint256)", 1)],
)
@pytest.mark.parametrize("value", [0, 1, 2**112 - 1, 2**255, 2**256 - 1])
@pytest.mark.parametrize("suffix", [b"", b"\x00", bytes(32)])
def test_fixed_getter_decoder_matches_native_values_and_layouts(
    signature: str, words: int, value: int, suffix: bytes
) -> None:
    call = Call(ADDRESSES[0], signature)
    payload = encode(["uint256"] * words, [value] * words) + suffix
    assert _rpc._decode_batch_output(payload, call) == Call.decode_output(payload, call.signature)


def test_batch_decoder_retains_native_return_handlers() -> None:
    call = Call(
        ADDRESSES[0], "balanceOf(address)(uint256)", returns=[("balance", lambda value: value + 1)]
    )
    assert _rpc._decode_batch_output(encode(["uint256"], [42]), call) == {"balance": 43}


@pytest.mark.parametrize(
    "holder",
    [
        "0x" + "00" * 20,
        "0x" + "ff" * 20,
        "0x4200000000000000000000000000000000000006",
        "0x000000000000000000000000000000000000aBcD",
        "42" * 20,
        bytes.fromhex("42" * 20),
    ],
)
def test_balance_getter_encoder_matches_native_bytes(holder: Any) -> None:
    call = Call(ADDRESSES[0], ["balanceOf(address)(uint256)", holder])
    assert _rpc._getter_call_data(call) == call.data


@pytest.mark.parametrize("holder", ["0x" + "zz" * 20, "0x123", True, 123])
def test_invalid_balance_getter_encoder_retains_native_errors(holder: Any) -> None:
    call = Call(ADDRESSES[0], ["balanceOf(address)(uint256)", holder])
    with pytest.raises(Exception) as native:
        _ = call.data
    with pytest.raises(type(native.value)):
        _rpc._getter_call_data(call)


@pytest.mark.parametrize(
    "signature,args",
    [("getReserves()(uint256,uint256,uint256)", []), ("balanceOf(address)(uint256)", [])],
)
def test_other_getter_encoder_retains_native_behavior(signature: str, args: list[Any]) -> None:
    call = Call(ADDRESSES[0], [signature, *args])
    assert _rpc._getter_call_data(call) == call.data


@pytest.mark.parametrize("count", [0, 1, 17, 4096])
def test_canonical_aggregate_encoder_matches_native_bytes(count: int) -> None:
    members = [[f"0x{index:040x}", bytes([index % 256]) * (index % 99)] for index in range(count)]
    call = Call(
        ADDRESSES[0],
        [
            "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])",
            False,
            members,
        ],
    )
    assert _rpc._batch_call_data(call) == call.data


@pytest.mark.parametrize("require_success", [False, True, 0])
@pytest.mark.parametrize("payload", [b"", b"\x00" * 32, bytearray(b"\x01"), "0x0001"])
def test_aggregate_encoder_retains_native_noncanonical_inputs(
    require_success: object, payload: object
) -> None:
    call = Call(
        ADDRESSES[0],
        [
            "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])",
            require_success,
            [[ADDRESSES[0], payload]],
        ],
    )
    try:
        expected = call.data
    except Exception as error:
        with pytest.raises(type(error)):
            _rpc._batch_call_data(call)
    else:
        assert _rpc._batch_call_data(call) == expected


@pytest.mark.parametrize("target", ["0x123", "0x" + "zz" * 20, "0x" + " " * 40])
def test_aggregate_encoder_retains_native_invalid_address_errors(target: str) -> None:
    call = Call(
        ADDRESSES[0],
        [
            "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])",
            False,
            [[target, b""]],
        ],
    )
    with pytest.raises(Exception) as primary:
        _ = call.data
    with pytest.raises(type(primary.value)):
        _rpc._batch_call_data(call)


def test_aggregate_encoder_retains_native_prefixless_address_support() -> None:
    call = Call(
        ADDRESSES[0],
        [
            "tryBlockAndAggregate(bool,(address,bytes)[])(uint256,uint256,(bool,bytes)[])",
            False,
            [["12" * 20, b""]],
        ],
    )
    assert _rpc._batch_call_data(call) == call.data


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
