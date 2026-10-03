"""Token indexes preserve both event positions and historical completeness."""

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock

import pytest

from tests.test_amount_quotes import CHILD, TOKEN, USD
from tests.test_pricing_correctness import Ready, instance, run_async_test
from y import convert
from y.contracts import Contract
from y.prices.dex.solidly import SolidlyRouter
from y.prices.dex.uniswap import v2, v3
from y.prices.dex.velodrome import VelodromeRouterV2
from y.utils.events import ProcessedEvents


class Event(dict[str, Any]):
    block_number: int
    blockNumber: int
    logIndex: int
    transactionHash: Any

    def __init__(self, block: int, **kwargs: Any) -> None:
        super().__init__(kwargs)
        self.block_number = block


def event_history(protocol: str) -> list[Event]:
    rows = [(10, TOKEN, USD), (10, CHILD, TOKEN), (20, TOKEN, CHILD), (12, USD, CHILD)]
    if protocol in ("v2", "solidly", "velodrome"):
        return [
            Event(
                block,
                token0=first,
                token1=second,
                **(
                    {"pool": f"0x{0x448800+i:040x}", "stable": i % 2 == 0}
                    if protocol == "velodrome"
                    else {
                        "pair": f"0x{0x445500+i:040x}",
                        **({"stable": i % 2 == 0} if protocol == "solidly" else {}),
                    }
                ),
            )
            for i, (block, first, second) in enumerate(rows)
        ]
    return [
        Event(
            block,
            token0=first,
            token1=second,
            **({"fee": 3000, "tick_spacing": 60} if protocol == "v3" else {"tick_spacing": 60}),
            pool=f"0x{0x446600+i+(100 if protocol == 'slipstream' else 0):040x}",
        )
        for i, (block, first, second) in enumerate(rows)
    ]


def setup_discovery(monkeypatch: Any, protocol: str) -> tuple[Any, list[Event], list[Any], Any]:
    rows = event_history(protocol)
    calls: list[Any] = []
    state = SimpleNamespace(failure=None)
    factory: Any = SimpleNamespace(address=USD, topics={"PoolCreated": "0x" + "12" * 32})
    if protocol in ("v2", "solidly", "velodrome"):
        router_type: Any = {
            "v2": v2.UniswapRouterV2,
            "solidly": SolidlyRouter,
            "velodrome": VelodromeRouterV2,
        }[protocol]
        router = instance(router_type)
        router.address, router.factory, router.label = CHILD, USD, "review"
        router._supports_factory_helper = False
        router._skip_factory_helper = set()
        from brownie.network.event import _deployment_topics

        monkeypatch.setitem(_deployment_topics, convert.to_address(USD), {})

        def no_inventory(self: Any) -> Any:
            raise AssertionError("started a full inventory")

        monkeypatch.setattr(type(router), "__pools__", property(no_inventory))
        monkeypatch.setattr(v2, "dank_eth", SimpleNamespace(block_number=Ready(30)))
    else:
        registry = (v3.UniV3Pools if protocol == "v3" else v3.SlipstreamPools)(factory, True)
        router = SimpleNamespace(__pools__=Ready(registry))

    async def objects(
        self: Any, to_block: int, from_block: int | None = None
    ) -> AsyncIterator[Any]:
        topics = self.topics
        assert len(topics) in (2, 3), "started an unfiltered full inventory"
        position = len(topics) - 1
        assert position == 1 or topics[1] is None
        assert self.addresses == [convert.to_address(USD)]
        calls.append((tuple(topics), from_block, to_block))
        for row in rows:
            token = row["token0" if position == 1 else "token1"]
            if topics[position] == "0x" + token[2:].lower().zfill(64):
                if (from_block or 0) <= row.block_number <= to_block:
                    yield self._process_event(row)
        if position == 2 and state.failure:
            raise state.failure

    monkeypatch.setattr(ProcessedEvents, "objects", objects)
    return router, rows, calls, state


