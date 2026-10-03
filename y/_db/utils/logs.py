import itertools
import logging
from collections.abc import Iterable, Sequence
from functools import lru_cache
from operator import getitem
from threading import Lock, local
from time import monotonic
from typing import Any, cast

import cachebox
from a_sync import a_sync, cgather
from a_sync.executor import _AsyncExecutorMixin
from brownie.network.event import _EventItem
from eth_typing import HexStr
from eth_utils.toolz import concat
from evmspec import Log as RpcLog
from evmspec.data import Address, BlockNumber, HexBytes32, uint
from evmspec.structs.log import Topic
from hexbytes import HexBytes
from msgspec import ValidationError, json
from pony.orm import Database, DatabaseError, commit, select
from pony.orm.core import Query

from y import ENVIRONMENT_VARIABLES as ENVS
from y import convert
from y._db.common import DiskCache, default_filter_threads, enc_hook, make_executor
from y._db.decorators import db_session_retry_locked, retry_locked
from y._db.entities import Block, FactoryLog, Hashes
from y._db.entities import Log as DbLog
from y._db.entities import LogCacheInfo, LogCacheRange, LogTopic
from y._db.log import Log
from y._db.log_coverage import completed_thru, topics_cover
from y._db.typing import db_session
from y._db.utils._ep import _get_get_block
from y._db.utils.bulk import insert as _bulk_insert
from y.constants import CHAINID

logger = logging.getLogger(__name__)

LOG_COLS = (
    "block_chain",
    "block_number",
    "tx",
    "log_index",
    "address",
    "topic0",
    "topic1",
    "topic2",
    "topic3",
    "raw",
)

_BLOCK_COLS = "chain", "number"
_BLOCK_COLS_EXTENDED = "chain", "number", "classtype"

_topic_executor = make_executor(4, 8, "ypricemagic db executor [topic]")
_hash_executor = make_executor(4, 8, "ypricemagic db executor [hash]")

_get_log_cache_info = LogCacheInfo.get
_get_log_topic = LogTopic.get
_get_hash = Hashes.get

_encode_generic = json.Encoder().encode
_encode_log = json.Encoder(enc_hook=enc_hook).encode


def _encode_factory_log(log: RpcLog) -> bytes:
    """Encode canonical RPC fields in the existing JSON array format."""
    numbers = (log.blockNumber, log.logIndex, log.transactionIndex)
    if (
        getattr(type(log), "__struct_fields__", None) == Log.__struct_fields__
        and isinstance(log.address, Address)
        and isinstance(log.data, HexBytes)
        and isinstance(log.transactionHash, HexBytes32)
        and isinstance(log.topics, (list, tuple))
        and all(isinstance(topic, HexBytes32) for topic in log.topics)
        and type(log.removed) is bool
        and all(isinstance(number, int) and not isinstance(number, bool) for number in numbers)
    ):
        return _encode_generic(
            (
                tuple(_remove_0x_prefix(topic.strip()) for topic in log.topics),
                log.address[2:],
                bytes(log.data).hex(),
                log.removed,
                int(cast(BlockNumber, log.blockNumber)),
                _remove_0x_prefix(log.transactionHash.strip()),
                int(log.logIndex),
                int(log.transactionIndex),
            )
        )
    # Keep the original codec's support and errors for noncanonical values.
    return _encode_log(Log(**log))


@lru_cache(maxsize=1)
def _factory_writer() -> _AsyncExecutorMixin:
    # One connection owns the enlarged SQLite page cache. Sharing the filter
    # executor would multiply this budget across its four connections.
    return make_executor(1, 8, "ypricemagic db executor [factory]")


