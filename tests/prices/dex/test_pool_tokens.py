"""Pool metadata from events must not schedule token fetches during warmup."""

from unittest.mock import AsyncMock, Mock

import pytest

from y.prices.dex.uniswap import v2

TOKEN0 = "0x0000000000000000000000000000000000000001"
TOKEN1 = "0x0000000000000000000000000000000000000002"
TOKEN2 = "0x0000000000000000000000000000000000000003"


@pytest.mark.asyncio_cooperative
async def test_cached_pool_tokens_need_no_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    pools = [
        v2.UniswapV2Pool(
            f"0x{index + 8000000000000:040x}",
            token0=TOKEN0,
            token1=TOKEN1,
            asynchronous=True,
        )
        for index in range(10_001)
    ]
    forbidden = Mock(side_effect=AssertionError("known tokens must not create a task mapping"))
    monkeypatch.setattr(v2.UniswapV2Pool.tokens, "map", forbidden)
    checkpoints = AsyncMock()
    monkeypatch.setattr(v2, "sleep", checkpoints)
    assert await v2._load_pool_tokens(pools) == {TOKEN0, TOKEN1}
    forbidden.assert_not_called()
    assert checkpoints.await_count == 2


@pytest.mark.asyncio_cooperative
async def test_missing_pool_tokens_keep_existing_fetch_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    known = v2.UniswapV2Pool(
        "0x0000000000000000000000000000090000000000",
        token0=TOKEN0,
        token1=TOKEN1,
        asynchronous=True,
    )
    partial = v2.UniswapV2Pool(
        "0x0000000000000000000000000000090000000001",
        token0=TOKEN0,
        asynchronous=True,
    )
    missing = v2.UniswapV2Pool("0x0000000000000000000000000000090000000002", asynchronous=True)
    values = AsyncMock(return_value=[(TOKEN0, TOKEN2), (TOKEN1, TOKEN2)])
    mapping = Mock(return_value=Mock(values=values))
    monkeypatch.setattr(v2.UniswapV2Pool.tokens, "map", mapping)
    assert await v2._load_pool_tokens([known, partial, missing]) == {TOKEN0, TOKEN1, TOKEN2}
    mapping.assert_called_once_with([partial, missing])
    values.assert_awaited_once_with(pop=True)
