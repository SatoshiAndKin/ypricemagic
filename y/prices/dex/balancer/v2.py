from asyncio import Task, create_task
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from decimal import Decimal
from enum import IntEnum
from logging import DEBUG, getLogger
from typing import Any, NewType, TypeVar, cast

import a_sync
from a_sync.a_sync import HiddenMethodDescriptor
from brownie import ZERO_ADDRESS
from brownie.convert.datatypes import EthAddress
from brownie.network.event import _EventItem
from eth_abi.exceptions import InvalidPointer
from hexbytes import HexBytes
from multicall import Call
from typing_extensions import Self
from web3.exceptions import ContractLogicError

from y import ENVIRONMENT_VARIABLES as ENVS
from y import contracts
from y._decorators import stuck_coro_debugger
from y.classes.common import ERC20, ContractBase, WeiBalance
from y.constants import CHAINID, CONNECTED_TO_MAINNET
from y.contracts import Contract
from y.datatypes import Address, AnyAddressType, Block, Pool, PriceResult, UsdValue
from y.exceptions import ContractNotVerified, TokenNotFound
from y.networks import Network
from y.prices._candidates import (
    derive_price,
    gather_owned,
    valid_price,
)
from y.prices._quote import bounded_map
from y.prices.dex.balancer._abc import BalancerABC, BalancerPool
from y.utils.cache import a_sync_ttl_cache
from y.utils.events import ProcessedEvents
from y.utils.logging import get_price_logger

BALANCER_V2_VAULTS = {
    Network.Mainnet: [
        "0xBA12222222228d8Ba445958a75a0704d566BF2C8",
    ],
    Network.Fantom: [
        "0x20dd72Ed959b6147912C2e529F0a0C651c33c9ce",
    ],
    Network.Polygon: [
        "0xBA12222222228d8Ba445958a75a0704d566BF2C8",
    ],
    Network.Arbitrum: [
        "0xBA12222222228d8Ba445958a75a0704d566BF2C8",
    ],
    Network.Base: [
        "0xBA12222222228d8Ba445958a75a0704d566BF2C8",
    ],
    Network.Berachain: [
        "0x4Be03f781C497A489E3cB0287833452cA9B9E80B",  # BEX Exchange https://docs.bex.berachain.com/developers/
    ],
}.get(CHAINID, [])

MESSED_UP_POOLS = {
    Network.Mainnet: [
        # NOTE: this was the first ever balancer "pool" and isn't actually a pool
        "0xF3799CBAe9c028c1A590F4463dFF039b8F4986BE",
    ],
}.get(CHAINID, [])

T = TypeVar("T")

PoolId = NewType("PoolId", bytes)
PoolBalances = dict[ERC20, WeiBalance]

logger = getLogger(__name__)


class PoolSpecialization(IntEnum):
    ComposableStablePool = 0
    WeightedPool = 1
    WeightedPool2Tokens = 2
    # This is a weird one
    CronV1Pool = -1

    @staticmethod
    def with_immutable_tokens() -> list["PoolSpecialization"]:
        """
        Get a list of pool specializations with immutable tokens.

        Returns:
            A list of :class:`~PoolSpecialization` enums representing pools with immutable tokens.

        Examples:
            >>> PoolSpecialization.with_immutable_tokens()
            [<PoolSpecialization.ComposableStablePool: 0>, <PoolSpecialization.WeightedPool: 1>, <PoolSpecialization.WeightedPool2Tokens: 2>, <PoolSpecialization.CronV1Pool: -1>]
        """
        return [
            PoolSpecialization.ComposableStablePool,
            PoolSpecialization.WeightedPool,
            PoolSpecialization.WeightedPool2Tokens,
            PoolSpecialization.CronV1Pool,
        ]