@db_session_retry_locked
def _insert_factory_rows(rows: list[tuple[Any, ...]]) -> None:
    started = monotonic()
    database = cast(Database, getattr(FactoryLog, "_database_"))
    if getattr(database, "provider_name", None) == "sqlite":
        # Bound the page cache at 64 MiB while retaining the existing journal
        # and synchronous durability settings. Random token-index writes to a
        # multi-million-event catalog otherwise churn the default 2 MiB cache.
        database.execute("PRAGMA cache_size=-65536")
    _bulk_insert(
        FactoryLog,
        (
            "chain",
            "address",
            "block",
            "log_index",
            "txhash",
            "topic0",
            "topic1",
            "topic2",
            "topic3",
            "raw",
        ),
        rows,
        db=database,
        sync=True,
    )
    logger.debug("factory SQL rows=%s seconds=%.3f", len(rows), monotonic() - started)


def _decode_hook_unsafe(typ: type[Any], obj: Any) -> Any:
    """This decode hook does NOT ensure addresses are checksummed. They must be stored that way."""
    try:
        if issubclass(typ, uint):
            if isinstance(obj, int):
                return int.__new__(typ, obj)
            elif isinstance(obj, str):
                return typ(obj, 16)
        elif issubclass(typ, HexBytes):
            return typ(obj)
        elif typ is Address:
            # We have to put the 0x back on since we remove it for db storage.
            # The safe decode hook does that for us but the unsafe hook skips all validation.
            return str.__new__(Address, f"0x{obj}")
    except (TypeError, ValueError, ValidationError) as e:
        raise Exception(e, typ, obj) from e
    raise NotImplementedError(typ, obj)


# Match the JSON writer. Decoding cached data must not query or modify the database.
_decode_log = json.Decoder(type=Log, dec_hook=_decode_hook_unsafe).decode


# Pony invalidates shared translators when fixed topic attributes change.
# Construct event-page queries serially; database reads and decoding stay parallel.
_page_query_lock = Lock()


class _FactoryStatistics:
    """Keep SQLite's bounded index samples current without retaining event rows."""

    def __init__(self) -> None:
        self.ready = False
        self.large_sample = False
        self.pending_rows = 0
        self.lock = Lock()
        self.generation = 0
        self.connections = local()

    def _reload(self, database: Database) -> None:
        connection = database.get_connection()
        if (
            getattr(self.connections, "connection", None) is connection
            and getattr(self.connections, "generation", -1) == self.generation
        ):
            return
        try:
            # ANALYZE updates the analyzing connection's planner. Other
            # long-lived readers must reload the persisted samples themselves.
            database.execute("ANALYZE sqlite_schema")
            commit()
        except DatabaseError as error:
            logger.warning("factory cache index statistics reload unavailable: %s", error)
        else:
            self.connections.connection = connection
            self.connections.generation = self.generation

    def ensure(self, database: Database, *, added_rows: int = 0) -> None:
        if getattr(database, "provider_name", None) != "sqlite":
            return
        with self.lock:
            self.pending_rows += added_rows
            if self.ready and (
                not added_rows or (self.large_sample and self.pending_rows < 1_000_000)
            ):
                self._reload(database)
                return
            try:
                # Without statistics SQLite can prefer scanning every raw event
                # to the selective token index, even for an empty token page.
                # Limit samples per index instead of scanning the full catalog.
                database.execute("PRAGMA analysis_limit=1000")
                database.execute('ANALYZE "FactoryLog"')
                commit()
            except DatabaseError as error:
                logger.warning("factory cache index statistics unavailable: %s", error)
            else:
                self.ready = True
                self.large_sample = self.large_sample or bool(self.pending_rows)
                self.pending_rows = 0
                self.generation += 1
                self.connections.connection = database.get_connection()
                self.connections.generation = self.generation


@lru_cache(maxsize=32)
def _factory_statistics(database: Database) -> _FactoryStatistics:
    return _FactoryStatistics()


@db_session_retry_locked
def _refresh_factory_statistics(added_rows: int) -> None:
    database = cast(Database, getattr(FactoryLog, "_database_"))
    _factory_statistics(database).ensure(database, added_rows=added_rows)


