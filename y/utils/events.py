from abc import abstractmethod
from asyncio import AbstractEventLoop, as_completed, get_event_loop, sleep
from collections import Counter, defaultdict
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterable, Mapping, Sequence
from functools import cached_property, wraps
from inspect import isawaitable
from itertools import zip_longest
from logging import getLogger
from threading import current_thread, main_thread
from typing import TYPE_CHECKING, Any, NoReturn, TypeVar, cast

import a_sync
import dank_mids
import eth_retry
from a_sync import igather
from a_sync.executor import _AsyncExecutorMixin
from brownie import web3
from brownie.network.event import (
    EventDict,
    _add_deployment_topics,
    _decode_logs,
    _deployment_topics,
    _EventItem,
)
from dank_mids.brownie_patch import dank_eth
from eth_typing import BlockNumber, ChecksumAddress
from eth_utils.toolz import concat, groupby
from evmspec import Log
from msgspec.structs import force_setattr
from typing_extensions import TypeVar as DefaultTypeVar
from web3.middleware.filter import block_ranges
from web3.types import FilterParams, LogReceipt

from y import ENVIRONMENT_VARIABLES as ENVS
from y._db.common import Filter, _clean_addresses, make_executor
from y._typing import async_property
from y.datatypes import Address, AnyAddressType, Block
from y.exceptions import reraise_excs_with_extra_context
from y.utils.cache import memory
from y.utils.middleware import BATCH_SIZE

if TYPE_CHECKING:
    from y._db.utils.logs import LogCache


T = TypeVar("T")
_StoredLog = DefaultTypeVar("_StoredLog", default=Log)
_StoredEvent = DefaultTypeVar("_StoredEvent", default=_EventItem[Any])

logger = getLogger(__name__)

# Event decoding must not wait behind writes on a filter's database executor.
_decode_threads = make_executor(1, 1, "ypricemagic event decoder")


def decode_logs(logs: Iterable[LogReceipt | Log]) -> EventDict | list[_EventItem[Any]]:
    # NOTE: we want to ensure backward-compatability with LogReceipt
    """
    Decode logs to events and enrich them with additional info.

    Args:
        logs: An iterable of :class:`~web3.types.LogReceipt` or :class:`~evmspec.Log` objects.

    Returns:
        An :class:`~brownie.network.event.EventDict` containing decoded events.

    Examples:
        >>> logs = [LogReceipt(...), LogReceipt(...)]
        >>> events = decode_logs(logs)
        >>> print(events)

    See Also:
        - :class:`~brownie.network.event.EventDict`
    """
    entries = list(logs)
    if not entries:
        return EventDict()

    from y.contracts import Contract
    from y.convert import to_address

    for log in entries:
        address = to_address(log["address"])
        if address not in _deployment_topics:
            _add_deployment_topics(address, Contract(address).abi)

    # Brownie's decoder mutates topics with pop(); restore immutable RPC logs
    # even when decoding fails, since other readers can share these objects.
    structs = [log for log in entries if isinstance(log, Log)]
    original_topics = [log.topics for log in structs]
    for log in structs:
        force_setattr(log, "topics", list(log.topics))
    try:
        decoded: EventDict | list[_EventItem[Any]]
        try:
            decoded = _decode_logs(cast(list[Mapping[str, Any]], entries))
        except Exception:
            decoded = []
            for log in entries:
                with reraise_excs_with_extra_context(log):
                    decoded.extend(_decode_logs(cast(list[Mapping[str, Any]], [log])))

        with reraise_excs_with_extra_context(len(entries), decoded):
            for i, log in enumerate(entries):
                setattr(decoded[i], "block_number", log["blockNumber"])
                setattr(decoded[i], "transaction_hash", log["transactionHash"])
                setattr(decoded[i], "log_index", log["logIndex"])
        return decoded
    finally:
        for log, topics in zip(structs, original_topics):
            force_setattr(log, "topics", topics)


