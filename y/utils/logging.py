from asyncio import Task, sleep
from logging import DEBUG, Logger, StreamHandler, _lock, getLogger
from typing import Final, TypeVar, final
from weakref import ref as weak_ref

import a_sync
from brownie import chain
from lazy_logging import LazyLoggerFactory  # type: ignore [import-untyped]
from typing_extensions import ParamSpec

from y.datatypes import AnyAddressType, Block
from y.networks import Network

T = TypeVar("T")
P = ParamSpec("P")


NETWORK_NAME: Final = Network.name()
yLazyLogger: Final = LazyLoggerFactory("YPRICEMAGIC")


logger: Final = getLogger(__name__)


def enable_debug_logging(logger: str = "y") -> None:
    """
    Enables ypricemagic's debugging mode. Very verbose.

    Args:
        logger: The name of the logger to enable debugging for. Defaults to "y".

    Example:
        >>> enable_debug_logging("y")
    """
    logger = getLogger(logger)
    logger.setLevel(DEBUG)
    if not logger.handlers:
        logger.addHandler(StreamHandler())


@final
class PriceLogger(Logger):
    """One request owns its logger and diagnostic task."""

    def __init__(self, name: str, address: str, block: Block | None) -> None:
        super().__init__(name)
        # Register only the stable category. Per-token and per-block logger
        # names would leave permanent placeholders in logging's registry.
        self.parent = getLogger("y.prices")
        parent_name = name
        with _lock:
            while parent_name:
                parent = self.manager.loggerDict.get(parent_name)
                if isinstance(parent, Logger):
                    self.parent = parent
                    break
                parent_name = parent_name.rpartition(".")[0]
        self.address = address
        self.block = block
        self.enabled = self.isEnabledFor(DEBUG)
        self.debug_task: Task[None] | None = None

    def isEnabledFor(self, level: int) -> bool:
        # Unregistered loggers do not participate in Manager._clear_cache().
        # Read the current level so changes to parent logging still take effect.
        return (
            not self.disabled and self.manager.disable < level and level >= self.getEffectiveLevel()
        )

    def close(self) -> None:
        task, self.debug_task = self.debug_task, None
        if task is not None:
            task.cancel()


def get_price_logger(
    token_address: AnyAddressType,
    block: Block | None,
    *,
    symbol: str | None = None,
    extra: str = "",
    start_task: bool = False,
) -> PriceLogger:
    """
    Create a request-owned `PriceLogger` for a token address and block.

    Concurrent requests have independent diagnostic tasks. Call ``close()`` in
    the request's ``finally`` block. DEBUG logging must be enabled to start a task.

    Args:
        token_address: The address of the token.
        block: The block number.
        symbol: An optional symbol for the token.
        extra: An optional extra string to append to the logger name.
        start_task: Whether to start a debug task. Defaults to False.

    Example:
        >>> logger = get_price_logger("0xTokenAddress", 123456)
        >>> logger.debug("This is a debug message.")

    See Also:
        - :func:`enable_debug_logging`
    """
    address = str(token_address)
    name = f"y.prices.{Network.label()}.{address}.{block}"
    if extra:
        name += f".{extra}"

    logger = PriceLogger(name, address, block)
    if logger.enabled and start_task:
        logger.debug_task = a_sync.create_task(
            coro=_debug_tsk(symbol, weak_ref(logger)),
            name=f"_debug_tsk({symbol}, {logger})",
            log_destroy_pending=False,
        )
    return logger


async def _debug_tsk(symbol: str | None, logger_ref: "weak_ref[Logger]") -> None:
    """Prints a log every 1 minute until the creating coro returns."""
    args: tuple[str, ...]
    if symbol:
        args = "price still fetching for %s", symbol
    else:
        args = ("still fetching...",)
    while True:
        await sleep(60)
        logger = logger_ref()
        if logger is None:
            return
        logger.debug(*args)
        # Do not hold the owner across the next sleep.
        del logger


NETWORK_DESCRIPTOR_FOR_ISSUE_REQ: Final = (
    f"name ({NETWORK_NAME})" if NETWORK_NAME else f"chainid ({chain.id})"
)


def _gh_issue_request(issue_request_details: str | list[str], _logger=None) -> None:
    """
    Log a request for a GitHub issue or pull request.

    Args:
        issue_request_details: The details of the issue request.
        _logger: An optional logger to use. Defaults to the module logger.

    Example:
        >>> _gh_issue_request("This is an issue request.")
    """
    _logger = _logger or logger

    if type(issue_request_details) == str:
        _logger.warning(issue_request_details)

    elif type(issue_request_details) == list:
        for message in issue_request_details:
            _logger.warning(message)

    _logger.warning(
        "Please create an issue and/or create a PR at https://github.com/BobTheBuidler/ypricemagic"
    )
    _logger.warning(
        f"In your issue, please include the network {NETWORK_DESCRIPTOR_FOR_ISSUE_REQ} and the detail shown above."
    )
    _logger.warning(
        "and I will add it soon :). This will not prevent ypricemagic from fetching price for this asset."
    )