def _prepare_log(
    log: RpcLog, hash_dbids: dict[str, int], topic_dbids: dict[str, int]
) -> tuple[Any, ...]:
    """
    Prepare a log for insertion into the database.

    Resolve references from the batch lookup maps, then encode the event as JSON.

    Args:
        log: The log entry to prepare.
        hash_dbids: Database IDs for the batch's transaction hashes and addresses.
        topic_dbids: Database IDs for the batch's topics.

    Returns:
        A tuple containing the prepared log parameters.

    Examples:
        >>> log = Log(transactionHash=HexBytes('0x1234'), address='0x...', topics=['0x...'], blockNumber=123, logIndex=0)
        >>> prepared_log = _prepare_log(log, hash_dbids, topic_dbids)
        >>> print(prepared_log)

    See Also:
        - :func:`enc_hook`
    """
    transaction_dbid = hash_dbids[_remove_0x_prefix(log.transactionHash.hex())]
    assert log.address is not None
    address_dbid = hash_dbids[_remove_0x_prefix(log.address)]
    event_topic_dbids = [topic_dbids[_remove_0x_prefix(topic.strip())] for topic in log.topics]
    topics = {
        f"topic{i}": topic_dbid
        for i, topic_dbid in itertools.zip_longest(range(4), event_topic_dbids)
    }
    params = {
        "block_chain": CHAINID,
        "block_number": log.blockNumber,
        "transaction": transaction_dbid,
        "log_index": log.logIndex,
        "address": address_dbid,
        **topics,
        "raw": _encode_log(Log(**log)),
    }
    return tuple(params.values())


def _get_dbids(entity: Any, attribute: str, values: tuple[str, ...]) -> dict[str, int]:
    """Read reference IDs within the database provider's SQL parameter limit."""
    remaining = iter(values)
    result: dict[str, int] = {}
    while batch := tuple(itertools.islice(remaining, entity._database_.provider.max_params_count)):
        result.update(
            select(
                (getattr(row, attribute), row.dbid)
                for row in entity
                if getattr(row, attribute) in batch
            )
        )
    return result


@retry_locked
def _prepare_logs(
    logs: Sequence[RpcLog], hashes: tuple[tuple[str], ...], topics: tuple[tuple[str], ...]
) -> list[tuple[Any, ...]]:
    with db_session:
        hash_dbids = _get_dbids(Hashes, "hash", tuple(row[0] for row in hashes))
        topic_dbids = _get_dbids(LogTopic, "topic", tuple(row[0] for row in topics))
    return [_prepare_log(log, hash_dbids, topic_dbids) for log in logs]


def _check_using_extended_db() -> bool:
    return "eth_portfolio" in _get_get_block().__module__


async def bulk_insert(
    logs: list[RpcLog], executor: _AsyncExecutorMixin = default_filter_threads
) -> None:
    if not logs:
        return

    submit = executor.submit

    # handle a conflict with eth-portfolio's extended db
    blocks: tuple[tuple[Any, ...], ...]
    if _check_using_extended_db():
        blocks = tuple(
            (CHAINID, block, "BlockExtended") for block in {log.blockNumber for log in logs}
        )
        blocks_fut = submit(_bulk_insert, Block, _BLOCK_COLS_EXTENDED, blocks, sync=True)
    else:
        blocks = tuple((CHAINID, block) for block in {log.blockNumber for log in logs})
        blocks_fut = submit(_bulk_insert, Block, _BLOCK_COLS, blocks, sync=True)
    del blocks

    txhashes = (txhash.hex() for txhash in {log.transactionHash for log in logs})
    addresses = {cast(str, log.address) for log in logs}
    hashes = tuple((_remove_0x_prefix(hash),) for hash in itertools.chain(txhashes, addresses))
    hashes_fut = submit(_bulk_insert, Hashes, ("hash",), hashes, sync=True)
    del txhashes, addresses

    topics = tuple(
        (_remove_0x_prefix(topic.strip()),) for topic in set(concat(log.topics for log in logs))
    )
    topics_fut = submit(
        _bulk_insert,
        LogTopic,
        ("topic",),
        topics,
        sync=True,
    )
    await cgather(blocks_fut, hashes_fut, topics_fut)

    await executor.run(
        _bulk_insert,
        DbLog,
        LOG_COLS,
        await executor.run(_prepare_logs, logs, hashes, topics),
        sync=True,
    )


