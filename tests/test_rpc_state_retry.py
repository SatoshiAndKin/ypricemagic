"""Retry transient archive-state misses without changing the requested block."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, call

import pytest
from eth_abi.abi import encode
from hexbytes import HexBytes

from tests.test_amount_quotes import BLOCK, TOKEN
from tests.test_pricing_correctness import run_async_test
from y.prices import _rpc
from y.prices._quote import SharedCache


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
    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(**{method: rpc})))
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
    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=rpc)))
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
    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=rpc)))
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
    monkeypatch.setattr(_rpc, "dank_web3", SimpleNamespace(eth=SimpleNamespace(call=rpc)))
    cancelled = asyncio.CancelledError()
    sleep = AsyncMock(side_effect=cancelled)
    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError) as raised:
        await _rpc.read(TOKEN, "totalSupply()(uint256)", BLOCK)
    assert raised.value is cancelled
    rpc.assert_awaited_once()
    sleep.assert_awaited_once_with(0.5)


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
