"""Pool discovery need not construct an unused reserve RPC handle."""

from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_pricing_correctness import run_async_test
from y.prices.dex.uniswap import v2


def fake_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    constructed: list[tuple[str, str]] = []

    class Call:
        def __init__(self, address: str, signature: str) -> None:
            self.signature = signature
            constructed.append((address, signature))

        async def coroutine(self, *, block_id: int) -> tuple[int, int, int]:
            assert block_id == 18_000_000
            if "uint112" in self.signature:
                return 11, 22, 33
            return 44, 55, 66

    monkeypatch.setattr(v2, "Call", Call)
    return constructed


def test_unused_pool_does_not_construct_reserve_call(monkeypatch: pytest.MonkeyPatch) -> None:
    constructed = fake_calls(monkeypatch)
    pool = v2.UniswapV2Pool("0x0000000000000000000000000000000012340001", asynchronous=True)
    assert pool.address == "0x0000000000000000000000000000000012340001"
    assert constructed == []


@run_async_test
async def test_pool_reuses_reserve_call_and_preserves_verified_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = fake_calls(monkeypatch)
    address = "0x0000000000000000000000000000000012340002"
    pool = v2.UniswapV2Pool(address, asynchronous=True)
    first = pool.get_reserves
    assert pool.get_reserves is first
    assert await first(block_id=18_000_000) == (11, 22, 33)
    assert constructed == [(address, "getReserves()((uint112,uint112,uint32))")]

    async def contract(pool_address: str) -> Any:
        assert pool_address == address
        return SimpleNamespace(
            getReserves=SimpleNamespace(abi={"outputs": [{"type": "uint256"}] * 3})
        )

    monkeypatch.setattr(v2, "Contract", SimpleNamespace(coroutine=contract))
    await pool._check_return_types()
    assert pool.get_reserves is not first
    assert await pool.get_reserves(block_id=18_000_000) == (44, 55, 66)
    await pool._check_return_types()
    assert constructed == [
        (address, "getReserves()((uint112,uint112,uint32))"),
        (address, "getReserves()((uint256,uint256,uint256))"),
    ]