async def bulk_insert_factory(logs: list[RpcLog]) -> None:
    """Persist raw discovery history in one table instead of four reference tables."""
    if not logs:
        return

    def prepare() -> list[tuple[Any, ...]]:
        started = monotonic()
        for log in logs:
            if log.blockNumber is None:
                raise ValueError("Factory event has no completed block")
        rows = [
            (
                CHAINID,
                str(log.address).lower(),
                int(cast(BlockNumber, log.blockNumber)),
                int(log.logIndex),
                log.transactionHash.hex(),
                *(
                    _remove_0x_prefix(log.topics[i].strip()) if i < len(log.topics) else ""
                    for i in range(4)
                ),
                _encode_factory_log(log),
            )
            for log in logs
        ]
        logger.debug("factory prepare rows=%s seconds=%.3f", len(rows), monotonic() - started)
        return rows

    rows = await default_filter_threads.run(prepare)
    await _factory_writer().run(_insert_factory_rows, rows)
    if len(logs) >= 4096:
        await default_filter_threads.run(_refresh_factory_statistics, len(logs))


# Cache completed IDs once for both synchronous and asynchronous callers.
@a_sync(default="async", executor=_topic_executor)
@retry_locked
@cachebox.cached(cachebox.LRUCache(ENVS.DEFAULT_CACHE_MAXSIZE))
@db_session_retry_locked
def get_topic_dbid(topic: Topic) -> int:
    topic_text = _remove_0x_prefix(topic.strip())
    entity = _get_log_topic(topic=topic_text)
    if entity is None:
        entity = LogTopic(topic=topic_text)
    return entity.dbid


@cachebox.cached(cachebox.TTLCache(10000, ttl=600))
async def get_hash_dbid(txhash: HexStr) -> int:
    return await _get_hash_dbid(txhash)


@a_sync(default="async", executor=_hash_executor)
@db_session_retry_locked
def _get_hash_dbid(hexstr: HexStr) -> int:
    if len(hexstr) == 42:
        hexstr = convert.to_address(hexstr)
    string = _remove_0x_prefix(hexstr)
    entity = _get_hash(hash=string)
    if entity is None:
        entity = Hashes(hash=string)
    return entity.dbid


def get_decoded(log: RpcLog) -> _EventItem[Any] | None:
    # TODO: load these in bulk
    entity = getitem(DbLog, (CHAINID, log.block_number, log.transaction_hash, log.log_index))
    if decoded := getattr(entity, "decoded"):
        return _EventItem(
            decoded["name"], decoded["address"], decoded["event_data"], decoded["pos"]
        )
    return None


@db_session
@retry_locked
def set_decoded(log: RpcLog, decoded: _EventItem[Any]) -> None:
    entity = getitem(DbLog, (CHAINID, log.block_number, log.transaction_hash, log.log_index))
    setattr(entity, "decoded", decoded)


page_size = 100