class BalancerV2Vault(ContractBase):
    def __init__(self, address: AnyAddressType, *, asynchronous: bool = False) -> None:
        """
        Initialize a BalancerV2Vault instance.

        Args:
            address: The address of the Balancer V2 Vault.
            asynchronous: Whether to use asynchronous operations.

        Examples:
            >>> vault = BalancerV2Vault("0xBA12222222228d8Ba445958a75a0704d566BF2C8")
        """
        super().__init__(address, asynchronous=asynchronous)
        self._events = BalancerEvents(
            self,
            addresses=address,
            topics=["0x3c13bc30b8e878c53fd2a36b679409c073afd75950be43d8858768e956fbc20e"],
        )
        if not self._is_cached:
            # we need the contract cached so we can decode logs correctly
            self.contract

    @stuck_coro_debugger
    async def pools(self, block: Block | None = None) -> AsyncIterator["BalancerV2Pool"]:
        """
        Asynchronously iterate over Balancer V2 pools.

        Args:
            block: The block number to query. Defaults to the latest block.

        Yields:
            Instances of :class:`~BalancerV2Pool`.

        Examples:
            >>> async for pool in vault.pools():
            ...     print(pool)
        """
        async for pool in self._events.events(to_block=block):
            yield pool

    @stuck_coro_debugger
    async def pools_for_token(
        self, token: Address, block: Block | None = None
    ) -> AsyncIterator["BalancerV2Pool"]:
        """
        Asynchronously iterate over Balancer V2 pools containing a specific token.

        Args:
            token: The address of the token to search for.
            block: The block number to query. Defaults to the latest block.

        Yields:
            Instances of :class:`~BalancerV2Pool` containing the specified token.

        Examples:
            >>> async for pool in vault.pools_for_token("0xTokenAddress"):
            ...     print(pool)
        """
        pools = [pool async for pool in self.pools(block=block)]

        async def pool_tokens(pool: Any) -> Any:
            return await pool.tokens(block=block, sync=False)

        tokens_by_pool = await bounded_map(pool_tokens, pools)
        for pool, tokens in zip(pools, tokens_by_pool):
            if token in tokens:
                yield pool

    @a_sync_ttl_cache
    @stuck_coro_debugger
    async def get_pool_tokens(self, pool_id: HexBytes, block: Block | None = None):
        """
        Get the tokens and balances for a specific pool.

        Args:
            pool_id: The ID of the pool.
            block: The block number to query. Defaults to the latest block.

        Returns:
            A tuple containing the tokens and their balances.

        Examples:
            >>> tokens, balances = await vault.get_pool_tokens(pool_id)
        """
        contract = await contracts.Contract.coroutine(self.address)
        try:
            return await contract.getPoolTokens.coroutine(pool_id, block_identifier=block)
        except InvalidPointer:
            return (), (), None

    @a_sync_ttl_cache
    @stuck_coro_debugger
    async def get_pool_info(
        self, poolids: tuple[HexBytes, ...], block: Block | None = None
    ) -> list[tuple]:
        """
        Get information for multiple pools.

        Args:
            poolids: A tuple of pool IDs.
            block: The block number to query. Defaults to the latest block.

        Returns:
            A list of tuples containing pool information.

        Examples:
            >>> pool_info = await vault.get_pool_info((pool_id1, pool_id2))
        """
        contract = await contracts.Contract.coroutine(self.address)
        return await contract.getPoolTokens.map(poolids, block_identifier=block)

    @a_sync_ttl_cache
    @stuck_coro_debugger
    async def deepest_pool_for(
        self, token_address: Address, block: Block | None = None
    ) -> "BalancerV2Pool":
        """
        Find the deepest pool for a specific token.

        Args:
            token_address: The address of the token.
            block: The block number to query. Defaults to the latest block.

        Returns:
            The :class:`~BalancerV2Pool` with the deepest liquidity for the specified token.

        Examples:
            >>> deepest_pool = await vault.deepest_pool_for("0xTokenAddress")
        """
        balance_tasks: a_sync.TaskMapping[BalancerV2Pool, WeiBalance | None]

        logger = get_price_logger(token_address, block, extra="balancer.v2")

        balance_tasks = BalancerV2Pool.get_balance.map(token_address=token_address, block=block)
        balances_aiterator = balance_tasks.map(
            self.pools_for_token(token_address, block=block), pop=True
        )
        filtered = balances_aiterator.filter(_lookup_balance_from_tuple)
        high_to_low = filtered.sort(key=_lookup_balance_from_tuple, reverse=True)

        if logger.isEnabledFor(DEBUG):
            async for pool, balance in high_to_low:
                logger._log(DEBUG, "deepest pool %s balance %s", (pool, balance))
                return pool
        else:
            async for pool, balance in high_to_low:
                return pool


