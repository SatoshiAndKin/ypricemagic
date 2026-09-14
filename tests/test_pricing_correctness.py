"""Regression tests exercise the production pricing entry points with controlled RPCs."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Coroutine, Generator
from decimal import Decimal
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Generic, ParamSpec, TypeVar
from unittest.mock import AsyncMock

import a_sync
import pytest
from eth_typing import BlockNumber, ChecksumAddress, HexAddress, HexStr

from y import constants
from y.classes.common import ERC20
from y.datatypes import PriceResult, PriceStep, UsdPrice
from y.prices import exotic_tokens, magic, solidex, utils, yearn
from y.prices.dex import mooniswap

TOKEN = ChecksumAddress(HexAddress(HexStr("0x0000000000000000000000000000000000000101")))
CHILD = "0x0000000000000000000000000000000000000102"
BLOCK = BlockNumber(15_000_000)


P = ParamSpec("P")
T = TypeVar("T")


def run_async_test(function: Callable[P, Coroutine[Any, Any, None]]) -> Callable[P, None]:
    """Run tests that patch shared pricing modules one at a time."""

    @wraps(function)
    def run(*args: P.args, **kwargs: P.kwargs) -> None:
        return asyncio.get_event_loop().run_until_complete(function(*args, **kwargs))

    return run


class Ready(Generic[T]):
    def __init__(self, value: T) -> None:
        self.value = value

    def __await__(self) -> Generator[Any, None, T]:
        async def resolve() -> T:
            return self.value

        return resolve().__await__()


@run_async_test
async def test_balancer_conversion_drains_rpc_on_child_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from y.prices.dex.balancer.v1 import _calc_out_value

    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def scale(address: object) -> int:
        entered.set()
        try:
            await asyncio.Event().wait()
            return 10**18
        finally:
            cleaned.set()

    async def child(*args: Any, **kwargs: Any) -> None:
        await entered.wait()
        raise RuntimeError("child quote failed")

    monkeypatch.setattr(ERC20, "_get_scale_for", scale)
    monkeypatch.setattr(magic, "get_price", child)
    with pytest.raises(RuntimeError, match="child quote failed"):
        await _calc_out_value(TOKEN, CHILD, 10**18, 1, BLOCK)
    assert cleaned.is_set()


def instance(cls: type[a_sync.ASyncGenericBase]) -> Any:
    obj: Any = object.__new__(cls)
    a_sync.ASyncGenericBase.__init__(obj)
    obj.asynchronous = True
    return obj


@run_async_test
@pytest.mark.parametrize("explicit", [False, True])
async def test_price_block_is_a_plain_integer(
    monkeypatch: pytest.MonkeyPatch, explicit: bool
) -> None:
    class RpcBlockNumber(int):
        pass

    block = RpcBlockNumber(BLOCK)
    monkeypatch.setattr(
        magic, "dank_mids", SimpleNamespace(eth=SimpleNamespace(block_number=Ready(block)))
    )
    lookup = AsyncMock(return_value=PriceResult(UsdPrice(1), []))
    monkeypatch.setattr(magic, "_get_price", lookup)
    assert await magic.get_price(TOKEN, block if explicit else None, sync=False)
    assert lookup.await_args.args == (TOKEN, BLOCK)
    assert type(lookup.await_args.args[1]) is int


@run_async_test
@pytest.mark.parametrize(
    "balance,supply,expected",
    [
        (0, 10**18, 0),
        (None, 10**18, None),
        (10**18, 0, None),
        (10**18, None, None),
        (6 * 10**6, 2 * 10**18, 12),
    ],
)
async def test_xpremia_backing(
    monkeypatch: pytest.MonkeyPatch,
    balance: int | None,
    supply: int | None,
    expected: float | bool | None,
) -> None:
    async def call(address: str, method: str, **kwargs: Any) -> str | int | None:
        assert kwargs["block"] == BLOCK
        return {"premia()": CHILD, "balanceOf(address)": balance, "totalSupply()": supply}[method]

    async def scale(address: str) -> int:
        return 10**6 if str(address) == CHILD else 10**18

    monkeypatch.setattr(exotic_tokens, "raw_call", call)
    monkeypatch.setattr(ERC20, "_get_scale_for", scale)
    child_price = AsyncMock(
        return_value=PriceResult(UsdPrice(4), [PriceStep(CHILD, UsdPrice(4), "oracle")])
    )
    monkeypatch.setattr(magic, "get_price", child_price)
    result = await exotic_tokens.get_price_xpremia(TOKEN, BLOCK, skip_cache=True, sync=False)
    if expected is None:
        assert result is None
    else:
        assert float(result) == expected
    if not balance or not supply:
        child_price.assert_not_awaited()


@run_async_test
async def test_cache_forwards_skip_and_does_not_reuse_unrestricted_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from y._db.utils import price as db

    child = PriceResult(UsdPrice(3), [])
    lookup = AsyncMock(return_value=child)
    cached = magic.__cache(lookup)
    read = AsyncMock(return_value=Decimal(99))
    monkeypatch.setattr(db, "get_price", read)
    monkeypatch.setattr(db, "set_price", lambda *args: pytest.fail("restricted price was cached"))
    assert await cached(TOKEN, BLOCK, skip_cache=True) == child
    assert lookup.call_args.kwargs["skip_cache"] is True
    assert await cached(TOKEN, BLOCK, ignore_pools=("excluded",)) == child
    read.assert_not_awaited()


@pytest.mark.parametrize(
    "value",
    [10**1000, Decimal("sNaN"), Decimal("Infinity"), True],
    ids=["overflow", "signalling-nan", "infinity", "boolean"],
)
def test_invalid_price_conversion(value: object) -> None:
    from y.prices._candidates import valid_price

    assert valid_price(value) is False


@run_async_test
async def test_chainlink_replacements_removals_and_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    module = importlib.import_module("y.prices.chainlink")
    chainlink = instance(module.Chainlink)
    old = SimpleNamespace(asset=TOKEN, address=CHILD, start_block=100)
    newer = SimpleNamespace(
        asset=TOKEN, address="0x0000000000000000000000000000000000000103", start_block=200
    )
    removed = SimpleNamespace(asset=TOKEN, address=module.ZERO_ADDRESS, start_block=300)
    scanned = []

    async def events(to_block: int) -> AsyncIterator[SimpleNamespace]:
        scanned.append(to_block)
        await asyncio.sleep(0)
        for feed in (old, newer, removed):
            if feed.start_block <= to_block:
                yield feed

    chainlink._feeds = [SimpleNamespace(asset=TOKEN, address=CHILD, start_block=0)]
    chainlink._feeds_from_events = SimpleNamespace(objects=events)
    chainlink.registry = None

    async def resolve(number: int) -> Any:
        return module.BlockRef(1, number, f"0x{number:064x}", number)

    async def deployed(address: str, block: Any) -> bool:
        return int(block.number) >= 100

    monkeypatch.setattr(module.BlockRef, "resolve", resolve)
    monkeypatch.setattr(module, "deployed", deployed)
    blocks = (99, 100, 199, 200, 201, 299, 300, 301)
    results = await asyncio.gather(
        *(chainlink.get_feed(TOKEN, block, sync=False) for block in blocks)
    )
    assert [feed.address if feed else None for feed in results] == [
        None,
        CHILD,
        CHILD,
        newer.address,
        newer.address,
        newer.address,
        None,
        None,
    ]
    assert await chainlink.get_feed(TOKEN.lower(), 200, sync=False) is newer
    assert scanned.count(200) == 1
    monkeypatch.setattr(
        module, "dank_mids", SimpleNamespace(eth=SimpleNamespace(block_number=Ready(199)))
    )
    assert await chainlink.get_feed(TOKEN, sync=False) is old
    monkeypatch.setattr(
        module, "dank_mids", SimpleNamespace(eth=SimpleNamespace(block_number=Ready(301)))
    )
    assert await chainlink.get_feed(TOKEN, sync=False) is None
    assert module.FeedsFromEvents._include_event(
        {"denomination": module.DENOMINATIONS["USD"], "latestAggregator": module.ZERO_ADDRESS}
    )


@run_async_test
@pytest.mark.parametrize("decoded,expected", [(0, True), (5, True), (None, False)])
async def test_xtarot_probe_has_encoded_share_amount(
    monkeypatch: pytest.MonkeyPatch, decoded: int | None, expected: float | bool | None
) -> None:
    monkeypatch.setattr(
        exotic_tokens, "ERC20", lambda *args, **kwargs: SimpleNamespace(symbol=Ready("xTAROT"))
    )
    monkeypatch.setattr(exotic_tokens, "has_methods", AsyncMock(return_value=True))
    call = AsyncMock(return_value=decoded)
    monkeypatch.setattr(exotic_tokens, "raw_call", call)
    # Exercise detection without reusing results from a different controlled RPC.
    address = f"0x{(1000 + (decoded if decoded is not None else 100)):040x}"
    assert await exotic_tokens.is_xtarot(address, sync=False) is expected
    assert call.call_args.args[1] == "shareValuedAsUnderlying(uint256)"
    assert call.call_args.kwargs["inputs"] == 10**18
    assert call.call_args.kwargs["output"] == "int"


@run_async_test
@pytest.mark.parametrize(
    "api,bucket,expected,expected_calls",
    [
        (0, 0, 7, (1, 1)),
        (-1, float("nan"), 7, (1, 1)),
        (float("inf"), 4, 4, (1, 0)),
        (3, 4, 3, (0, 0)),
    ],
)
async def test_invalid_prices_fall_through(
    monkeypatch: pytest.MonkeyPatch,
    api: float,
    bucket: float,
    expected: float | bool | None,
    expected_calls: tuple[bool, bool],
) -> None:
    monkeypatch.setattr(
        magic, "ERC20", lambda *args, **kwargs: SimpleNamespace(symbol=Ready("TEST"))
    )
    monkeypatch.setattr(magic, "_get_price_from_api", AsyncMock(return_value=api))
    bucket_call = AsyncMock(return_value=(bucket, "bucket"))
    dex_call = AsyncMock(return_value=(UsdPrice(7), "dex"))
    monkeypatch.setattr(magic, "_exit_early_for_known_tokens", bucket_call)
    monkeypatch.setattr(magic, "_get_price_from_dexes", dex_call)
    monkeypatch.setattr(utils, "sense_check", AsyncMock())
    result = await magic.get_price(TOKEN, BLOCK, skip_cache=True, sync=False)
    assert float(result) == expected
    assert (bucket_call.await_count, dex_call.await_count) == expected_calls


@run_async_test
async def test_recursive_cycle_and_exclusion_inheritance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        magic, "ERC20", lambda *args, **kwargs: SimpleNamespace(symbol=Ready("TEST"))
    )
    monkeypatch.setattr(magic, "_get_price_from_api", AsyncMock(return_value=None))
    monkeypatch.setattr(magic, "_exit_early_for_known_tokens", AsyncMock(return_value=(None, None)))
    calls = []

    async def dex(
        token: str,
        block: int,
        ignore_pools: tuple[object, ...],
        skip_cache: bool,
        logger: logging.Logger,
    ) -> tuple[PriceResult | None, str]:
        calls.append((token, ignore_pools, skip_cache))
        child = await magic.get_price(
            CHILD if token == TOKEN else TOKEN, block, fail_to_None=True, sync=False
        )
        return child, "recursive"

    monkeypatch.setattr(magic, "_get_price_from_dexes", dex)
    assert (
        await magic.get_price(
            TOKEN, BLOCK, ignore_pools=("excluded",), skip_cache=True, fail_to_None=True, sync=False
        )
        is None
    )
    assert calls == [(TOKEN, ("excluded",), True), (CHILD, ("excluded",), True)]
    assert magic._price_request.get().dependencies == ()


@run_async_test
async def test_conversion_preserves_exact_child_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from y.prices import convex

    child = PriceResult(
        UsdPrice(4),
        [PriceStep(CHILD, UsdPrice(4), "pool"), PriceStep("underlying", UsdPrice(2), "oracle")],
    )
    monkeypatch.setattr(convex, "get_underlying_lp", AsyncMock(return_value=CHILD))
    monkeypatch.setattr(magic, "get_price", AsyncMock(return_value=child))
    result = await convex.get_price(TOKEN, BLOCK, skip_cache=True, sync=False)
    assert result.path == [
        PriceStep(TOKEN, UsdPrice(4), f"Convex wrapping Curve LP {CHILD}"),
        *child.path,
    ]
    assert result.path[1] is not child.path[0]
    result.path.pop()
    assert child.path == [
        PriceStep(CHILD, UsdPrice(4), "pool"),
        PriceStep("underlying", UsdPrice(2), "oracle"),
    ]


@run_async_test
async def test_bucket_priority_waits_for_every_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from y._db.utils import token as db
    from y.prices.utils import buckets

    monkeypatch.setattr(db, "get_bucket", AsyncMock(return_value=None))
    monkeypatch.setattr(db, "set_bucket", lambda *args: None)
    monkeypatch.setattr(buckets, "string_matchers", {})
    monkeypatch.setattr(buckets, "calls_only", {})
    monkeypatch.setattr(buckets, "gearbox", None)
    monkeypatch.setattr(buckets, "chainlink", None)
    monkeypatch.setattr(buckets, "synthetix", None)
    monkeypatch.setattr(buckets, "curve", None)
    started, release, all_started = set(), asyncio.Event(), asyncio.Event()

    def check(name: str, result: bool = False) -> Callable[..., Coroutine[Any, Any, bool]]:
        async def call(*args: Any, **kwargs: Any) -> bool:
            started.add(name)
            if len(started) == 8:
                all_started.set()
            if name == "solidex":
                await release.wait()
            return result

        return call

    monkeypatch.setattr(solidex, "is_solidex_deposit", check("solidex", True))
    monkeypatch.setattr(
        buckets, "uniswap_multiplexer", SimpleNamespace(is_uniswap_pool=check("uni", True))
    )
    monkeypatch.setattr(
        buckets,
        "aave",
        SimpleNamespace(is_wrapped_atoken_v2=check("aave2"), is_wrapped_atoken_v3=check("aave3")),
    )
    monkeypatch.setattr(buckets, "is_generic_amm", check("generic"))
    monkeypatch.setattr(mooniswap, "is_mooniswap_pool", check("moon"))
    monkeypatch.setattr(buckets, "compound", SimpleNamespace(is_compound_market=check("compound")))
    monkeypatch.setattr(yearn, "is_yearn_vault", check("yearn"))
    task = asyncio.create_task(buckets.check_bucket(TOKEN, BLOCK, sync=False))
    try:
        await asyncio.wait_for(all_started.wait(), 2)
        assert not task.done()
        release.set()
        assert await task == "uni or uni-like lp"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@run_async_test
async def test_balancer_weight_ratio(monkeypatch: pytest.MonkeyPatch) -> None:
    from y.prices.dex.balancer.v2 import BalancerV2Pool

    class Token:
        def __init__(self, address: str, price: float) -> None:
            self.address, self.value = address, price

        def __eq__(self, other: object) -> bool:
            return self.address == getattr(other, "address", other)

        def __hash__(self) -> int:
            return hash(self.address)

        async def price(self, **kwargs: Any) -> PriceResult:
            return PriceResult(
                UsdPrice(self.value), [PriceStep(self.address, UsdPrice(self.value), "oracle")]
            )

    token, paired = Token(TOKEN, 0), Token(CHILD, 3)
    pool = instance(BalancerV2Pool)
    pool.address = "pool"
    balances = {
        token: SimpleNamespace(__readable__=Ready(Decimal(10))),
        paired: SimpleNamespace(__readable__=Ready(Decimal(40))),
    }
    monkeypatch.setattr(BalancerV2Pool, "get_balances", AsyncMock(return_value=balances))
    monkeypatch.setattr(BalancerV2Pool, "weights", AsyncMock(return_value=[8 * 10**17, 2 * 10**17]))
    result = await pool.get_token_price(TOKEN, BLOCK, sync=False)
    assert float(result) == 48  # 40 * $3 * (0.8 / 0.2) / 10
    assert result.path[1] == PriceStep(CHILD, UsdPrice(3), "oracle")


@run_async_test
@pytest.mark.parametrize("response,expected", [(bytes(32), True), (b"", False)])
async def test_xtarot_actual_calldata_and_zero_decoding(
    monkeypatch: pytest.MonkeyPatch, response: bytes, expected: float | bool | None
) -> None:
    from eth_utils.crypto import keccak
    from hexbytes import HexBytes

    from y.utils import raw_calls

    monkeypatch.setattr(
        exotic_tokens, "ERC20", lambda *args, **kwargs: SimpleNamespace(symbol=Ready("xTAROT"))
    )
    monkeypatch.setattr(exotic_tokens, "has_methods", AsyncMock(return_value=True))

    async def rpc(call: dict[str, str], block_identifier: int | None) -> bytes:
        assert bytes(HexBytes(call["data"])) == keccak(text="shareValuedAsUnderlying(uint256)")[
            :4
        ] + (10**18).to_bytes(32, "big")
        return HexBytes(response)

    monkeypatch.setattr(raw_calls, "dank_mids", SimpleNamespace(eth=SimpleNamespace(call=rpc)))
    address = f"0x{(2000 + len(response)):040x}"
    assert await exotic_tokens.is_xtarot(address, sync=False) is expected


@run_async_test
@pytest.mark.parametrize("cache_value", [0, -1, float("nan"), float("inf")])
async def test_invalid_cache_values_are_neither_accepted_nor_written(
    monkeypatch: pytest.MonkeyPatch, cache_value: float
) -> None:
    from y._db.utils import price as db

    monkeypatch.setattr(db, "get_price", AsyncMock(return_value=cache_value))
    writes = []
    monkeypatch.setattr(db, "set_price", lambda *args: writes.append(args))
    lookup = AsyncMock(return_value=PriceResult(UsdPrice(cache_value), []))
    cached = magic.__cache(lookup)
    await cached(TOKEN, BLOCK)
    await cached(TOKEN, BLOCK)
    assert writes == []
    assert lookup.await_count == 2


@run_async_test
async def test_numeric_disk_cache_hit_has_empty_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from y._db.utils import price as db

    monkeypatch.setattr(db, "get_price", AsyncMock(return_value=Decimal(6)))
    lookup = AsyncMock()
    result = await magic.__cache(lookup)(TOKEN, BLOCK)
    assert result == PriceResult(UsdPrice(6), [])
    lookup.assert_not_awaited()


@run_async_test
async def test_valid_price_cache_writes_numeric_value(monkeypatch: pytest.MonkeyPatch) -> None:
    from y._db.utils import price as db

    read = AsyncMock(return_value=None)
    writes = []
    monkeypatch.setattr(db, "get_price", read)
    monkeypatch.setattr(db, "set_price", lambda *args: writes.append(args))
    result = PriceResult(UsdPrice(7.5), [PriceStep(TOKEN, UsdPrice(7.5), "oracle")])
    lookup = AsyncMock(return_value=result)
    cached = magic.__cache(lookup)
    assert await cached(TOKEN, BLOCK) is result
    second = await cached(TOKEN, BLOCK)
    assert second == result and second is not result
    second.path[0].source = "caller edit"
    third = await cached(TOKEN, BLOCK)
    assert third is not None and third.path[0].source == "oracle"
    assert writes == [(TOKEN, BLOCK, Decimal("7.5"))]
    assert read.await_count == lookup.await_count == 1


@run_async_test
@pytest.mark.parametrize(
    "incremental,failure",
    [(False, None), (True, None), (False, "metadata"), (True, "metadata"), (False, "cancel")],
)
async def test_v2_discovery_uses_one_block_and_drains_loader(
    monkeypatch: pytest.MonkeyPatch, incremental: bool, failure: str | None
) -> None:
    import importlib

    module = importlib.import_module("y.prices.dex.uniswap.v2")
    loader_cleaned, loader_started = asyncio.Event(), asyncio.Event()
    calls = []

    class Head:
        def __init__(self) -> None:
            self.reads = 0

        @property
        def block_number(self) -> Ready[int]:
            self.reads += 1
            return Ready(BLOCK + self.reads - 1)

    head = Head()
    monkeypatch.setattr(module, "dank_mids", SimpleNamespace(eth=head))

    class Pool:
        def __init__(
            self,
            address: str,
            token0: str = TOKEN,
            token1: str = CHILD,
            deploy_block: int = 1,
            **kwargs: Any,
        ) -> None:
            self.address, self.token0, self.token1, self._deploy_block = (
                address,
                None if failure == "metadata" else token0,
                token1,
                deploy_block,
            )

        def __hash__(self) -> int:
            return hash(self.address)

        @a_sync.property
        async def tokens(self) -> tuple[str | None, str]:
            return self.token0, self.token1

    monkeypatch.setattr(module, "UniswapV2Pool", Pool)

    async def count(factory: str, method: str, **kwargs: Any) -> int:
        calls.append((method, kwargs["block"]))
        return 2

    monkeypatch.setattr(module, "raw_call", count)
    monkeypatch.setattr(
        module,
        "_load_cached_pool_tuples",
        lambda factory: [["first", TOKEN, CHILD, 1]] if incremental else [],
    )
    saved = []
    monkeypatch.setattr(module, "_save_pool_tuples", lambda factory, pools: saved.append(pools))

    async def index(index: int, block_identifier: int | None) -> str:
        calls.append(("allPairs", block_identifier))
        return "first" if index == 0 else "second"

    monkeypatch.setattr(
        module,
        "Contract",
        SimpleNamespace(
            coroutine=AsyncMock(
                return_value=SimpleNamespace(allPairs=SimpleNamespace(coroutine=index))
            )
        ),
    )

    class Events:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            async def load() -> None:
                try:
                    await asyncio.Event().wait()
                finally:
                    loader_cleaned.set()

            self._task = asyncio.create_task(load())

        async def pools(self, to_block: int) -> AsyncIterator[Pool]:
            calls.append(("events", to_block))
            await asyncio.sleep(0)
            loader_started.set()
            if failure == "cancel":
                await asyncio.Event().wait()
            yield Pool("second")

    monkeypatch.setattr(module, "PoolsFromEvents", Events)
    router = SimpleNamespace(label="test", factory=TOKEN, asynchronous=True)
    lookup = module.UniswapRouterV2.__dict__["pools"].__wrapped__(router)
    if failure == "cancel":
        task = asyncio.create_task(lookup)
        await loader_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert loader_cleaned.is_set()
        assert saved == []
        return
    if failure == "metadata":
        with pytest.raises(ValueError, match="Incomplete pool discovery"):
            await lookup
        assert saved == []
        return
    result = await lookup
    assert [pool.address for pool in result] == ["first", "second"]
    assert head.reads == 1
    assert {block for _, block in calls} == {BLOCK}
    assert saved == [[["first", TOKEN, CHILD, 1], ["second", TOKEN, CHILD, 1]]]
    if not incremental:
        assert loader_cleaned.is_set()


def test_price_reset_preserves_other_chains_and_metadata(tmp_path: Path) -> None:
    import sqlite3

    from y._db.price_cache import reset_prices

    database, backup = tmp_path / "prices.sqlite", tmp_path / "backup.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE Price (token_chain INTEGER, block_chain INTEGER, price REAL)")
        db.executemany("INSERT INTO Price VALUES (?, ?, ?)", [(1, 1, 2), (1, 1, 3), (10, 10, 4)])
        db.execute("CREATE TABLE Address (address TEXT)")
        db.execute("INSERT INTO Address VALUES (?)", (TOKEN,))
        db.execute("CREATE TABLE Log (event TEXT)")
        db.execute("INSERT INTO Log VALUES ('PairCreated')")
    assert reset_prices(database, 1, backup) == {
        "chain": 1,
        "before": 2,
        "deleted": 2,
        "other_chain_rows": 1,
    }
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT * FROM Price").fetchall() == [(10, 10, 4)]
        assert db.execute("SELECT * FROM Address").fetchall() == [(TOKEN,)]
        assert db.execute("SELECT * FROM Log").fetchall() == [("PairCreated",)]
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT * FROM Price").fetchall() == [(1, 1, 2), (1, 1, 3), (10, 10, 4)]
    with pytest.raises(FileExistsError):
        reset_prices(database, 1, backup)


@run_async_test
@pytest.mark.parametrize("missing", ["premia", "decimals"])
async def test_xpremia_missing_required_data(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    from y.exceptions import NonStandardERC20

    async def call(address: str, method: str, **kwargs: Any) -> str | int | None:
        if method == "premia()":
            return None if missing == "premia" else CHILD
        return 10**18

    monkeypatch.setattr(exotic_tokens, "raw_call", call)
    monkeypatch.setattr(
        ERC20, "_get_scale_for", AsyncMock(side_effect=NonStandardERC20("missing decimals"))
    )
    child = AsyncMock()
    monkeypatch.setattr(magic, "get_price", child)
    assert await exotic_tokens.get_price_xpremia(TOKEN, BLOCK, sync=False) is None
    child.assert_not_awaited()


@run_async_test
async def test_conversion_ratios_keep_child_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    from y.prices import curve_gauge

    module = importlib.import_module("y.prices.eth_derivs.wsteth")
    child = PriceResult(UsdPrice(10), [PriceStep(CHILD, UsdPrice(10), "oracle")])
    monkeypatch.setattr(module, "raw_call", AsyncMock(return_value=15 * 10**17))
    monkeypatch.setattr(magic, "get_price", AsyncMock(return_value=child))
    wrapper = instance(module.wstEth)
    wrapper.address = TOKEN
    result = await wrapper.get_price(BLOCK, sync=False)
    assert result.path == [
        PriceStep(TOKEN, UsdPrice(15), "Lido wstETH via stEthPerToken"),
        child.path[0],
    ]
    assert result.path[1] is not child.path[0]
    monkeypatch.setattr(curve_gauge, "_get_lp_token", AsyncMock(return_value=CHILD))
    gauge = await curve_gauge.get_price(TOKEN, BLOCK, sync=False)
    assert gauge.path == [
        PriceStep(TOKEN, UsdPrice(10), f"Curve gauge for LP {CHILD}"),
        child.path[0],
    ]
    assert child.path == [PriceStep(CHILD, UsdPrice(10), "oracle")]


def test_selected_mypyc_modules_are_compiled() -> None:
    import importlib
    import tomllib
    from importlib.machinery import EXTENSION_SUFFIXES
    from pathlib import Path

    config = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    for path in config["tool"]["mypyc"]["files"]:
        module = importlib.import_module(path.removesuffix(".py").replace("/", "."))
        assert module.__file__ is not None
        assert any(
            module.__file__.endswith(suffix) for suffix in EXTENSION_SUFFIXES
        ), module.__file__


@run_async_test
async def test_v2_pool_exclusions_leave_cached_collection_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from y.prices.dex.uniswap.v2 import UniswapRouterV2

    class Pool:
        def __init__(self, address: str, deployed: int) -> None:
            self.address = address
            self.deploy_block = AsyncMock(return_value=deployed)

    first, second, future = Pool("first", 1), Pool("second", 2), Pool("future", BLOCK + 1)
    cached = {first: CHILD, second: CHILD, future: CHILD}
    router = instance(UniswapRouterV2)
    monkeypatch.setattr(UniswapRouterV2, "get_pools_for", AsyncMock(return_value=cached))
    selected = [pool async for pool in router.pools_for_token(TOKEN, BLOCK, ("FIRST",))]
    assert selected == [second]
    assert list(cached) == [first, second, future]
    selected = [pool async for pool in router.pools_for_token(TOKEN, BLOCK, ("second",))]
    assert selected == [first]
    for pool in cached:
        pool.deploy_block.assert_awaited_with(when_no_history_return_0=True, sync=False)


@run_async_test
async def test_bucket_cancellation_preserves_shared_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    from y._db.utils import token as db
    from y.prices.utils import buckets

    started, release, cancelled, drained = (asyncio.Event() for _ in range(4))

    class Registry(a_sync.ASyncGenericBase):
        def __init__(self) -> None:
            super().__init__()
            self.asynchronous = True

        @a_sync.aka.cached_property
        async def data(self) -> bool:
            started.set()
            try:
                await release.wait()
                return True
            except asyncio.CancelledError:
                cancelled.set()
                raise

    registry = Registry()

    async def check(*args: Any, **kwargs: Any) -> bool:
        try:
            return await registry.data
        finally:
            drained.set()

    monkeypatch.setattr(db, "get_bucket", AsyncMock(return_value=None))
    monkeypatch.setattr(buckets, "string_matchers", {})
    monkeypatch.setattr(buckets, "calls_only", {"shared": check})
    first = asyncio.create_task(buckets.check_bucket(TOKEN, BLOCK + 1, sync=False))
    await started.wait()
    second = asyncio.ensure_future(registry.data)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert drained.is_set()
    assert not cancelled.is_set()
    release.set()
    assert await second is True


@run_async_test
@pytest.mark.parametrize("via", ["previewRedeem", "convertToAssets"])
async def test_erc4626_ratio_and_wrapped_gas_paths(
    monkeypatch: pytest.MonkeyPatch, via: str
) -> None:
    from y.constants import EEE_ADDRESS
    from y.prices import erc4626, utils

    child = PriceResult(UsdPrice(4), [PriceStep(CHILD, UsdPrice(4), "oracle")])
    monkeypatch.setattr(
        erc4626,
        "ERC20",
        lambda address, **kwargs: SimpleNamespace(
            __scale__=Ready(10**6), symbol=Ready("VAULT" if address == TOKEN else "ASSET")
        ),
    )
    monkeypatch.setattr(erc4626, "raw_call", AsyncMock(return_value=CHILD))
    monkeypatch.setattr(
        erc4626,
        "_call_preview_redeem",
        AsyncMock(return_value=3 * 10**6 if via == "previewRedeem" else None),
    )
    monkeypatch.setattr(erc4626, "_call_convert_to_assets", AsyncMock(return_value=3 * 10**6))
    child_call = AsyncMock(return_value=child)
    with monkeypatch.context() as patch:
        patch.setattr(magic, "get_price", child_call)
        result = await erc4626.get_price(TOKEN, BLOCK, sync=False)
    assert float(result) == 12
    assert result.path[0].token == TOKEN and result.path[0].price == 12
    assert result.path[1] == child.path[0] and result.path[1] is not child.path[0]
    assert result.path[0].source == (
        f"ERC4626 vault VAULT ({TOKEN}) underlying ASSET ({CHILD}) via {via}"
    )

    monkeypatch.setattr(
        magic, "ERC20", lambda *args, **kwargs: SimpleNamespace(symbol=Ready("TEST"))
    )
    monkeypatch.setattr(magic, "_get_price_from_api", AsyncMock(return_value=None))
    monkeypatch.setattr(utils, "sense_check", AsyncMock())

    async def bucket(token: str, block: int, **kwargs: Any) -> str:
        return "wrapped gas coin" if str(token) == EEE_ADDRESS else "stable usd"

    monkeypatch.setattr(utils, "check_bucket", bucket)
    monkeypatch.setattr(magic, "chainlink", SimpleNamespace(get_price=AsyncMock(return_value=1)))
    gas = await magic.get_price(EEE_ADDRESS, BLOCK, skip_cache=True, sync=False)
    assert [step.token for step in gas.path] == [EEE_ADDRESS, str(constants.WRAPPED_GAS_COIN)]
    assert [float(step.price) for step in gas.path] == [1, 1]


@run_async_test
@pytest.mark.parametrize("velodrome", [False, True])
async def test_solidly_compares_stable_and_volatile_routes(
    monkeypatch: pytest.MonkeyPatch, velodrome: bool
) -> None:
    from y.prices.dex.solidly import SolidlyRouter
    from y.prices.dex.velodrome import VelodromeRouterV2

    cls = VelodromeRouterV2 if velodrome else SolidlyRouter
    router = instance(cls)
    router.factory = CHILD
    quoted = []

    async def pool(
        start: str, end: str, stable: bool, block: int, **kwargs: Any
    ) -> SimpleNamespace:
        assert (start, end, block) == (TOKEN, CHILD, BLOCK)
        return SimpleNamespace(address="stable" if stable else "volatile")

    async def amounts(
        amount: int, routes: list[tuple[object, ...]], block_identifier: int | None
    ) -> list[int]:
        assert amount == 10**18 and block_identifier == BLOCK
        quoted.append(routes)
        assert len(routes[0]) == (4 if velodrome else 3)
        return (amount, 3 if routes[0][2] else 8)

    monkeypatch.setattr(cls, "get_pool", staticmethod(pool))
    contract = SimpleNamespace(getAmountsOut=SimpleNamespace(coroutine=amounts))
    monkeypatch.setattr(cls, "contract", property(lambda self: contract))
    result = await router.get_quote(10**18, [TOKEN, CHILD], BLOCK, sync=False)
    assert result == (10**18, 8)
    assert len(quoted) == 2
    quoted.clear()
    result = await router.get_quote(10**18, [TOKEN, CHILD], BLOCK, pools=("stable",), sync=False)
    assert result == (10**18, 3)
    assert len(quoted) == 1


@run_async_test
@pytest.mark.parametrize("fallback", [False, True])
async def test_velodrome_discovery_uses_one_block(
    monkeypatch: pytest.MonkeyPatch, fallback: bool
) -> None:
    from web3.exceptions import ContractLogicError

    from y.prices.dex import velodrome as module

    calls = []

    class Head:
        reads = 0

        @property
        def block_number(self) -> Ready[int]:
            self.reads += 1
            return Ready(BLOCK + self.reads - 1)

    head = Head()
    monkeypatch.setattr(module, "dank_mids", SimpleNamespace(eth=head))

    async def count(factory: str, method: str, **kwargs: Any) -> int:
        calls.append((method, kwargs["block"]))
        return 1

    async def events(to_block: int) -> AsyncIterator[None]:
        calls.append(("events", to_block))
        for event in tuple[None, ...]():
            yield event

    async def index(indices: list[int], block_id: int) -> str:
        assert indices == [0]
        calls.append(("index", block_id))
        if fallback:
            raise ContractLogicError("execution reverted")
        return CHILD

    async def fallback_index(index: int, block_identifier: int | None) -> str:
        assert index == 0
        calls.append(("fallback", block_identifier))
        return CHILD

    async def methods(pool: str, signatures: tuple[str, ...], block: int) -> tuple[str, str, bool]:
        assert pool == CHILD and signatures == module._INIT_METHODS
        calls.append(("metadata", block))
        return TOKEN, CHILD, False

    class Pool:
        def __init__(self, address: str, token0: str, token1: str, **kwargs: Any) -> None:
            self.address = address
            self.__token0__, self.__token1__ = Ready(token0), Ready(token1)

    factory = SimpleNamespace(
        topics={"PoolCreated": "topic"},
        events=SimpleNamespace(PoolCreated=SimpleNamespace(events=events)),
        allPools=SimpleNamespace(coroutine=fallback_index),
    )
    monkeypatch.setattr(module, "raw_call", count)
    monkeypatch.setattr(
        module, "Contract", SimpleNamespace(coroutine=AsyncMock(return_value=factory))
    )
    monkeypatch.setattr(module, "gather_methods", methods)
    monkeypatch.setattr(module, "VelodromePool", Pool)
    router = instance(module.VelodromeRouterV2)
    router.factory, router.label = TOKEN, "test"
    router._all_pools = SimpleNamespace(coroutine=index)
    pools = await module.VelodromeRouterV2.__dict__["pools"].__wrapped__(router)
    assert [pool.address for pool in pools] == [CHILD]
    assert head.reads == 1
    assert calls == [("allPoolsLength()", BLOCK), ("events", BLOCK), ("index", BLOCK)] + (
        [("fallback", BLOCK)] if fallback else []
    ) + [("metadata", BLOCK)]


@run_async_test
@pytest.mark.parametrize("version", [1, 2])
async def test_balancer_lp_forwards_exclusions_to_underlying_prices(
    monkeypatch: pytest.MonkeyPatch, version: int
) -> None:
    from y.classes.common import WeiBalance
    from y.prices.dex.balancer.v1 import BalancerV1, BalancerV1Pool
    from y.prices.dex.balancer.v2 import BalancerV2, BalancerV2Pool

    cls, pool_cls = (BalancerV1, BalancerV1Pool) if version == 1 else (BalancerV2, BalancerV2Pool)
    pool = instance(pool_cls)
    pool.address = CHILD
    token = ERC20(TOKEN, asynchronous=True)
    excluded = ("excluded", pool)

    async def balances(self: Any, block: int, **kwargs: Any) -> dict[ERC20, Any]:
        assert block == BLOCK
        if version == 1:
            return {token: Decimal(3)}
        assert kwargs["ignore_pools"] == excluded
        return {token: WeiBalance(3, token, block=block, skip_cache=True, ignore_pools=excluded)}

    async def price(address: str, block: int, **kwargs: Any) -> PriceResult:
        assert str(address) == TOKEN and block == BLOCK
        assert kwargs["ignore_pools"] == excluded
        assert kwargs["skip_cache"] is True
        return PriceResult(UsdPrice(2), [])

    monkeypatch.setattr(pool_cls, "get_balances", balances)
    monkeypatch.setattr(pool_cls, "total_supply_readable", AsyncMock(return_value=4))
    monkeypatch.setattr(ERC20, "__scale__", property(lambda self: Ready(1)))
    monkeypatch.setattr(magic, "get_price", price)
    monkeypatch.setattr(cls, "_pool_type", staticmethod(lambda *args, **kwargs: pool))
    adapter = instance(cls)
    result = await adapter.get_pool_price(
        CHILD, BLOCK, skip_cache=True, ignore_pools=("excluded",), sync=False
    )
    assert float(result) == 1.5


@run_async_test
async def test_balancer_bucket_uses_lp_valuation_before_dex_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(utils, "check_bucket", AsyncMock(return_value="balancer pool"))
    adapter = SimpleNamespace(
        get_pool_price=AsyncMock(return_value=0), get_price=AsyncMock(return_value=9)
    )
    monkeypatch.setattr(magic, "balancer_multiplexer", adapter)
    result, source = await magic._exit_early_for_known_tokens(
        TOKEN, BLOCK, logging.getLogger(__name__), skip_cache=True, ignore_pools=("excluded",)
    )
    assert result == 0
    adapter.get_pool_price.assert_awaited_once_with(
        TOKEN, BLOCK, skip_cache=True, ignore_pools=("excluded",), sync=False
    )
    adapter.get_price.assert_not_awaited()


@run_async_test
@pytest.mark.parametrize("lp_price", [0, 2])
async def test_balancer_invalid_lp_valuation_continues_to_pool_quotes(
    monkeypatch: pytest.MonkeyPatch, lp_price: int
) -> None:
    from y.prices.dex.balancer.balancer import BalancerMultiplexer

    adapter = instance(BalancerMultiplexer)
    from y.prices import _routing

    route = AsyncMock(return_value=PriceResult(UsdPrice(9), []))
    monkeypatch.setattr(_routing, "liquidity_price", route)
    monkeypatch.setattr(BalancerMultiplexer, "is_balancer_pool", AsyncMock(return_value=True))
    monkeypatch.setattr(BalancerMultiplexer, "get_pool_price", AsyncMock(return_value=lp_price))
    result = await adapter.get_price(TOKEN, BLOCK, sync=False)
    assert float(result) == (2 if lp_price else 9)
    assert route.await_count == (0 if lp_price else 1)


@run_async_test
async def test_v2_pool_index_is_shared_and_results_are_copied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from y.prices.dex.uniswap.v2 import UniswapRouterV2

    class Pool:
        def __init__(self, first: str, second: str) -> None:
            self.pair = (first, second)
            self.reads = 0

        @a_sync.property
        async def tokens(self) -> tuple[str, str]:
            self.reads += 1
            return self.pair

    first, second = Pool(TOKEN, CHILD), Pool(TOKEN, "third")
    monkeypatch.setattr(UniswapRouterV2, "__pools__", property(lambda self: Ready([first, second])))
    router = instance(UniswapRouterV2)
    by_token, by_child = await asyncio.gather(
        router.all_pools_for(TOKEN, sync=False), router.all_pools_for(CHILD, sync=False)
    )
    assert by_token == {first: CHILD, second: "third"}
    assert by_child == {first: TOKEN}
    by_token.clear()
    assert await router.all_pools_for(TOKEN, sync=False) == {first: CHILD, second: "third"}
    assert (first.reads, second.reads) == (1, 1)