@a_sync.a_sync(default="sync")
async def get_logs_asap(
    address: Address | None,
    topics: list[str] | None,
    from_block: Block | None = None,
    to_block: Block | None = None,
    verbose: int = 0,
) -> list[Any]:
    """
    Get logs as soon as possible.

    This function fetches raw logs from the blockchain within the specified block range.
    The logs are not decoded; use :func:`decode_logs` to decode them if needed.

    Args:
        address: The address of the contract to fetch logs from.
        topics: The event topics to filter logs by.
        from_block: The starting block to fetch logs from.
        to_block: The ending block to fetch logs to.
        verbose: Verbosity level for logging.

    Returns:
        A list of raw logs.

    Examples:
        Synchronous usage:
        >>> logs = get_logs_asap("0x1234...", ["0x5678..."], 1000000, 1000100)
        >>> decoded_logs = decode_logs(logs)

        Asynchronous usage:
        >>> logs = await get_logs_asap("0x1234...", ["0x5678..."], 1000000, 1000100, sync=False)
        >>> decoded_logs = decode_logs(logs)

    See Also:
        - :func:`decode_logs`
    """
    if from_block is None:
        from y.contracts import contract_creation_block_async

        from_block = 0 if address is None else await contract_creation_block_async(address, True)
    if to_block is None:
        to_block = await dank_eth.block_number

    ranges = list(block_ranges(BlockNumber(from_block), BlockNumber(to_block), BATCH_SIZE))
    if verbose > 0:
        logger.info("fetching %d batches", len(ranges))

    batches = await igather(_get_logs_async(address, topics, start, end) for start, end in ranges)
    return list(concat(batches))


async def get_logs_asap_generator(
    address: Address | None,
    topics: list[str] | None = None,
    from_block: Block | None = None,
    to_block: Block | None = None,
    chronological: bool = True,
    run_forever: bool = False,
    run_forever_interval: int = 60,
    verbose: int = 0,
) -> AsyncGenerator[list[LogReceipt], None]:  # sourcery skip: low-code-quality
    """
    Get logs as soon as possible in a generator.

    This function fetches raw logs from the blockchain within the specified block range
    and yields them as they are retrieved. The logs are not decoded; use :func:`decode_logs`
    to decode them if needed.

    Args:
        address: The address of the contract to fetch logs from.
        topics: The event topics to filter logs by.
        from_block: The starting block to fetch logs from.
        to_block: The ending block to fetch logs to.
        chronological: If True, yield logs in chronological order.
        run_forever: If True, run indefinitely, fetching new logs periodically.
        run_forever_interval: The interval in seconds to wait between fetches when running forever.
        verbose: Verbosity level for logging.

    Yields:
        Lists of raw logs.

    Examples:
        >>> async for logs in get_logs_asap_generator("0x1234...", ["0x5678..."], 1000000, 1000100):
        ...     decoded_logs = decode_logs(logs)

    See Also:
        - :func:`decode_logs`
    """
    # NOTE: If you don't need the logs in order, you will get your logs faster if you set `chronological` to False.

    if from_block is None:
        from y.contracts import contract_creation_block_async

        if address is None:
            from_block = 0
        elif isinstance(address, Iterable) and not isinstance(address, str):
            from_block = await _lowest_deploy_block(address, when_no_history_return_0=True)
        else:
            from_block = await contract_creation_block_async(address, True)
    if to_block is None:
        to_block = await dank_eth.block_number
    elif run_forever:
        raise TypeError("`to_block` must be None if `run_forever` is True.")
    if from_block > to_block:
        raise ValueError(
            f"from_block must be <= to_block. You passed from_block: {from_block} to_block: {to_block}."
        )
    while True:
        ranges = list(block_ranges(BlockNumber(from_block), BlockNumber(to_block), BATCH_SIZE))
        if verbose > 0:
            logger.info("fetching %d batches", len(ranges))
        coros = [_get_logs_async(address, topics, start, end) for start, end in ranges]
        if chronological:
            yielded = 0
            done = {}
            async for i, result in a_sync.as_completed(dict(enumerate(coros)), aiter=True):
                done[i] = result
                for i in range(len(coros)):
                    if yielded > i:
                        continue
                    if i not in done:
                        break
                    yield done.pop(i)
                    yielded += 1
        else:
            for logs in as_completed(coros, timeout=None):
                yield await logs
        if not run_forever:
            return

        await sleep(run_forever_interval)

        # Find start and end block for next loop
        current_block = await dank_eth.block_number
        while current_block <= to_block:
            await sleep(run_forever_interval)
            current_block = await dank_eth.block_number
        from_block = to_block + 1 if to_block + 1 <= current_block else current_block
        to_block = current_block