class BalancerEvents(ProcessedEvents[tuple[HexBytes, EthAddress, Block]]):
    __slots__ = ("asynchronous",)

    def __init__(self, vault: BalancerV2Vault, *args, asynchronous: bool = False, **kwargs):
        """
        Initialize a BalancerEvents instance.

        Args:
            vault: The associated :class:`~BalancerV2Vault`.
            asynchronous: Whether to use asynchronous operations.

        Examples:
            >>> events = BalancerEvents(vault)
        """
        super().__init__(*args, **kwargs)
        self.vault = vault
        self.asynchronous = asynchronous
        self.__tasks: dict[Task[Any], BalancerV2Pool] = {}

    def _include_event(self, event: _EventItem) -> Awaitable[bool]:
        """
        Determine whether to include a specific event.

        Args:
            event: The event to evaluate.

        Returns:
            A boolean indicating whether to include the event.

        Examples:
            >>> include = await events._include_event(event)
        """
        if event["poolAddress"] in MESSED_UP_POOLS:
            return False
        # NOTE: For some reason the Balancer fork on Fantom lists "0x3e522051A9B1958Aa1e828AC24Afba4a551DF37d"
        #       as a pool, but it is not a contract. This handler will prevent it and future cases from causing problems.
        # NOTE: this isn't really optimized as it still runs semi-synchronously but its better than what was had previously
        return self.executor.run(contracts.is_contract, event["poolAddress"])

    def _process_event(self, event: _EventItem) -> "BalancerV2Pool":
        """
        Process a specific event and return the associated Balancer V2 pool.

        Args:
            event: The event to process.

        Returns:
            The associated :class:`~BalancerV2Pool`.

        Examples:
            >>> pool = events._process_event(event)
        """
        try:
            specialization = PoolSpecialization(event["specialization"])
        except ValueError:
            specialization = None
        pool = BalancerV2Pool(
            address=event["poolAddress"],
            id=HexBytes(event["poolId"]),
            specialization=specialization,
            vault=self.vault,
            _deploy_block=event.block_number,
            asynchronous=self.asynchronous,
        )
        # lets get this cached into memory now
        task = create_task(pool.tokens(sync=False))
        self.__tasks[task] = pool
        task.add_done_callback(self._task_done_callback)
        return pool

    def _get_block_for_obj(self, pool: "BalancerV2Pool") -> int:
        """
        Get the block number for a specific pool.

        Args:
            pool: The :class:`~BalancerV2Pool` to evaluate.

        Returns:
            The block number.

        Examples:
            >>> block_number = events._get_block_for_obj(pool)
        """
        return pool._deploy_block

    def _task_done_callback(self, t: Task):
        """
        Log any Exception that occurs in a startup task.

        Because these tasks are only used to populate caches
        and don't block anything, we don't need to propagate
        the Exception and can just remove the task so it can
        be garbage collected

        Args:
            t: The completed task.

        Examples:
            >>> events._task_done_callback(task)
        """
        pool = self.__tasks.pop(t)
        if t.cancelled():
            logger.error("balancer v2 startup task %s is cancelled??", t)
        elif exc := t.exception():
            logger.error(f"balancer v2 startup task failed: {exc!r}")
        # force shrink the dict's hash table as the tasks complete
        self.__tasks = dict(self.__tasks)