async def discover(router: Any, protocol: str, token: Any, block: int) -> list[Any]:
    if protocol in ("v2", "solidly", "velodrome"):
        return list(await router.get_pools_for(token, block=block, sync=False))
    return [pool async for pool in v3.UniswapV3.pools_for_token(router, token, block)]


@run_async_test
@pytest.mark.parametrize("protocol", ["v2", "solidly", "velodrome", "v3", "slipstream"])
@pytest.mark.parametrize("block", [9, 10, 20])
@pytest.mark.parametrize("cached", [True, False])
@pytest.mark.parametrize("large_inventory", [False, True])
@pytest.mark.parametrize("raw_pages", [False, True])
async def test_compact_metadata_keeps_all_historical_candidates_without_pool_objects(
    monkeypatch: Any,
    protocol: str,
    block: int,
    cached: bool,
    large_inventory: bool,
    raw_pages: bool,
) -> None:
    from y import contracts
    from y._db import common
    from y._db.utils import logs
    from y.utils import events

    router, rows, _, _ = setup_discovery(monkeypatch, protocol)
    if large_inventory:
        for index in range(8201):
            row = Event(10, **rows[index % len(rows)])
            row["pool" if "pool" in row else "pair"] = f"0x{0x990000 + index:040x}"
            rows.append(row)
    monkeypatch.setattr(contracts, "contract_creation_block_async", AsyncMock(return_value=10))
    constructed = Mock(side_effect=AssertionError("constructed a pool object"))
    monkeypatch.setattr(v2, "UniswapV2Pool", constructed)
    monkeypatch.setattr(v3, "UniswapV3Pool", constructed)
    if protocol in ("v3", "slipstream"):
        router._factory = USD
        router.asynchronous = True
        factory = SimpleNamespace(address=USD, topics={"PoolCreated": "0x" + "12" * 32})
        monkeypatch.setattr(Contract, "coroutine", AsyncMock(return_value=factory))
        for row in rows:
            row["tickSpacing"] = row.pop("tick_spacing")
    from brownie.network.event import _EventItem

    monkeypatch.setattr(
        events,
        "decode_logs",
        lambda rows: [_EventItem("PairCreated", None, [row], (0,)) for row in rows],
    )

    coverage = [1000 if cached else 0]
    prefetched: list[Any] = []

    class Cache:
        def __init__(self, addresses: Any, topics: Any) -> None:
            self.position = len(topics) - 1

        def is_cached_thru(self, start: int) -> int:
            return coverage[0]  # Later history must not enter an earlier quote.

        def select(self, start: int, end: int) -> list[Event]:
            assert end <= block
            return [
                row
                for row in rows
                if start <= row.block_number <= end
                and row["token0" if self.position == 1 else "token1"] == TOKEN
            ]

        def select_page(self, start: int, end: int, after: Any, limit: int = 512) -> list[Event]:
            from hexbytes import HexBytes

            assert limit == 4096
            selected = self.select(start, end)
            for index, row in enumerate(selected):
                row.blockNumber = row.block_number
                row.logIndex = index
                row.transactionHash = HexBytes("0x01")
            selected.sort(key=lambda row: (row.blockNumber, row.logIndex))
            if after:
                selected = [row for row in selected if (row.blockNumber, row.logIndex) > after[:2]]
            return selected[:limit]

    if raw_pages:
        from msgspec import json

        from y.utils import _pool_events

        def raw_page(
            self: Cache, start: int, end: int, after: Any, limit: int
        ) -> tuple[list[bytes], Any]:
            page = self.select_page(start, end, after, limit)
            last = page[-1] if page else None
            cursor = (last.blockNumber, last.logIndex, last.transactionHash.hex()) if last else None
            return [json.encode(dict(row)) for row in page], cursor

        monkeypatch.setattr(Cache, "select_raw_page", raw_page, raising=False)
        monkeypatch.setattr(_pool_events, "decode_pool_raws", lambda raws: map(json.decode, raws))

    async def run(function: Any, *args: Any) -> Any:
        return function(*args)

    from y.utils import _factory_history

    async def fetch(addresses: Any, topics: Any, first: int, last: int) -> list[Event]:
        assert not prefetched, "repeated tiny reads after the shared window was committed"
        prefetched.append((first, last))
        selected = Cache(addresses, topics).select(first, last)
        coverage[0] = 1000
        return selected

    monkeypatch.setattr(_factory_history, "factory_logs", fetch)
    monkeypatch.setattr(v2, "indexed_chunk_size", lambda: 2)
    monkeypatch.setattr(v3, "indexed_chunk_size", lambda: 2)
    monkeypatch.setattr(logs, "LogCache", Cache)
    monkeypatch.setattr(common, "default_filter_threads", SimpleNamespace(run=run))
    monkeypatch.setattr(events, "_decode_threads", SimpleNamespace(run=run))
    if protocol in ("v3", "slipstream"):
        v3_batches = [
            batch async for batch in v3.UniswapV3.pool_metadata_batches(router, TOKEN, block)
        ]
        actual = {
            (item.address, (item.token0, item.token1)) for batch in v3_batches for item in batch
        }
        assert all(
            item.slipstream == (protocol == "slipstream") for batch in v3_batches for item in batch
        )
    else:
        batches = [batch async for batch in router.pool_metadata_batches(TOKEN, block)]
        actual = {(item.address, item.tokens) for batch in batches for item in batch}
        expected_stable = {
            str(row.get("pair", row.get("pool"))).lower(): row.get("stable") for row in rows
        }
        assert all(
            item.stable is expected_stable[item.address] for batch in batches for item in batch
        )
    expected = {
        (
            str(row.get("pair", row.get("pool"))).lower(),
            (row["token0"].lower(), row["token1"].lower()),
        )
        for row in rows
        if row.block_number <= block and TOKEN in (row["token0"], row["token1"])
    }
    assert actual == expected
    result_batches = v3_batches if protocol in ("v3", "slipstream") else batches
    assert all(
        len(batch) <= (6250 if protocol in ("v3", "slipstream") else 7500)
        for batch in result_batches
    )
    assert sum(map(len, v3_batches if protocol in ("v3", "slipstream") else batches)) == len(
        expected
    )
    constructed.assert_not_called()
    assert len(prefetched) == int(not cached and block >= 10)