def logs_to_balance_checkpoints(
    logs: Iterable[LogReceipt | Log],
) -> dict[ChecksumAddress, dict[Block, int]]:
    """
    Convert Transfer logs to `{address: {from_block: balance}}` checkpoints.

    Args:
        logs: An iterable of logs to convert.

    Returns:
        A dictionary mapping addresses to balance checkpoints.

    Examples:
        >>> logs = [Log(...), Log(...)]
        >>> checkpoints = logs_to_balance_checkpoints(logs)
        >>> print(checkpoints)
    """
    balances: Counter[ChecksumAddress] = Counter()
    checkpoints: defaultdict[ChecksumAddress, dict[Block, int]] = defaultdict(dict)
    for block, block_logs in groupby("blockNumber", logs).items():
        events = decode_logs(block_logs)
        for log in events:
            # ZERO_ADDRESS tracks -totalSupply
            (
                sender,
                receiver,
                amount,
            ) = log.values()  # there can be several different aliases
            balances[sender] -= amount
            checkpoints[sender][block] = balances[sender]
            balances[receiver] += amount
            checkpoints[receiver][block] = balances[receiver]
    return checkpoints


def checkpoints_to_weight(
    checkpoints: Mapping[Block, int], start_block: Block, end_block: Block
) -> float:
    """
    Calculate the weight of checkpoints between two blocks.

    Args:
        checkpoints: A dictionary of checkpoints.
        start_block: The starting block number.
        end_block: The ending block number.

    Returns:
        The calculated weight.

    Examples:
        >>> checkpoints = {0: 100, 10: 200}
        >>> weight = checkpoints_to_weight(checkpoints, 0, 10)
        >>> print(weight)
    """
    total: float = 0
    for a, b in zip_longest(list(checkpoints), list(checkpoints)[1:]):
        if a is None or a < start_block or a > end_block:
            continue
        b = min(b, end_block) if b else end_block
        total += checkpoints[a] * (b - a) / (end_block - start_block)
    return total


@a_sync.a_sync
def _get_logs(
    address: Address | None,
    topics: list[str] | None,
    start: Block,
    end: Block,
) -> list[LogReceipt]:
    """
    Get logs for a given address, topics, and block range.

    Args:
        address: The address of the contract to fetch logs from.
        topics: The event topics to filter logs by.
        start: The starting block to fetch logs from.
        end: The ending block to fetch logs to.

    Returns:
        A list of raw logs.

    Examples:
        >>> logs = _get_logs("0x1234...", ["0x5678..."], 1000000, 1000100)
        >>> print(logs)
    """
    if end - start == BATCH_SIZE - 1:
        response = _get_logs_batch_cached(address, topics, start, end)
    else:
        response = _get_logs_no_cache(address, topics, start, end)
    if address:
        """I have this due to a corrupt cache on my local box that I would prefer not to lose."""
        """ It will not impact your scripts. """
        response = [log for log in response if log["address"] == str(address)]
    return response


get_logs_semaphore: defaultdict[AbstractEventLoop, dank_mids.BlockSemaphore] = defaultdict(
    lambda: dank_mids.BlockSemaphore(
        int(ENVS.GETLOGS_DOP),
        # We need to do this in case users use the sync api in a multithread context
        name="y.get_logs" + ("" if current_thread() == main_thread() else f".{current_thread()}"),
    )
)


