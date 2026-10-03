from pathlib import Path
from types import SimpleNamespace

import pytest

from y.networks import Network
from y.utils import middleware


@pytest.mark.parametrize(
    "chain_id",
    (Network.BinanceSmartChain, Network.Polygon, Network.Avalanche),
)
def test_remove_legacy_poa_middleware_target_chains(
    chain_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    onion = ["cache", "poa-first", "poa-second", "other"]
    monkeypatch.setattr(middleware, "chain", SimpleNamespace(id=chain_id))
    monkeypatch.setattr(middleware, "web3", SimpleNamespace(middleware_onion=onion))

    middleware.remove_legacy_poa_middleware()

    assert onion == ["cache", "poa-second", "other"]


@pytest.mark.parametrize("chain_id", (Network.Mainnet, Network.Optimism))
def test_remove_legacy_poa_middleware_non_target_chains_unchanged(
    chain_id: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    onion = ["cache", "poa-first", "other"]
    monkeypatch.setattr(middleware, "chain", SimpleNamespace(id=chain_id))
    monkeypatch.setattr(middleware, "web3", SimpleNamespace(middleware_onion=onion))

    middleware.remove_legacy_poa_middleware()

    assert onion == ["cache", "poa-first", "other"]


def test_remove_legacy_poa_middleware_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    onion = ["cache", "poa-first", "other"]
    monkeypatch.setattr(middleware, "chain", SimpleNamespace(id=Network.Polygon))
    monkeypatch.setattr(middleware, "web3", SimpleNamespace(middleware_onion=onion))

    middleware.remove_legacy_poa_middleware()
    middleware.remove_legacy_poa_middleware()

    assert onion == ["cache", "other"]


@pytest.mark.parametrize("debug", (False, True))
def test_v7_cache_preserves_latest_only_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, debug: bool
) -> None:
    from unittest.mock import Mock

    from joblib import Memory  # type: ignore [import-untyped]
    from web3 import Web3
    from web3.types import RPCEndpoint

    monkeypatch.setattr(middleware, "memory", Memory(tmp_path, verbose=0))
    monkeypatch.setattr(middleware.logger, "isEnabledFor", lambda level: debug)
    response = {"jsonrpc": "2.0", "id": 7, "result": "0x1234"}
    request = Mock(return_value=response)
    wrapped = middleware.getcode_cache_middleware(Web3()).wrap_make_request(request)
    latest = ["0x0000000000000000000000000000000000000001", "latest"]
    assert wrapped(RPCEndpoint("eth_getCode"), latest) == response
    assert wrapped(RPCEndpoint("eth_getCode"), latest) == response
    assert request.call_count == 1
    for selector in ("pending", "0x1", {"blockHash": "0x" + "ab" * 32, "requireCanonical": True}):
        params = [latest[0], selector]
        assert wrapped(RPCEndpoint("eth_getCode"), params) == response
        assert wrapped(RPCEndpoint("eth_getCode"), params) == response
    assert wrapped(RPCEndpoint("eth_getBalance"), latest) == response
    assert wrapped(RPCEndpoint("eth_getBalance"), latest) == response
    assert request.call_args_list == [
        ((RPCEndpoint("eth_getCode"), latest),),
        *[
            ((RPCEndpoint("eth_getCode"), [latest[0], selector]),)
            for selector in (
                "pending",
                "0x1",
                {"blockHash": "0x" + "ab" * 32, "requireCanonical": True},
            )
            for _ in range(2)
        ],
        ((RPCEndpoint("eth_getBalance"), latest),),
        ((RPCEndpoint("eth_getBalance"), latest),),
    ]