@run_async_test
@pytest.mark.parametrize("protocol", ["v2", "solidly", "velodrome", "v3", "slipstream"])
@pytest.mark.parametrize("form", ["str", "bytes"])
async def test_indexed_positions_history_and_incremental_discovery(
    monkeypatch: Any, protocol: str, form: str
) -> None:
    router, rows, calls, _ = setup_discovery(monkeypatch, protocol)
    token = TOKEN if form == "str" else bytes.fromhex(TOKEN[2:])
    expected = [row.get("pair", row.get("pool")) for row in rows[:3]]
    for block, indices in [(10, [0, 1]), (9, []), (20, [0, 1, 2]), (10, [0, 1])]:
        pools = await discover(router, protocol, token, block)
        assert {pool.address for pool in pools} == {expected[i] for i in indices}
        assert len(pools) == len(indices)
        assert all(pool._deploy_block <= block for pool in pools)
        if protocol == "slipstream":
            assert all(isinstance(pool, v3.SlipstreamPool) and pool.fee == 0 for pool in pools)
    assert len(calls) == (8 if protocol in ("v2", "solidly", "velodrome") else 4)
    if protocol not in ("v2", "solidly", "velodrome"):
        assert [entry[1:] for entry in calls] == [(0, 10), (0, 10), (11, 20), (11, 20)]