class LogCache(DiskCache[Log, LogCacheInfo]):
    __slots__ = "addresses", "topics"

    def __init__(self, addresses: Any, topics: Any) -> None:
        self.addresses = addresses
        self.topics = topics

    def __repr__(self) -> str:
        string = f"{type(self).__name__}(addresses={self.addresses}"
        for topic in ("topic0", "topic1", "topic2", "topic3"):
            if value := getattr(self, topic):
                string += f", {topic}={value}"
        return f"{string})"

    @property
    def topic0(self) -> str | list[str] | None:
        return self.topics[0] if self.topics else None

    @property
    def topic1(self) -> str | list[str] | None:
        return self.topics[1] if self.topics and len(self.topics) > 1 else None

    @property
    def topic2(self) -> str | list[str] | None:
        return self.topics[2] if self.topics and len(self.topics) > 2 else None

    @property
    def topic3(self) -> str | list[str] | None:
        return self.topics[3] if self.topics and len(self.topics) > 3 else None

    def load_metadata(self) -> LogCacheInfo | None:
        """Loads the cache metadata from the db."""
        if self.addresses:
            raise NotImplementedError(self.addresses)

        from y._db.utils import utils as db

        chain = db.get_chain(sync=True)
        # If we cached all of this topic0 with no filtering for all addresses
        if self.topic0 and (
            info := _get_log_cache_info(
                chain=chain,
                address="None",
                topics=_encode_generic([self.topic0]),
            )
        ):
            return info
        # If we cached these specific topics for all addresses
        elif self.topics and (
            info := _get_log_cache_info(
                chain=chain,
                address="None",
                topics=_encode_generic(self.topics),
            )
        ):
            return info
        return None

    def _is_cached_thru(self, from_block: int) -> int:
        from y._db.utils import utils as db

        chain = db.get_chain(sync=True)
        addresses = (
            [self.addresses]
            if isinstance(self.addresses, str)
            else list(self.addresses or ["None"])
        )
        # The range table is authoritative once a legacy filter has been migrated.
        scopes = ["none", *(str(address).lower() for address in addresses)]
        modern: list[LogCacheRange] = list(
            select(
                row for row in LogCacheRange if row.chain == chain and row.address.lower() in scopes
            )
        )
        migrated = {(row.address.lower(), row.topics) for row in modern}
        legacy: list[LogCacheInfo] = [
            row
            for row in select(
                row for row in LogCacheInfo if row.chain == chain and row.address.lower() in scopes
            )
            if (row.address.lower(), row.topics) not in migrated
        ]
        through = []
        rows: list[LogCacheRange | LogCacheInfo] = [*modern, *legacy]
        for address in addresses:
            ranges = []
            for row in rows:
                if row.address != "None" and row.address.lower() != str(address).lower():
                    continue
                if topics_cover(json.decode(row.topics), self.topics):
                    ranges.append((row.cached_from, row.cached_thru))
            through.append(completed_thru(from_block, ranges))
        result = min(through, default=0)
        logger.debug(
            "event cache reuse addresses=%s topics=%s from=%s thru=%s",
            self.addresses,
            self.topics,
            from_block,
            result,
        )
        return result

    def _select(self, from_block: int, to_block: int) -> list[Log]:
        modern = [_decode_log(row[3]) for row in self._factory_query(from_block, to_block)]
        legacy = self._select_legacy(from_block, to_block)
        return self._merge_logs(legacy, modern)

    @staticmethod
    def _merge_logs(legacy: list[Log], modern: list[Log]) -> list[Log]:
        if not modern:
            return legacy
        unique = {
            (
                int(cast(BlockNumber, log.blockNumber)),
                int(log.logIndex),
                log.transactionHash.hex(),
            ): log
            for log in [*legacy, *modern]
        }
        return [unique[key] for key in sorted(unique)]

    @db_session_retry_locked
    def select_page(
        self,
        from_block: int,
        to_block: int,
        after: tuple[int, int, str] | None = None,
        limit: int = 512,
    ) -> list[Log]:
        """Read a bounded event page, even across very sparse completed history."""
        modern_query, legacy_query = self._page_queries(from_block, to_block, after, limit)
        modern = [_decode_log(row[3]) for row in modern_query.limit(limit)]
        legacy = [_decode_log(row[3]) for row in legacy_query.limit(limit)]
        return self._merge_logs(legacy, modern)[:limit]

    @db_session_retry_locked
    def select_raw_page(
        self,
        from_block: int,
        to_block: int,
        after: tuple[int, int, str] | None = None,
        limit: int = 512,
    ) -> tuple[list[bytes], tuple[int, int, str] | None]:
        """Read the same ordered event page without constructing log wrappers."""
        modern_query, legacy_query = self._page_queries(from_block, to_block, after, limit)
        # Both projections already carry their full ordering keys. Normalize
        # legacy unprefixed hashes before deduplicating, with modern rows taking
        # precedence exactly as in _merge_logs.
        unique = {
            (block, index, "0x" + txhash.removeprefix("0x").zfill(64)): raw
            for block, txhash, index, raw in legacy_query.limit(limit)
        }
        unique.update(
            {(block, index, txhash): raw for block, index, txhash, raw in modern_query.limit(limit)}
        )
        keys = sorted(unique)[:limit]
        return [unique[key] for key in keys], keys[-1] if keys else None

    def _page_queries(
        self, from_block: int, to_block: int, after: tuple[int, int, str] | None, limit: int
    ) -> tuple["Query[Any, Any]", "Query[Any, Any]"]:
        with _page_query_lock:
            return self._page_queries_locked(from_block, to_block, after, limit)

    def _page_queries_locked(
        self, from_block: int, to_block: int, after: tuple[int, int, str] | None, limit: int
    ) -> tuple["Query[Any, Any]", "Query[Any, Any]"]:
        if not 1 <= limit <= 4096:
            raise ValueError("event page limit must be between 1 and 4096")
        database = cast(Database, getattr(FactoryLog, "_database_"))
        _factory_statistics(database).ensure(database)
        if after:
            from_block = max(from_block, after[0])
        modern_query = self._factory_query(from_block, to_block)
        legacy_query = self._get_query(from_block, to_block)
        if after:
            last_block, last_index, last_tx = after
            # Pony accepts unpacked projections; pony-stubs models one argument.
            modern_query = modern_query.filter(
                lambda block, index, txhash, raw: block > last_block  # type: ignore[misc,arg-type]
                or (block == last_block and index > last_index)
                or (block == last_block and index == last_index and txhash > last_tx)
            )
            # Legacy hashes omit the 0x prefix used by raw RPC events.
            last_tx = _remove_0x_prefix(last_tx)
            legacy_query = legacy_query.filter(
                lambda block, txhash, index, raw: block > last_block  # type: ignore[misc,arg-type]
                or (block == last_block and index > last_index)
                or (block == last_block and index == last_index and txhash > last_tx)
            )
        return modern_query, legacy_query

    def _factory_query(self, from_block: int, to_block: int) -> "Query[Any, Any]":
        from y._db.utils import utils as db

        chain_id = db.get_chain(sync=True).id
        generator: Iterable[FactoryLog] = (
            row
            for row in FactoryLog
            if row.chain == chain_id and row.block >= from_block and row.block <= to_block
        )
        if self.addresses:
            addresses = [self.addresses] if isinstance(self.addresses, str) else self.addresses
            addresses = tuple(str(address).lower() for address in addresses)
            generator = (row for row in generator if row.address in addresses)
        for i in range(4):
            generator = self._wrap_factory_topic(generator, f"topic{i}")
        raw = select((row.block, row.log_index, row.txhash, row.raw) for row in generator)
        return raw.order_by(1, 2, 3)

    def _wrap_factory_topic(
        self, generator: Iterable[FactoryLog], field: str
    ) -> Iterable[FactoryLog]:
        if not (constraint := getattr(self, field)):
            return generator
        values = [constraint] if isinstance(constraint, (bytes, str)) else constraint
        choices = tuple(_remove_0x_prefix(HexBytes32(value).strip()) for value in values)
        return (row for row in generator if getattr(row, field) in choices)

    def _select_legacy(self, from_block: int, to_block: int) -> list[Log]:
        logger.info("executing select query for %s", self)
        try:
            return [_decode_log(row[3]) for row in self._get_query(from_block, to_block)]
        except ValidationError:
            results = []
            for row in self._get_query(from_block, to_block):
                try:
                    results.append(_decode_log(row[3]))
                except ValidationError as e:
                    raise ValueError(e, json.decode(row[3])) from e
            return results

    def _get_query(
        self, from_block: int, to_block: int
    ) -> "Query[tuple[int, str, int, bytes], tuple[int, str, int, bytes]]":
        from y._db.utils import utils as db

        generator: Iterable[DbLog] = (
            log
            for log in DbLog
            if log.block.chain == db.get_chain(sync=True)
            and log.block.number >= from_block
            and log.block.number <= to_block
        )

        generator = self._wrap_query_with_addresses(generator)

        for topic in [f"topic{i}" for i in range(4)]:
            generator = self._wrap_query_with_topic(generator, topic)

        query = (
            # Project the body with its ordering keys. Fetching Log entities would
            # leave their lazy raw fields unloaded and issue one query per event.
            select((log.block.number, log.tx.hash, log.log_index, log.raw) for log in generator)
            .without_distinct()
            .order_by(1, 3, 2)
        )
        logger.debug(query.get_sql())
        return query

    def _set_metadata(self, from_block: int, done_thru: int) -> None:
        from y._db.utils import utils as db

        chain = db.get_chain(sync=True)
        encoded_topics = _encode_generic(self.topics or None)
        addresses = (
            [self.addresses]
            if isinstance(self.addresses, str)
            else list(self.addresses or ["None"])
        )
        for address in addresses:
            existing = list(
                select(
                    row
                    for row in LogCacheRange
                    if row.chain == chain
                    and row.address == address
                    and row.topics == encoded_topics
                )
            )
            legacy = _get_log_cache_info(chain=chain, address=address, topics=encoded_topics)
            if not existing and legacy:
                LogCacheRange(
                    chain=chain,
                    address=address,
                    topics=encoded_topics,
                    cached_from=legacy.cached_from,
                    cached_thru=legacy.cached_thru,
                )
                # Flush before merging, so a matching start is not inserted twice.
                commit()
                existing = list(
                    select(
                        row
                        for row in LogCacheRange
                        if row.chain == chain
                        and row.address == address
                        and row.topics == encoded_topics
                    )
                )
            first, last = from_block, done_thru
            for row in existing:
                if row.cached_from <= last + 1 and row.cached_thru + 1 >= first:
                    first, last = (
                        min(first, row.cached_from),
                        max(last, row.cached_thru),
                    )
                    row.delete()
            # Flush deletes before reusing a range's primary key.
            commit()
            LogCacheRange(
                chain=chain,
                address=address,
                topics=encoded_topics,
                cached_from=first,
                cached_thru=last,
            )
            if legacy is None:
                LogCacheInfo(
                    chain=chain,
                    address=address,
                    topics=encoded_topics,
                    cached_from=first,
                    cached_thru=last,
                )
            elif legacy.cached_from <= last + 1 and legacy.cached_thru + 1 >= first:
                legacy.cached_from = min(first, legacy.cached_from)
                legacy.cached_thru = max(last, legacy.cached_thru)
        commit()
        logger.debug(
            "cached %s %s range %s to %s",
            self.addresses,
            self.topics,
            from_block,
            done_thru,
        )

    def _wrap_query_with_addresses(self, generator: Iterable[DbLog]) -> Iterable[DbLog]:
        if not (addresses := self.addresses):
            return generator
        elif isinstance(addresses, str):
            address = convert.to_address(addresses)[2:]
            return (log for log in generator if log.address.hash == address)
        addresses = tuple(convert.to_address(address)[2:] for address in addresses)
        return (log for log in generator if log.address.hash in addresses)

    def _wrap_query_with_topic(self, generator: Iterable[DbLog], topic_id: str) -> Iterable[DbLog]:
        if not (topic_or_topics := getattr(self, topic_id)):
            return generator

        if isinstance(topic_or_topics, (bytes, str)):
            topic = topic_or_topics
            topic = _remove_0x_prefix(HexBytes32(topic).strip())
            return (log for log in generator if getattr(log, topic_id).topic == topic)

        topics = [_remove_0x_prefix(HexBytes32(v).strip()) for v in topic_or_topics]
        return (log for log in generator if getattr(log, topic_id).topic in topics)


def _remove_0x_prefix(string: str) -> str:  # sourcery skip: str-prefix-suffix
    if not isinstance(string, str):
        raise TypeError(type(string), string)
    return string[2:] if string[:2] == "0x" else string