async def _get_logs_async(
    address: Address | None, topics: list[str] | None, start: Block, end: Block
) -> list[LogReceipt]:
    """
    Get logs for a given address, topics, and block range.

    The result of this function is cached.

    Args:
        address: The address of the contract to fetch logs from.
        topics: The event topics to filter logs by.
        start: The starting block to fetch logs from.
        end: The ending block to fetch logs to.

    Returns:
        A list of raw logs.

    Examples:
        >>> logs = await _get_logs_async("0x1234...", ["0x5678..."], 1000000, 1000100)
        >>> print(logs)
    """
    async with get_logs_semaphore[get_event_loop()][end]:
        return await _get_logs(address, topics, start, end, asynchronous=True)


@eth_retry.auto_retry
async def _get_logs_async_no_cache(
    address: AnyAddressType | Iterable[AnyAddressType] | None,
    topics: Sequence[str | Sequence[str] | None] | None,
    start: Block,
    end: Block,
) -> list[Log]:
    """
    Get logs for a given address, topics, and block range.

    The result of this function is not cached.

    Args:
        address: The address of the contract to fetch logs from.
        topics: The event topics to filter logs by.
        start: The starting block to fetch logs from.
        end: The ending block to fetch logs to.

    Returns:
        A list of raw logs.

    Examples:
        >>> logs = await _get_logs_async_no_cache("0x1234...", ["0x5678..."], 1000000, 1000100)
        >>> print(logs)
    """
    args: dict[str, Any] = {"fromBlock": hex(start), "toBlock": hex(end)}
    if address is None:
        args["topics"] = topics

    elif topics is None:
        args["address"] = address

    else:
        args["address"] = address
        args["topics"] = topics

    try:
        return await dank_eth.get_logs(args)
    except Exception as e:
        errs = [
            "Service Unavailable for url:",
            "exceed maximum block range",
            "block range is too wide",
            "request timed out",
            "parse error",
            "method handler crashed",
            # TypeError
            # This is some intermittent error I need to debug in dank_mids, I think it occurs when we get rate limited
            "a bytes-like object is required, not 'NoneType'",
        ]
        if all(err not in str(e) for err in errs):
            raise
        logger.debug("your node is having trouble, breaking batch in half")
        batch_size = end - start + 1
        if batch_size <= 2:
            # breaks the logic below and usually just succeeds on retry anyway
            return await _get_logs_async_no_cache(address, topics, start, end)
        half_of_batch = batch_size // 2
        batch1_end = start + half_of_batch
        batch2_start = batch1_end + 1
        batch1 = await _get_logs_async_no_cache(address, topics, start, batch1_end)
        batch2 = await _get_logs_async_no_cache(address, topics, batch2_start, end)
        response = batch1 + batch2
    return response


@eth_retry.auto_retry
def _get_logs_no_cache(
    address: Address | None,
    topics: list[str] | None,
    start: Block,
    end: Block,
) -> list[LogReceipt]:
    """
    Get logs without using the disk cache.

    Args:
        address: The address of the contract to fetch logs from.
        topics: The event topics to filter logs by.
        start: The starting block to fetch logs from.
        end: The ending block to fetch logs to.

    Returns:
        A list of raw logs.

    Examples:
        >>> logs = _get_logs_no_cache("0x1234...", ["0x5678..."], 1000000, 1000100)
        >>> print(logs)
    """
    logger.debug("fetching logs %s to %s", start, end)
    try:
        if address is None:
            response = web3.eth.get_logs(
                cast(FilterParams, {"topics": topics, "fromBlock": start, "toBlock": end})
            )
        elif topics is None:
            response = web3.eth.get_logs(
                cast(FilterParams, {"address": address, "fromBlock": start, "toBlock": end})
            )
        else:
            response = web3.eth.get_logs(
                cast(
                    FilterParams,
                    {
                        "address": address,
                        "topics": topics,
                        "fromBlock": start,
                        "toBlock": end,
                    },
                )
            )
    except Exception as e:
        errs = (
            "Service Unavailable for url:",
            "exceed maximum block range",
            "block range is too wide",
            "request timed out",
            "parse error",
            "method handler crashed",
            "Log response size exceeded.",
        )
        if any(map(str(e).__contains__, errs)):
            logger.debug("your node is having trouble, breaking batch in half")
            batch_size = end - start + 1
            half_of_batch = batch_size // 2
            batch1_end = start + half_of_batch
            batch2_start = batch1_end + 1
            batch1 = _get_logs_no_cache(address, topics, start, batch1_end)
            batch2 = _get_logs_no_cache(address, topics, batch2_start, end)
            response = batch1 + batch2
        else:
            raise
    return response