@run_async_test
@pytest.mark.parametrize("protocol", ["v2", "solidly", "velodrome", "v3", "slipstream"])
@pytest.mark.parametrize("failure", [RuntimeError("RPC failed"), asyncio.CancelledError()])
async def test_failed_second_position_can_be_retried(
    monkeypatch: Any, protocol: str, failure: BaseException
) -> None:
    router, rows, _, state = setup_discovery(monkeypatch, protocol)
    state.failure = failure
    with pytest.raises(type(failure)):
        await discover(router, protocol, TOKEN, 20)
    if protocol not in ("v2", "solidly", "velodrome"):
        registry = await router.__pools__
        assert TOKEN not in registry._pools_loaded_through
    state.failure = None
    pools = await discover(router, protocol, TOKEN, 20)
    assert len(pools) == 3
    assert {pool._deploy_block for pool in pools} == {10, 20}


@run_async_test
async def test_v2_latest_returns_copy_and_helper_fallback_keeps_block(monkeypatch: Any) -> None:
    router, _, calls, _ = setup_discovery(monkeypatch, "v2")
    result = await router.all_pools_for(TOKEN, sync=False)
    assert len(result) == 3
    result.clear()
    assert len(await router.all_pools_for(TOKEN, sync=False)) == 3
    router._supports_factory_helper = True
    monkeypatch.setattr(
        v2,
        "FACTORY_HELPER",
        SimpleNamespace(
            getPairsFor=SimpleNamespace(coroutine=AsyncMock(side_effect=ValueError("timeout")))
        ),
    )
    assert len(await router.get_pools_for(TOKEN, block=10, sync=False)) == 2
    assert [call[2] for call in calls[-2:]] == [10, 10]


@run_async_test
@pytest.mark.parametrize("http", [False, True, "timeout"])
async def test_large_range_rejection_splits_without_gaps(
    monkeypatch: Any, http: bool | str
) -> None:
    from aiohttp import ClientResponseError

    from y.utils import _log_ranges as _indexed

    calls: list[tuple[int, int]] = []

    async def get_logs(args: Any) -> Any:
        start, end = int(args["fromBlock"], 16), int(args["toBlock"], 16)
        calls.append((start, end))
        if end - start + 1 > 10000:
            if http == "timeout":
                raise TimeoutError()
            if http:
                raise ClientResponseError(
                    cast(Any, SimpleNamespace(real_url="https://example.invalid")), (), status=400
                )
            raise ValueError("Log response size exceeded.")
        return [start, end]

    monkeypatch.setattr(_indexed, "_request_logs", get_logs)
    assert cast(Any, await _indexed.adaptive_logs([USD], ["signature", "token"], 1, 20001)) == [
        1,
        5001,
        5002,
        10001,
        10002,
        20001,
    ]
    assert calls == [(1, 20001), (1, 10001), (1, 5001), (5002, 10001), (10002, 20001)]


@run_async_test
@pytest.mark.parametrize("kind", ["http400", "http401", "rpc", "cancel"])
async def test_small_range_and_unexpected_errors_propagate(monkeypatch: Any, kind: str) -> None:
    from aiohttp import ClientResponseError

    from y.utils import _log_ranges as _indexed

    error: BaseException
    if kind.startswith("http"):
        error = ClientResponseError(
            cast(Any, SimpleNamespace(real_url="https://example.invalid")), (), status=int(kind[4:])
        )
    else:
        error = ValueError("invalid indexed topic") if kind == "rpc" else asyncio.CancelledError()
    request = AsyncMock(side_effect=error)
    monkeypatch.setattr(_indexed, "_request_logs", request)
    with pytest.raises(type(error)):
        await _indexed.adaptive_logs(
            [USD], ["signature", "token"], 1, 10000 if kind == "http400" else 1000000
        )
    request.assert_awaited_once()


