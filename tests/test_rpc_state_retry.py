"""Retry transient archive-state misses without changing the requested block."""

import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from eth_abi.abi import decode, encode
from eth_utils.crypto import keccak
from hexbytes import HexBytes

from tests.rpc_fixtures import native_rpc
from tests.test_amount_quotes import BLOCK, TOKEN
from tests.test_pricing_correctness import Ready, run_async_test
from y.contracts import Contract
from y.prices import _rpc
from y.prices._quote import SharedCache
from y.prices.lending.compound import CToken


def state_error() -> ValueError:
    return ValueError({"code": -32000, "message": f"historical state {'ab' * 32} is not available"})


@run_async_test
@pytest.mark.parametrize("method", ["call", "get_code"])
async def test_archive_state_retry_preserves_hash_and_decodes(
    monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    response = (
        HexBytes(encode(["uint256"], [123456789])) if method == "call" else HexBytes("0x6000")
    )
    rpc = AsyncMock(side_effect=[state_error(), state_error(), response])
    monkeypatch.setattr(
        _rpc,
        "dank_web3",
        native_rpc(rpc) if method == "call" else SimpleNamespace(eth=SimpleNamespace(get_code=rpc)),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr(_rpc, "state_cache", lambda: SharedCache(8))
    if method == "call":
        assert await _rpc.read(TOKEN, "totalSupply()(uint256)", BLOCK) == 123456789
        assert rpc.await_args_list[0].kwargs["block_identifier"] == BLOCK.identifier
    else:
        assert await _rpc.deployed(TOKEN, BLOCK) is True
        assert rpc.await_args_list[0].args[1] == BLOCK.identifier
    assert rpc.await_count == 3
    assert rpc.await_args_list == [rpc.await_args_list[0]] * 3
    assert sleep.await_args_list == [call(0.5), call(1.0)]


@run_async_test
async def test_archive_state_retry_is_bounded_and_never_optional(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = state_error()
    rpc = AsyncMock(side_effect=error)
    monkeypatch.setattr(_rpc, "dank_web3", native_rpc(rpc))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(ValueError) as raised:
        await _rpc.optional_read(TOKEN, "totalSupply()(uint256)", BLOCK)
    assert raised.value is error
    assert rpc.await_count == 10
    assert sleep.await_args_list == [
        call(delay) for delay in (0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0, 30.0)
    ]


@run_async_test
@pytest.mark.parametrize(
    "error",
    [
        ValueError({"code": -32001, "message": f"historical state {'ab' * 32} is not available"}),
        ValueError({"code": -32000, "message": "header not found"}),
        ValueError({"code": -32000, "message": "execution reverted"}),
        ValueError("historical state unavailable"),
        TypeError("unexpected decoder failure"),
        asyncio.CancelledError(),
    ],
)
async def test_archive_state_retry_propagates_other_errors(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    rpc = AsyncMock(side_effect=error)
    monkeypatch.setattr(_rpc, "dank_web3", native_rpc(rpc))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(type(error)) as raised:
        await _rpc.read(TOKEN, "totalSupply()(uint256)", BLOCK)
    assert raised.value is error
    rpc.assert_awaited_once()
    sleep.assert_not_awaited()


@run_async_test
async def test_archive_state_retry_cancellation_during_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rpc = AsyncMock(side_effect=state_error())
    monkeypatch.setattr(_rpc, "dank_web3", native_rpc(rpc))
    cancelled = asyncio.CancelledError()
    sleep = AsyncMock(side_effect=cancelled)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError) as raised:
        await _rpc.read(TOKEN, "totalSupply()(uint256)", BLOCK)
    assert raised.value is cancelled
    rpc.assert_awaited_once()
    sleep.assert_awaited_once_with(0.5)


@run_async_test
@pytest.mark.parametrize("extra_outputs", [False, True])
@pytest.mark.parametrize("protocol,key", [("Uniswap V3", 3000), ("Slipstream", 60)])
async def test_native_quoter_transport_preserves_path_hash_and_full_input_proof(
    monkeypatch: pytest.MonkeyPatch, extra_outputs: bool, protocol: str, key: int
) -> None:
    import socket

    from aiohttp import ClientSession, web
    from web3 import AsyncHTTPProvider

    from tests.test_amount_quotes import CHILD, USD, market
    from y.datatypes import QuoteAsset
    from y.prices import _markets

    path = bytes.fromhex(TOKEN[2:]) + key.to_bytes(3, "big") + bytes.fromhex(USD[2:])
    reverse = path[-20:] + path[20:23] + path[:20]
    observed: list[tuple[bytes, int]] = []

    async def rpc(request: web.Request) -> web.Response:
        body = await request.json()
        assert body["method"] == "eth_call"
        transaction, identifier = body["params"]
        assert identifier == BLOCK.identifier
        data = HexBytes(transaction["data"])
        if data[:4] == keccak(text="decimals()")[:4]:
            assert transaction["to"].lower() == USD
            result = encode(["uint8"], [6])
        else:
            assert transaction["to"].lower() == CHILD
            packed, amount = decode(["bytes", "uint256"], data[4:])
            observed.append((packed, amount))
            assert data[:4] in (
                keccak(text="quoteExactInput(bytes,uint256)")[:4],
                keccak(text="quoteExactOutput(bytes,uint256)")[:4],
            )
            output = (
                997000 if data[:4] == keccak(text="quoteExactInput(bytes,uint256)")[:4] else 1000002
            )
            result = (
                encode(
                    ["uint256", "uint160[]", "uint32[]", "uint256"], [output, [12345], [1], 99999]
                )
                if extra_outputs
                else encode(["uint256"], [output])
            )
        return web.json_response(
            {"jsonrpc": "2.0", "id": body["id"], "result": "0x" + result.hex()}
        )

    app = web.Application()
    app.router.add_post("/", rpc)
    runner = web.AppRunner(app)
    await runner.setup()
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        await web.SockSite(runner, listener).start()
        provider = AsyncHTTPProvider(f"http://127.0.0.1:{listener.getsockname()[1]}")
        session = await provider.cache_async_session(ClientSession())
        sdk = AsyncMock(side_effect=AssertionError("entered SDK retry queue"))
        abi = AsyncMock(side_effect=AssertionError("unnecessary ABI lookup"))
        monkeypatch.setattr(Contract, "coroutine", abi)
        monkeypatch.setattr(
            _rpc,
            "dank_web3",
            SimpleNamespace(eth=SimpleNamespace(w3=SimpleNamespace(provider=provider), call=sdk)),
        )
        pool = market("pool", protocol=protocol)
        from dataclasses import replace

        pool = replace(pool, router=CHILD, fee=3000, tick_spacing=60)
        try:
            result = await _markets.swap(pool, QuoteAsset(TOKEN, 1000001, 6), USD, BLOCK)
            assert result is not None and result.outputs == (QuoteAsset(USD, 997000, 6),)
            assert observed == [(path, 1000001), (reverse, 997001)]
            assert result.fees == "DEX fees included in native quote"
            sdk.assert_not_awaited()
            abi.assert_not_awaited()
        finally:
            await session.close()
            await runner.cleanup()


@run_async_test
@pytest.mark.parametrize("block", [None, 10_100_000])
async def test_contract_code_forwards_block_identifier(
    monkeypatch: pytest.MonkeyPatch, block: int | None
) -> None:
    from y import contracts

    contract = object.__new__(contracts.Contract)
    object.__setattr__(contract, "address", TOKEN)
    seen: list[tuple[str, int | None]] = []
    expected = HexBytes("0x60006000")

    async def get_code(address: str, block_identifier: int | None = None) -> HexBytes:
        seen.append((address, block_identifier))
        return expected

    monkeypatch.setattr(contracts, "get_code", get_code)
    assert await contract.get_code(block) == expected
    assert seen == [(TOKEN, block)]


@run_async_test
async def test_archive_state_retry_recovers_after_short_burst(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rpc = AsyncMock(side_effect=[*[state_error() for _ in range(5)], HexBytes("0x6000")])
    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(get_code=rpc)))
    monkeypatch.setattr(_rpc, "state_cache", lambda: SharedCache(8))
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    assert await _rpc.deployed(TOKEN, BLOCK)
    assert rpc.await_count == 6
    assert rpc.await_args_list == [rpc.await_args_list[0]] * 6
    assert sleep.await_args_list == [call(0.5), call(1.0), call(2.0), call(4.0), call(8.0)]


@run_async_test
async def test_compound_exchange_rate_retries_real_call_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = 123456789012345678901
    rpc = AsyncMock(side_effect=[state_error(), HexBytes(encode(["uint256"], [raw]))])
    monkeypatch.setattr(
        importlib.import_module("multicall.call"),
        "get_async_w3",
        lambda _: SimpleNamespace(eth=SimpleNamespace(call=rpc)),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    token = CToken(TOKEN, asynchronous=True)
    assert await token.exchange_rate(BLOCK.number, sync=False) == raw / 10**18
    expected = call({"to": TOKEN, "data": HexBytes("0xbd6d894d")}, BLOCK.number)
    assert rpc.await_args_list == [expected, expected]
    sleep.assert_awaited_once_with(0.5)


@run_async_test
async def test_compound_oracle_retries_only_failed_native_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_amount_quotes import CHILD, USD

    rpc = AsyncMock(
        side_effect=[
            HexBytes(encode(["address"], [CHILD])),
            HexBytes(encode(["address"], [USD])),
            state_error(),
            HexBytes(encode(["uint256"], [3 * 10**30])),
        ]
    )
    monkeypatch.setattr(
        importlib.import_module("multicall.call"),
        "get_async_w3",
        lambda _: SimpleNamespace(eth=SimpleNamespace(call=rpc)),
    )
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    monkeypatch.setattr(CToken, "__underlying__", Ready(SimpleNamespace(__decimals__=Ready(6))))
    token = CToken(TOKEN, asynchronous=True)
    assert await token.get_underlying_price(BLOCK.number, sync=False) == 3.0
    assert [c.args[0]["to"].lower() for c in rpc.await_args_list] == [TOKEN, CHILD, USD, USD]
    assert all(c.args[1] == BLOCK.number for c in rpc.await_args_list)
    assert rpc.await_args_list[-1] == rpc.await_args_list[-2]


@run_async_test
@pytest.mark.parametrize(
    "error", [state_error(), TypeError("unexpected RPC"), asyncio.CancelledError()]
)
async def test_compound_exchange_rate_propagates_exhaustion_errors_and_cancellation(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    rpc = AsyncMock(side_effect=error)
    monkeypatch.setattr(
        importlib.import_module("multicall.call"),
        "get_async_w3",
        lambda _: SimpleNamespace(eth=SimpleNamespace(call=rpc)),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    token = CToken(TOKEN, asynchronous=True)
    with pytest.raises(type(error)) as raised:
        await token.exchange_rate(BLOCK.number, sync=False)
    assert raised.value is error
    attempts = 10 if isinstance(error, ValueError) else 1
    assert rpc.await_count == attempts
    assert rpc.await_args_list == [rpc.await_args_list[0]] * attempts
    assert sleep.await_count == attempts - 1


@run_async_test
async def test_compound_contract_fallback_retries_same_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rpc = AsyncMock(return_value=HexBytes("0x"))
    monkeypatch.setattr(
        importlib.import_module("multicall.call"),
        "get_async_w3",
        lambda _: SimpleNamespace(eth=SimpleNamespace(call=rpc)),
    )
    fallback = AsyncMock(side_effect=[state_error(), 2 * 10**18])
    monkeypatch.setattr(
        Contract,
        "coroutine",
        AsyncMock(
            return_value=SimpleNamespace(exchangeRateCurrent=SimpleNamespace(coroutine=fallback))
        ),
    )
    sleep = AsyncMock()
    monkeypatch.setattr(asyncio, "sleep", sleep)
    assert await CToken(TOKEN, asynchronous=True).exchange_rate(BLOCK.number, sync=False) == 2.0
    rpc.assert_awaited_once()
    assert fallback.await_args_list == [call(block_identifier=BLOCK.number)] * 2
    sleep.assert_awaited_once_with(0.5)