##############################
# Leaving this here so as to not upset people's caches
##############################


@memory.cache()
def _get_logs_batch_cached(
    address: Address | None, topics: list[str] | None, start: Block, end: Block
) -> list[LogReceipt]:
    """
    Get logs from the disk cache, or fetch and cache them if not available.

    Args:
        address: The address of the contract to fetch logs from.
        topics: The event topics to filter logs by.
        start: The starting block to fetch logs from.
        end: The ending block to fetch logs to.

    Returns:
        A list of raw logs.

    Examples:
        >>> logs = _get_logs_batch_cached("0x1234...", ["0x5678..."], 1000000, 1000100)
        >>> print(logs)
    """
    return _get_logs_no_cache(address, topics, start, end)


class LogFilter(Filter[_StoredLog, "LogCache", Log]):
    """
    A filter for fetching and processing event logs.

    This class provides methods to fetch logs from the blockchain and process them.
    """

    __slots__ = "addresses", "topics", "from_block"

    def __init__(
        self,
        *,
        addresses: AnyAddressType | Iterable[AnyAddressType] | None = [],
        topics: Sequence[str | Sequence[str] | None] = [],
        from_block: Block | None = None,
        chunk_size: int = BATCH_SIZE,
        chunks_per_batch: int | None = None,
        semaphore: dank_mids.BlockSemaphore | None = None,
        executor: _AsyncExecutorMixin | None = None,
        is_reusable: bool = True,
        verbose: bool = False,
    ) -> None:  # sourcery skip: default-mutable-arg
        """
        Initialize a LogFilter instance.

        Args:
            addresses: List of contract addresses to fetch logs from.
            topics: List of event topics to filter logs by.
            from_block: The starting block to fetch logs from.
            chunk_size: The number of blocks to fetch in each chunk.
            chunks_per_batch: The number of chunks to fetch in each batch.
            semaphore: A semaphore for limiting concurrent requests.
            executor: An executor for running tasks asynchronously.
            is_reusable: Whether the filter is reusable.
            verbose: Verbosity level for logging.

        Examples:
            >>> log_filter = LogFilter(addresses=["0x1234..."], topics=["0x5678..."])
            >>> logs = log_filter.logs(1000100)
            >>> print(logs)
        """
        self.addresses = _clean_addresses(addresses)
        self.topics = topics
        super().__init__(
            from_block,
            chunk_size=chunk_size,
            chunks_per_batch=chunks_per_batch,
            semaphore=semaphore,
            executor=executor,
            is_reusable=is_reusable,
            verbose=verbose,
        )

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} addresses={self.addresses} topics={self.topics}>"

    @property
    def cache(self) -> "LogCache":
        cache = self._cache
        if cache is None:
            from y._db.utils.logs import LogCache

            cache = LogCache(self.addresses, self.topics)
            self._cache = cache
        return cache

    @property
    def semaphore(self) -> dank_mids.BlockSemaphore:
        semaphore = self._semaphore
        if semaphore is None:
            semaphore = get_logs_semaphore[get_event_loop()]
            self._semaphore = semaphore
        return semaphore

    def logs(self, to_block: Block | None) -> a_sync.ASyncIterator[_StoredLog]:
        """
        Get logs up to a given block.

        Args:
            to_block: The ending block to fetch logs to.

        Yields:
            A raw log.

        Examples:
            >>> log_filter = LogFilter(addresses=["0x1234..."], topics=["0x5678..."])
            >>> logs = log_filter.logs(1000100)
            >>> print(logs)
        """
        return self._objects_thru(block=to_block)

    @property
    def insert_to_db(self) -> Callable[[Log], None]:
        """
        Get the function for inserting logs into the database.

        Raises:
            NotImplementedError: If this method is not implemented in the subclass.
        """
        # TODO: refactor this out of the base class abc
        raise NotImplementedError

    @cached_property
    def bulk_insert(self) -> Callable[[list[Log]], Awaitable[None]]:
        """
        Get the function for bulk inserting logs into the database.

        Returns:
            A function for bulk inserting logs.

        Examples:
            >>> log_filter = LogFilter(addresses=["0x1234..."], topics=["0x5678..."])
            >>> await log_filter.bulk_insert(logs)
        """
        from y._db.utils.logs import bulk_insert

        executor = self.executor

        @wraps(bulk_insert)
        async def bulk_insert_wrapped(logs: list[Log]) -> None:
            return await bulk_insert(logs, executor=executor)

        return bulk_insert_wrapped

    @async_property
    async def _from_block(self) -> Block:
        """
        Get the starting block for fetching logs.

        Returns:
            The starting block.

        Examples:
            >>> log_filter = LogFilter(addresses=["0x1234..."], topics=["0x5678..."])
            >>> start_block = await log_filter._from_block
            >>> print(start_block)
        """
        if self.from_block is None:
            from y.contracts import contract_creation_block_async

            if self.addresses is None:
                self.from_block = 0
            elif isinstance(self.addresses, Iterable) and not isinstance(self.addresses, str):
                self.from_block = await _lowest_deploy_block(
                    self.addresses, when_no_history_return_0=True
                )
            else:
                self.from_block = await contract_creation_block_async(
                    self.addresses, when_no_history_return_0=True
                )
        return self.from_block

    async def _fetch_range(self, range_start: Block, range_end: Block) -> list[Log]:
        """
        Fetch logs for a given block range.

        Args:
            range_start: The starting block of the range.
            range_end: The ending block of the range.

        Returns:
            A list of raw logs.

        Examples:
            >>> log_filter = LogFilter(addresses=["0x1234..."], topics=["0x5678..."])
            >>> logs = await log_filter._fetch_range(1000000, 1000100)
            >>> print(logs)
        """
        if range_end - range_start + 1 > 10_000:
            from y.utils._log_ranges import adaptive_logs

            return await adaptive_logs(self.addresses, self.topics, range_start, range_end)
        tries = 0
        while True:
            try:
                return await _get_logs_async_no_cache(
                    self.addresses, self.topics, range_start, range_end
                )
            except ValueError as e:
                if "parse error" not in str(e) or tries >= 50:
                    raise
                tries += 1

    async def _fetch(self) -> NoReturn:
        """
        Fetch logs indefinitely, starting from the specified block.

        Examples:
            >>> log_filter = LogFilter(addresses=["0x1234..."], topics=["0x5678..."])
            >>> await log_filter._fetch()
        """
        from_block = await self._from_block
        await self._loop(from_block)

    __slots__ = "addresses", "topics", "from_block"


