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


@run_async_test
@pytest.mark.parametrize("asynchronous", [False, True])
async def test_pool_token_index_reuses_metadata_without_retaining_pool_methods(
    asynchronous: bool,
) -> None:
    import asyncio
    import weakref

    from tests.test_pricing_correctness import instance

    first = "0x0000000000000000000000000000000000000101"
    second = "0x0000000000000000000000000000000000000102"
    # The singleton registry owns ordinary pools. Isolate index/property ownership.
    pool = object.__new__(v2.UniswapV2Pool)
    v2.UniswapV2Pool.__init__(
        pool,
        f"0x000000000000000000000000000000001234000{3 + asynchronous}",
        first,
        second,
        18_000_000,
        asynchronous=asynchronous,
    )
    reference = weakref.ref(pool)
    router = instance(v2.UniswapRouterV2)
    router.pools = [pool]
    router.address, router.label = "test", "test"
    index = await v2.UniswapRouterV2.pools_by_token.get(router)
    assert index == {first: {pool: second}, second: {pool: first}}
    pair = await type(pool).tokens.get(pool)
    assert tuple(map(str, pair)) == (first, second)
    assert await type(pool).tokens.get(pool) is pair
    assert not {"__tokens__", "__token0__", "__token1__"}.intersection(vars(pool))
    assert pool._deploy_block == 18_000_000
    result = await router.all_pools_for(first, sync=False)
    result.clear()
    assert index[first] == {pool: second}
    # Drop the deliberate index owners, without garbage collection or cache expiry.
    router.pools = []
    router.pools_by_token = {}
    del index, pool
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert reference() is None


@run_async_test
@pytest.mark.parametrize("outcome", ["failure", "cancellation"])
async def test_pool_token_getter_preserves_subclasses_and_independent_waiters(outcome: str) -> None:
    import asyncio

    import a_sync

    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    first, second = object(), object()

    class Pool(v2.UniswapV2Pool):
        @a_sync.cached_property
        async def token0(self) -> Any:
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            if outcome == "failure" and calls == 1:
                raise ValueError("metadata failed")
            return first

        @a_sync.cached_property
        async def token1(self) -> Any:
            return second

    pool = Pool(
        (
            "0x0000000000000000000000000000000012340005"
            if outcome == "failure"
            else "0x0000000000000000000000000000000012340006"
        ),
        asynchronous=True,
    )
    caller = asyncio.create_task(type(pool).tokens.get(pool))
    await entered.wait()
    if outcome == "cancellation":
        survivor = asyncio.create_task(type(pool).tokens.get(pool))
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        release.set()
        assert await survivor == (first, second)
        assert calls == 1
    else:
        release.set()
        with pytest.raises(ValueError, match="metadata failed"):
            await caller
        assert await type(pool).tokens.get(pool) == (first, second)
        assert calls == 2
    pair = await type(pool).tokens.get(pool)
    assert await pool.__tokens__ is pair
    state = getattr(pool, "__async_property__")
    assert not state.tasks and not state.locks
