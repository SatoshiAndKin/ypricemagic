"""Factory discovery must register LP tokens for each supported factory interface."""

from collections import defaultdict
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

module = import_module("y.prices.stable_swap.curve")

FACTORY = "0x2db0E83599a91b508Ac268a6197b8B14F5e72840"
POOL = "0x0000000000000000000000000000000000000001"
TOKEN = "0x0000000000000000000000000000000000000002"


@pytest.mark.asyncio_cooperative
@pytest.mark.parametrize("interface", ["get_token", "get_lp_token", "stable"])
async def test_factory_registers_the_actual_lp_token(
    monkeypatch: pytest.MonkeyPatch, interface: str
) -> None:
    contract = SimpleNamespace(address=FACTORY)
    expected = TOKEN
    if interface == "stable":
        contract.is_meta = object()
        contract.get_implementation_address = object()
        expected = POOL
    else:
        setattr(contract, interface, SimpleNamespace(coroutine=AsyncMock(return_value=TOKEN)))
    registry = SimpleNamespace(token_to_pool={}, factories=defaultdict(set))
    monkeypatch.setattr(
        module, "Contract", SimpleNamespace(coroutine=AsyncMock(return_value=contract))
    )
    monkeypatch.setattr(module, "curve", registry)
    factory = object.__new__(module.Factory)
    factory.address = FACTORY
    factory.asynchronous = True
    await factory._Factory__load_pool(POOL, False)
    assert registry.token_to_pool == {expected: POOL}
    assert registry.factories == {FACTORY: {POOL}}


@pytest.mark.asyncio_cooperative
async def test_unknown_factory_does_not_invent_an_lp_token(monkeypatch: pytest.MonkeyPatch) -> None:
    contract = SimpleNamespace(address=FACTORY)
    registry = SimpleNamespace(token_to_pool={}, factories=defaultdict(set))
    monkeypatch.setattr(
        module, "Contract", SimpleNamespace(coroutine=AsyncMock(return_value=contract))
    )
    monkeypatch.setattr(module, "curve", registry)
    factory = object.__new__(module.Factory)
    factory.address = FACTORY
    factory.asynchronous = True
    with pytest.raises(NotImplementedError, match=FACTORY):
        await factory._Factory__load_pool(POOL, False)
    assert not registry.token_to_pool
    assert not registry.factories