class Events(LogFilter[_StoredEvent]):
    """
    A class for fetching and processing events.

    This class extends :class:`LogFilter` to provide additional functionality for handling events.
    """

    obj_type = _EventItem

    def events(
        self, to_block: Block | None, from_block: Block | None = None
    ) -> a_sync.ASyncIterator[_StoredEvent]:
        """
        Get events up to a given block.

        Args:
            to_block: The ending block to fetch events to.

        Yields:
            A decoded event.

        Examples:
            >>> events = Events(addresses=["0x1234..."], topics=["0x5678..."])
            >>> async for event in events.events(1000100):
            ...     print(event)
        """
        return self._objects_thru(block=to_block, from_block=from_block)

    async def _extend(self, logs: list[Log]) -> None:
        """
        Extend the list of events with decoded logs.

        Args:
            objs: A list of raw event logs.

        Examples:
            >>> events = Events(addresses=["0x1234..."], topics=["0x5678..."])
            >>> await events._extend(logs)
        """
        if logs:
            decoded = await _decode_threads.run(decode_logs, logs)
            # let the event loop run once since the previous and next lines are potentially blocking
            await sleep(0)
            self._objects.extend(cast(Iterable[_StoredEvent], decoded))

    def _get_block_for_obj(self, obj: _StoredEvent) -> Block:
        """
        Get the block number for a given event.

        Args:
            obj: The event.

        Returns:
            The block number.

        Examples:
            >>> events = Events(addresses=["0x1234..."], topics=["0x5678..."])
            >>> block_number = events._get_block_for_obj(event)
            >>> print(block_number)
        """
        return cast(Block, getattr(obj, "block_number"))

    __slots__: tuple[()] = ()


