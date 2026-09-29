from types import SimpleNamespace
from typing import NoReturn

import pytest
from brownie import web3
from dank_mids.brownie_patch import dank_eth, dank_web3

import y._db.utils.utils as db
import y.time as ytime
from y.networks import Network


@pytest.fixture(autouse=True)
def clear_get_block_timestamp_cache() -> None:
    if hasattr(ytime.get_block_timestamp, "clear"):
        ytime.get_block_timestamp.clear(warn=False)


def test_get_block_timestamp_erigon_supports_int_like_header_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    height = 987_654_301
    expected_timestamp = 1_700_000_001
    observed: dict[str, object] = {}

    class UnixTimestampLike:
        def __int__(self) -> int:
            return expected_timestamp

    def fake_get_block_timestamp(_height: int, sync: bool = False) -> None:  # noqa: ARG001
        return None

    def fake_set_block_timestamp(
        block: int, timestamp: int, sync: bool = False
    ) -> None:  # noqa: ARG001
        observed["set"] = (block, timestamp, sync)

    def fake_request_blocking(method: str, params: list[int]) -> SimpleNamespace:
        observed["request"] = (method, params)
        return SimpleNamespace(timestamp=UnixTimestampLike())

    monkeypatch.setattr(ytime, "CHAINID", Network.Mainnet)
    monkeypatch.setattr(ytime, "get_ethereum_client", lambda: "erigon")
    monkeypatch.setattr(db, "get_block_timestamp", fake_get_block_timestamp)
    monkeypatch.setattr(db, "_set_block_timestamp", fake_set_block_timestamp)
    monkeypatch.setattr(web3.manager, "request_blocking", fake_request_blocking)

    assert ytime.get_block_timestamp(height) == expected_timestamp
    assert observed["request"] == ("erigon_getHeaderByNumber", [height])
    assert observed["set"] == (height, expected_timestamp, True)


def test_get_block_timestamp_erigon_supports_hex_timestamp_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    height = 987_654_302
    expected_timestamp = 1_700_000_002
    observed: dict[str, object] = {}

    def fake_get_block_timestamp(_height: int, sync: bool = False) -> None:  # noqa: ARG001
        return None

    def fake_set_block_timestamp(
        block: int, timestamp: int, sync: bool = False
    ) -> None:  # noqa: ARG001
        observed["set"] = (block, timestamp, sync)

    def fake_request_blocking(_method: str, _params: list[int]) -> SimpleNamespace:
        return SimpleNamespace(timestamp=hex(expected_timestamp))

    monkeypatch.setattr(ytime, "CHAINID", Network.Mainnet)
    monkeypatch.setattr(ytime, "get_ethereum_client", lambda: "erigon")
    monkeypatch.setattr(db, "get_block_timestamp", fake_get_block_timestamp)
    monkeypatch.setattr(db, "_set_block_timestamp", fake_set_block_timestamp)
    monkeypatch.setattr(web3.manager, "request_blocking", fake_request_blocking)

    assert ytime.get_block_timestamp(height) == expected_timestamp
    assert observed["set"] == (height, expected_timestamp, True)


@pytest.mark.asyncio_cooperative
async def test_get_block_timestamp_async_erigon_supports_int_like_header_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    height = 987_654_303
    expected_timestamp = 1_700_000_003
    observed: dict[str, object] = {}

    class UnixTimestampLike:
        def __int__(self) -> int:
            return expected_timestamp

    async def fake_get_block_timestamp(_height: int, sync: bool = False) -> None:  # noqa: ARG001
        return None

    def fake_set_block_timestamp(block: int, timestamp: int) -> None:
        observed["set"] = (block, timestamp)

    async def fake_get_client() -> str:
        return "erigon"

    async def fake_coro_request(method: str, params: list[int]) -> SimpleNamespace:
        observed["request"] = (method, params)
        return SimpleNamespace(timestamp=UnixTimestampLike())

    async def fake_fallback(_height: int) -> NoReturn:  # pragma: no cover
        raise AssertionError("fallback path should not run for erigon header timestamps")

    monkeypatch.setattr(ytime, "CHAINID", Network.Mainnet)
    monkeypatch.setattr(ytime, "get_ethereum_client_async", fake_get_client)
    monkeypatch.setattr(db, "get_block_timestamp", fake_get_block_timestamp)
    monkeypatch.setattr(db, "set_block_timestamp", fake_set_block_timestamp)
    monkeypatch.setattr(getattr(dank_web3, "manager"), "coro_request", fake_coro_request)
    monkeypatch.setattr(dank_eth, "get_block_timestamp", fake_fallback)

    undecorated = getattr(getattr(ytime.get_block_timestamp_async, "__wrapped__"), "__wrapped__")
    assert await undecorated(height) == expected_timestamp
    assert observed["request"] == ("erigon_getHeaderByNumber", [height])
    assert observed["set"] == (height, expected_timestamp)


@pytest.mark.asyncio_cooperative
async def test_get_block_timestamp_async_erigon_supports_hex_timestamp_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    height = 987_654_304
    expected_timestamp = 1_700_000_004
    observed: dict[str, object] = {}

    async def fake_get_block_timestamp(_height: int, sync: bool = False) -> None:  # noqa: ARG001
        return None

    def fake_set_block_timestamp(block: int, timestamp: int) -> None:
        observed["set"] = (block, timestamp)

    async def fake_get_client() -> str:
        return "erigon"

    async def fake_coro_request(_method: str, _params: list[int]) -> SimpleNamespace:
        return SimpleNamespace(timestamp=hex(expected_timestamp))

    monkeypatch.setattr(ytime, "CHAINID", Network.Mainnet)
    monkeypatch.setattr(ytime, "get_ethereum_client_async", fake_get_client)
    monkeypatch.setattr(db, "get_block_timestamp", fake_get_block_timestamp)
    monkeypatch.setattr(db, "set_block_timestamp", fake_set_block_timestamp)
    monkeypatch.setattr(getattr(dank_web3, "manager"), "coro_request", fake_coro_request)

    undecorated = getattr(getattr(ytime.get_block_timestamp_async, "__wrapped__"), "__wrapped__")
    assert await undecorated(height) == expected_timestamp
    assert observed["set"] == (height, expected_timestamp)