class BalancerV2Pool(BalancerPool):
    """A pool from Balancer Protocol v2"""

    # internal variables to save calls in some instances
    # they do not necessarily reflect real life at all times
    # defaults are stored as class vars to keep instance dicts smaller
    _tokens: tuple[ERC20, ...] = None
    __nonweighted: bool = False
    __weights: list[int] = None

    def __init__(
        self,
        address: AnyAddressType,
        *,
        id: HexBytes | None = None,
        specialization: PoolSpecialization | None = None,
        vault: BalancerV2Vault | None = None,
        asynchronous: bool = False,
        _deploy_block: Block | None = None,
    ):
        """
        Initialize a BalancerV2Pool instance.

        Args:
            address: The address of the pool.
            id: The ID of the pool.
            specialization: The specialization of the pool.
            vault: The associated :class:`~BalancerV2Vault`.
            asynchronous: Whether to use asynchronous operations.
            _deploy_block: The block number when the pool was deployed.

        Examples:
            >>> pool = BalancerV2Pool("0xPoolAddress")
        """
        super().__init__(address, asynchronous=asynchronous, _deploy_block=_deploy_block)
        if id is not None:
            self.id = id
        if specialization is not None:
            self.pool_type = specialization
        if vault is not None:
            self.vault = vault

    @a_sync.aka.cached_property
    async def id(self) -> PoolId:
        """
        Get the ID of the pool.

        Returns:
            The pool ID.

        Examples:
            >>> pool_id = await pool.id
        """
        return await Call(self.address, "getPoolId()(bytes32)")

    __id__: HiddenMethodDescriptor[Self, PoolId]

    @a_sync.aka.cached_property
    @stuck_coro_debugger
    async def vault(self) -> BalancerV2Vault | None:
        """
        Get the associated Balancer V2 Vault.

        Returns:
            The associated :class:`~BalancerV2Vault`, or None if not found.

        Examples:
            >>> vault = await pool.vault
        """
        with suppress(ContractLogicError):
            vault = await Call(self.address, "getVault()(address)")
            if vault == ZERO_ADDRESS:
                return None
            elif vault:
                return BalancerV2Vault(vault, asynchronous=True)
        # in earlier web3 versions, we would get `None`. More recently, we get ContractLogicError. This handles both
        if CONNECTED_TO_MAINNET and await self.__build_name__ == "CronV1Pool":
            # NOTE: these `CronV1Pool` tokens ARE balancer pools but don't match the expected pool abi?
            return BalancerV2Vault("0xBA12222222228d8Ba445958a75a0704d566BF2C8", asynchronous=True)

    __vault__: HiddenMethodDescriptor[Self, BalancerV2Vault | None]

    @a_sync.aka.cached_property
    @stuck_coro_debugger
    async def pool_type(self) -> PoolSpecialization | int:
        """
        Get the type of the pool.

        Returns:
            The pool type as a :class:`~PoolSpecialization` or an integer.

        Examples:
            >>> pool_type = await pool.pool_type
        """
        vault = await self.__vault__
        if vault is None:
            raise ValueError(f"{self} has no vault") from None
        elif poolid := await self.__id__:
            _, specialization = await vault.contract.getPool.coroutine(poolid)
        elif CONNECTED_TO_MAINNET and await self.__build_name__ == "CronV1Pool":
            # NOTE: these `CronV1Pool` tokens ARE balancer pools but don't match the expected pool abi?
            return PoolSpecialization.CronV1Pool
        else:
            raise ValueError(f"{self} has no poolid") from None
        try:
            return PoolSpecialization(specialization)
        except ValueError:
            if self.address not in _warned:
                with suppress(ContractNotVerified):
                    logger.warning(
                        "ypricemagic does not recognize this pool type, please add `%s = %s` to %s.PoolSpecialization (pool=%s)",
                        await self.__build_name__,
                        specialization,
                        __name__,
                        self.address,
                    )
                _warned.add(self.address)
            return specialization

    __pool_type__: HiddenMethodDescriptor[Self, PoolSpecialization | None]

    @stuck_coro_debugger
    async def get_tvl(
        self,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
        ignore_pools: tuple[Pool, ...] = (),
    ) -> UsdValue | None:
        """
        Get the total value locked (TVL) in the pool in USD.

        Args:
            block: The block number to query. Defaults to the latest block.
            skip_cache: Whether to skip the cache.

        Returns:
            The TVL in USD, or None if it cannot be determined.

        Examples:
            >>> tvl = await pool.get_tvl()
        """
        if balances := await self.get_balances(
            block=block, skip_cache=skip_cache, ignore_pools=(*ignore_pools, self), sync=False
        ):
            # overwrite ref to big obj with ref to little obj
            balances = iter(tuple(balances.values()))
            return UsdValue(await WeiBalance.value_usd.sum(balances, sync=False))

    @a_sync_ttl_cache
    @stuck_coro_debugger
    async def get_balances(
        self,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
        ignore_pools: tuple[Pool, ...] = (),
    ) -> PoolBalances:
        """
        Get the balances of tokens in the pool.

        Args:
            block: The block number to query. Defaults to the latest block.
            skip_cache: Whether to skip the cache.

        Returns:
            A dictionary mapping :class:`~ERC20` tokens to their :class:`~WeiBalance` in the pool.

        Examples:
            >>> balances = await pool.get_balances()
        """
        vault = await self.__vault__
        if vault is None:
            return {}
        tokens, balances, lastChangedBlock = await vault.get_pool_tokens(
            await self.__id__, block=block, sync=False
        )
        return {
            ERC20(token, asynchronous=self.asynchronous): WeiBalance(
                balance, token, block=block, skip_cache=skip_cache, ignore_pools=ignore_pools
            )
            for token, balance in zip(tokens, balances)
            # NOTE: some pools include themselves in their own token list, and we should ignore those
            if token != self.address
        }

    async def get_balance(
        self,
        token_address: Address,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
    ) -> WeiBalance | None:
        """
        Get the balance of a specific token in the pool.

        Args:
            token_address: The address of the token.
            block: The block number to query. Defaults to the latest block.
            skip_cache: Whether to skip the cache.

        Returns:
            The :class:`~WeiBalance` of the specified token in the pool, or None if not found.

        Examples:
            >>> balance = await pool.get_balance("0xTokenAddress")
        """
        if info := await self.get_balances(block=block, sync=False):
            try:
                return info[token_address]
            except KeyError:
                raise TokenNotFound(token_address, self) from None

    @stuck_coro_debugger
    async def get_token_price(
        self,
        token_address: AnyAddressType,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
        ignore_pools: tuple[Pool, ...] = (),
    ) -> PriceResult | None:
        """
        Get the price of a specific token in the pool in USD.

        Args:
            token_address: The address of the token.
            block: The block number to query. Defaults to the latest block.
            skip_cache: Whether to skip the cache.

        Returns:
            The price of the specified token in USD, or None if it cannot be determined.

        Examples:
            >>> price = await pool.get_token_price("0xTokenAddress")
        """
        get_balances_coro = self.get_balances(
            block=block, skip_cache=skip_cache, ignore_pools=(self, *ignore_pools), sync=False
        )
        if self.__nonweighted:
            # this await will return immediately once cached
            token_balances = await get_balances_coro
            weights = self.__weights
        else:
            token_balances, weights = await gather_owned(
                [get_balances_coro, self.weights(block=block, sync=False)]
            )
        pool_token_info = list(zip(token_balances.keys(), token_balances.values(), weights))
        token_info = next((item for item in pool_token_info if item[0] == token_address), None)
        if token_info is None:
            return None
        _, token_balance, token_weight = token_info
        token_balance_readable = await token_balance.__readable__
        if not token_balance_readable or token_weight <= 0:
            return None

        @stuck_coro_debugger
        async def quote(paired, balance, weight):
            if weight <= 0:
                return None
            child = await paired.price(
                block=block, skip_cache=skip_cache, ignore_pools=(*ignore_pools, self), sync=False
            )
            if valid_price(child):
                # Balancer whitepaper Eq. 2: balances normalized by weights.
                value = (await balance.__readable__) * Decimal(str(float(child)))
                value = value * Decimal(token_weight) / Decimal(weight) / token_balance_readable
                return derive_price(
                    token_address,
                    value,
                    f"Balancer V2 pool {self.address} via {paired.address}",
                    child,
                )

        for paired, balance, weight in sorted(
            pool_token_info, key=lambda item: str(item[0]).lower()
        ):
            if paired == token_address:
                continue
            result = await quote(paired, balance, weight)
            if result is not None:
                return result
        return None

    @a_sync_ttl_cache
    @stuck_coro_debugger
    async def tokens(
        self, block: Block | None = None, skip_cache: bool = ENVS.SKIP_CACHE
    ) -> tuple[ERC20, ...]:
        """
        Get the tokens in the pool.

        Args:
            block: The block number to query. Defaults to the latest block.
            skip_cache: Whether to skip the cache.

        Returns:
            A tuple of :class:`~ERC20` tokens in the pool.

        Examples:
            >>> tokens = await pool.tokens()
        """
        if self._tokens:
            return self._tokens
        tokens = tuple(
            (await self.get_balances(block=block, skip_cache=skip_cache, sync=False)).keys()
        )
        if await self.__pool_type__ in PoolSpecialization.with_immutable_tokens():
            self._tokens = tokens
        return tokens

    @a_sync_ttl_cache
    @stuck_coro_debugger
    async def weights(self, block: Block | None = None) -> list[int]:
        """
        Get the weights of tokens in the pool.

        Args:
            block: The block number to query. Defaults to the latest block.

        Returns:
            A list of weights for the tokens in the pool.

        Examples:
            >>> weights = await pool.weights()
        """
        contract = await Contract.coroutine(self.address)
        try:
            return await contract.getNormalizedWeights.coroutine(block_identifier=block)
        except AttributeError:
            # Contract has no method `getNormalizedWeights`
            self.__nonweighted = True
            num_tokens = len(await self.tokens(block=block, sync=False))
            self.__weights = [10**18 // num_tokens] * num_tokens
            return self.__weights


class BalancerV2(BalancerABC[BalancerV2Pool]):

    _pool_type = BalancerV2Pool

    _check_methods = (
        "getPoolId()(bytes32)",
        "getPausedState()((bool,uint,uint))",
        "getSwapFeePercentage()(uint)",
    )

    def __init__(self, *, asynchronous: bool = False) -> None:
        """
        Initialize a BalancerV2 instance.

        Args:
            asynchronous: Whether to use asynchronous operations.

        Examples:
            >>> balancer = BalancerV2(asynchronous=True)
        """
        super().__init__()
        self.asynchronous = asynchronous
        self.vaults = [
            BalancerV2Vault(vault, asynchronous=self.asynchronous) for vault in BALANCER_V2_VAULTS
        ]

    @stuck_coro_debugger
    async def get_token_price(
        self,
        token_address: Address,
        block: Block | None = None,
        skip_cache: bool = ENVS.SKIP_CACHE,
        ignore_pools: tuple[Pool, ...] = (),
    ) -> PriceResult | None:
        """Use native Vault quotes from liquidity-ranked Balancer V2 pools."""
        from y.prices._routing import liquidity_price

        return await liquidity_price(
            str(token_address),
            block,
            ignore_pools=ignore_pools,
            skip_cache=skip_cache,
            first_markets=("Balancer V2",),
        )

    @stuck_coro_debugger
    async def deepest_pool_for(
        self,
        token_address: Address,
        block: Block | None = None,
        ignore_pools: tuple[Pool, ...] = (),
    ) -> BalancerV2Pool | None:
        """
        Find the deepest pool for a specific token.

        Args:
            token_address: The address of the token.
            block: The block number to query. Defaults to the latest block.

        Returns:
            The :class:`~BalancerV2Pool` with the deepest liquidity for the specified token, or None if not found.

        Examples:
            >>> deepest_pool = await balancer.deepest_pool_for("0xTokenAddress")
        """
        kwargs = {"token_address": token_address, "block": block}
        deepest_pools = BalancerV2Vault.deepest_pool_for.map(self.vaults, **kwargs)
        if deepest_pools := {
            vault.address: deepest_pool
            async for vault, deepest_pool in deepest_pools
            if deepest_pool is not None and deepest_pool not in ignore_pools
        }:
            logger.debug(
                "%s deepest pools for %s at %s: %s",
                self,
                token_address,
                block,
                deepest_pools,
            )
            async for pool in (
                BalancerV2Pool.get_balance.map(deepest_pools.values(), **kwargs)
                .keys(pop=True)
                .aiterbyvalues(reverse=True)
            ):
                return cast(BalancerV2Pool, pool)

        # TODO: afilter
        # deepest_pools = BalancerV2Vault.deepest_pool_for.map(self.vaults, **kwargs).values(pop=True).afilter()
        # async for pool in BalancerV2Pool.get_balance.map(deepest_pools, **kwargs).keys(pop=True).aiterbyvalues(reverse=True):
        #     return pool


balancer = BalancerV2(asynchronous=True)

_lookup_balance_from_tuple: Callable[[tuple[Any, T]], T] = (
    lambda pool_and_balance: pool_and_balance[1]
)
"Takes a tuple[K, V] and returns V."

_warned = set()