class ProcessedEvents(Events[T], a_sync.ASyncIterable[T]):
    """
    A class for fetching, processing, and iterating over events.

    This class extends :class:`Events` to provide additional functionality for processing events.
    """

    def _include_event(self, event: _EventItem[Any]) -> bool | Awaitable[bool]:
        """
        Determine whether to include a given event in this container.

        Override this to exclude specific events from processing and collection.

        Args:
            event: The event.

        Returns:
            True if the event should be included, False otherwise.

        Examples:
            >>> processed_events = ProcessedEvents(addresses=["0x1234..."], topics=["0x5678..."])
            >>> include = await processed_events._include_event(event)
            >>> print(include)
        """
        return True

    @abstractmethod
    def _process_event(self, event: _EventItem[Any]) -> T:
        """
        Process a given event and return the result.

        Args:
            event: The event.

        Returns:
            The processed event.

        Examples:
            >>> processed_events = ProcessedEvents(addresses=["0x1234..."], topics=["0x5678..."])
            >>> result = processed_events._process_event(event)
            >>> print(result)
        """

    def objects(
        self, to_block: Block | None, from_block: Block | None = None
    ) -> a_sync.ASyncIterator[T]:
        """
        Get an :class:`~a_sync.ASyncIterator` that yields all events up to a given block.

        Args:
            to_block: The ending block to fetch events to.

        Returns:
            An :class:`~a_sync.ASyncIterator` that yields all included events.

        Examples:
            >>> processed_events = ProcessedEvents(addresses=["0x1234..."], topics=["0x5678..."])
            >>> async for event in processed_events.objects(1000100):
            ...     print(event)
        """
        return self._objects_thru(block=to_block, from_block=from_block)

    async def _extend(self, logs: list[Log]) -> None:
        """
        Process a new set of logs and extend the list of processed events with the results.

        Args:
            logs: A list of raw event logs.

        Examples:
            >>> processed_events = ProcessedEvents(addresses=["0x1234..."], topics=["0x5678..."])
            >>> await processed_events._extend(logs)
        """
        if logs:
            decoded = await _decode_threads.run(decode_logs, logs)

            # let the event loop run once since the previous and next blocks are potentially blocking
            await sleep(0)

            should_include = list(map(self._include_event, decoded))
            awaitables = {
                i: obj
                for i, obj in enumerate(should_include)
                # filter for bool since its more lightweight than isawaitable
                if obj is not True and obj is not False and isawaitable(obj)
            }
            if awaitables:
                async for i, should in a_sync.as_completed(awaitables, aiter=True):
                    should_include[i] = should

            # let the event loop run once since the previous and next blocks are potentially blocking
            await sleep(0)

            append_processed_event = self._objects.append
            done = 0
            for event, include in zip(decoded, map(bool, should_include)):
                if include:
                    append_processed_event(self._process_event(event))
                done += 1
                if done % 10_000 == 0:
                    # Let the event loop run once in case we've been blocking for too long
                    await sleep(0)

    __slots__: tuple[()] = ()


async def _lowest_deploy_block(
    addresses: Iterable[AnyAddressType], when_no_history_return_0: bool
) -> Block:
    """
    Get the lowest deployment block for a list of addresses.

    Args:
        addresses: A list of contract addresses.
        when_no_history_return_0: Whether to return 0 if insufficient historical data is available to calculate.

    Returns:
        The lowest deployment block.

    Examples:
        >>> addresses = ["0x1234...", "0x5678..."]
        >>> block = await _lowest_deploy_block(addresses, True)
        >>> print(block)
    """
    from y.contracts import contract_creation_block_async

    return cast(
        Block,
        await contract_creation_block_async.map(
            addresses,
            when_no_history_return_0=when_no_history_return_0,
        ).min(sync=False),
    )