@pytest.mark.parametrize("protocol", ["solidly", "velodrome"])
def test_native_stable_pool_creation_event_decodes(monkeypatch: Any, protocol: str) -> None:
    from brownie.network.event import _deployment_topics
    from evmspec import Log
    from evmspec.data._main import _decode_hook
    from faster_eth_abi import encode
    from msgspec import json

    from y.prices.dex.solidly import SolidlyPoolsFromEvents
    from y.prices.dex.velodrome import VelodromePool, VelodromePoolsFromEvents
    from y.utils.events import decode_logs

    factory = convert.to_address(USD)
    monkeypatch.setitem(_deployment_topics, factory, {})
    reader = (VelodromePoolsFromEvents if protocol == "velodrome" else SolidlyPoolsFromEvents)(
        factory, "review", True, token=TOKEN
    )
    pool_address = "0x0000000000000000000000000000000000449900"
    topics = [reader.PairCreated, "0x" + TOKEN[2:].zfill(64), "0x" + USD[2:].zfill(64)]
    if protocol == "velodrome":
        topics.append("0x" + hex(1)[2:].zfill(64))
        data = encode(["address", "uint256"], [pool_address, 1])
    else:
        data = encode(["bool", "address", "uint256"], [True, pool_address, 1])
    payload = {
        "address": factory,
        "topics": topics,
        "data": "0x" + data.hex(),
        "blockNumber": "0xa",
        "blockHash": "0x" + "aa" * 32,
        "transactionHash": "0x" + "bb" * 32,
        "logIndex": "0x0",
        "transactionIndex": "0x0",
        "removed": False,
    }
    log = json.decode(json.encode(payload), type=Log, dec_hook=_decode_hook)
    pool = reader._process_event(decode_logs([log])[0])
    assert pool.address == pool_address
    assert pool._deploy_block == 10
    assert str(pool.token0) == TOKEN and str(pool.token1) == USD
    if protocol == "velodrome":
        assert isinstance(pool, VelodromePool) and pool.is_stable is True


@pytest.mark.parametrize(
    "default,override,expected",
    [
        (2000, 0, 2000),
        (10000, 0, 10000),
        (800000, 0, 10000),
        (10000, 12345, 10000),
        (2000, 10000, 2000),
        (10000, 1000, 1000),
    ],
)
def test_indexed_range_respects_provider_and_explicit_limits(
    monkeypatch: Any, default: int, override: int, expected: int
) -> None:
    from y import ENVIRONMENT_VARIABLES as envs
    from y.utils import _log_ranges, middleware

    monkeypatch.setattr(envs, "GETLOGS_BATCH_SIZE", override)
    monkeypatch.setattr(middleware, "BATCH_SIZE", default)
    assert _log_ranges.indexed_chunk_size() == expected


@run_async_test
@pytest.mark.parametrize("kind", ["http400", "rpc_timeout"])
async def test_log_range_error_reaches_splitter_without_batch_retry(
    monkeypatch: Any, kind: str
) -> None:
    from aiohttp import ClientSession, web
    from web3 import AsyncHTTPProvider

    from y.utils import _log_ranges

    ranges: list[tuple[int, int]] = []

    async def rpc(request: web.Request) -> web.Response:
        body = await request.json()
        assert isinstance(body, dict), "discovery entered a JSON RPC batch"
        args = body["params"][0]
        start, end = int(args["fromBlock"], 16), int(args["toBlock"], 16)
        ranges.append((start, end))
        if end - start + 1 > 10000:
            return web.json_response(
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "error": (
                        {"code": 400, "message": "invalid block range given"}
                        if kind == "http400"
                        else {"code": -32002, "message": "request timed out"}
                    ),
                },
                status=400 if kind == "http400" else 200,
            )
        result = [
            {
                "address": USD,
                "topics": [],
                "data": "0x",
                "blockNumber": hex(block),
                "blockHash": "0x" + "aa" * 32,
                "transactionHash": "0x" + "bb" * 32,
                "logIndex": "0x0",
                "transactionIndex": "0x0",
                "removed": False,
            }
            for block in (start, end)
        ]
        return web.json_response({"jsonrpc": "2.0", "id": body["id"], "result": result})

    app = web.Application()
    app.router.add_post("/", rpc)
    runner = web.AppRunner(app)
    await runner.setup()
    import socket

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        site = web.SockSite(runner, listener)
        await site.start()
        port = listener.getsockname()[1]
        provider = AsyncHTTPProvider(f"http://127.0.0.1:{port}")
        session = await provider.cache_async_session(ClientSession())
        monkeypatch.setattr(
            _log_ranges,
            "dank_web3",
            SimpleNamespace(eth=SimpleNamespace(w3=SimpleNamespace(provider=provider))),
        )
        try:
            logs = await asyncio.wait_for(_log_ranges.adaptive_logs([USD], [], 1, 20001), 5)
            assert [log.blockNumber for log in logs] == [1, 5001, 5002, 10001, 10002, 20001]
            rejected = [(1, 20001), (1, 10001)]
            expected = rejected
            assert ranges == expected + [(1, 5001), (5002, 10001), (10002, 20001)]
        finally:
            await session.close()
            await runner.cleanup()


@run_async_test
async def test_single_block_rpc_timeout_is_bounded_and_propagates(monkeypatch: Any) -> None:
    from y.utils import _log_ranges

    provider = SimpleNamespace(
        make_request=AsyncMock(
            return_value={"error": {"code": -32002, "message": "request timed out"}}
        )
    )
    monkeypatch.setattr(
        _log_ranges,
        "dank_web3",
        SimpleNamespace(eth=SimpleNamespace(w3=SimpleNamespace(provider=provider))),
    )
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    with pytest.raises(TimeoutError):
        await _log_ranges.adaptive_logs([USD], [], 1, 1)
    assert provider.make_request.await_count == 2
    assert provider.make_request.await_args_list == [provider.make_request.await_args_list[0]] * 2


@run_async_test
@pytest.mark.parametrize("recover", [True, False])
async def test_log_rate_limit_retries_same_range_and_propagates_exhaustion(
    monkeypatch: pytest.MonkeyPatch, recover: bool
) -> None:
    from y.utils import _log_ranges

    rate_limit = {"error": {"code": 429, "message": "capacity exceeded"}}
    provider = SimpleNamespace(
        make_request=AsyncMock(
            side_effect=[rate_limit, {"result": []}] if recover else [rate_limit] * 5
        )
    )
    monkeypatch.setattr(
        _log_ranges,
        "dank_web3",
        SimpleNamespace(eth=SimpleNamespace(w3=SimpleNamespace(provider=provider))),
    )
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    if recover:
        assert await _log_ranges.adaptive_logs([USD], [], 10, 20) == []
    else:
        with pytest.raises(ConnectionError, match="rate limit exceeded"):
            await _log_ranges.adaptive_logs([USD], [], 10, 20)
    calls = provider.make_request.await_args_list
    assert len(calls) == (2 if recover else 5)
    assert all(call.args == calls[0].args for call in calls)
    assert calls[0].args[1] == [
        {"address": [USD], "topics": [], "fromBlock": "0xa", "toBlock": "0x14"}
    ]


@run_async_test
async def test_large_scan_preserves_transient_parse_error_retry(monkeypatch: Any) -> None:
    from y.utils import _log_ranges
    from y.utils.events import LogFilter

    request = AsyncMock(side_effect=[ValueError("parse error"), ValueError("parse error"), []])
    monkeypatch.setattr(_log_ranges, "adaptive_logs", request)
    reader = LogFilter(addresses=[USD], topics=[], from_block=1)
    assert await reader._fetch_range(1, 1000000) == []
    assert request.await_count == 3


@run_async_test
async def test_many_token_indexes_bound_database_workers() -> None:
    """Cold discovery across many tokens must not create a thread per filter."""
    from threading import get_ident

    factory: Any = SimpleNamespace(address=USD, topics={"PoolCreated": "0x" + "12" * 32})
    filters: list[ProcessedEvents[Any]] = []
    for token in (f"0x{number:040x}" for number in range(1, 129)):
        filters.extend(
            (
                v2.PoolsFromEvents(USD, "bounded workers", token=token),
                v3.UniV3Pools(factory, token=token),
            )
        )
    workers = await asyncio.gather(*(events.executor.run(get_ident) for events in filters))
    assert len(set(workers)) <= 4, "token count must not scale the database thread count"
