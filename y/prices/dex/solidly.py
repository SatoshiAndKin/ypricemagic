from abc import abstractmethod
from itertools import product

import dank_mids

from y._decorators import continue_on_revert, stuck_coro_debugger
from y.datatypes import Address, Block, Pool
from y.exceptions import call_reverted
from y.prices._candidates import gather_owned, pool_address
from y.prices.dex.uniswap.v2 import Path, UniswapRouterV2, UniswapV2Pool
from y.utils.cache import a_sync_ttl_cache


class SolidlyRouterBase(UniswapRouterV2):
    """
    Solidly is a modified fork of Uni V2.
    The `uniswap_multiplexer` is the entrypoint for pricing using this object.

    This class provides methods to interact with the Solidly protocol, which is
    based on the Uniswap V2 model. It includes functionality to get price quotes
    and determine routes for token swaps.

    See Also:
        - :class:`~y.prices.dex.uniswap.v2.UniswapRouterV2`
        - :class:`~y.prices.dex.uniswap.v2.UniswapV2Pool`
    """

    @continue_on_revert
    @stuck_coro_debugger
    async def get_quote(
        self, amount_in: int, path: Path, block: Block | None = None, pools: tuple[Pool, ...] = ()
    ) -> tuple[int, ...] | None:
        """
        Get a price quote for a given input amount and swap path.

        This method calculates the output amount for a given input amount and
        swap path by interacting with the Solidly contract.

        Args:
            amount_in: The amount of input tokens.
            path: The swap path as a list of token addresses.
            block: The block number to query. Defaults to the latest block.

        Returns:
            A tuple containing the output amount and the path used.

        Raises:
            Exception: If the call reverts for reasons other than insufficient
            input amount or liquidity.

        Examples:
            >>> router = SolidlyRouterBase("0xRouterAddress")
            >>> quote = await router.get_quote(1000, ["0xTokenA", "0xTokenB"])
            >>> print(quote)
        """
        if block is None:
            block = await dank_mids.eth.block_number
        variants = await self.get_routes_from_path(path, block, pools=pools, sync=False)

        async def quote(routes):
            try:
                return await self.contract.getAmountsOut.coroutine(
                    amount_in, routes, block_identifier=block
                )
            except Exception as exc:
                strings = (
                    "INSUFFICIENT_INPUT_AMOUNT",
                    "INSUFFICIENT_LIQUIDITY",
                    "INSUFFICIENT_OUT_LIQUIDITY",
                    "Sequence has incorrect length",
                    "Call reverted: Integer overflow",
                )
                if not call_reverted(exc) and not any(text in str(exc) for text in strings):
                    raise
                return None

        quotes = await gather_owned(quote(routes) for routes in variants)
        return max(
            (quote for quote in quotes if quote and quote[-1] > 0),
            key=lambda quote: quote[-1],
            default=None,
        )

    def _encode_route(self, start, end, stable):
        return (start, end, stable)

    @abstractmethod
    async def get_pool(
        self, input_token: Address, output_token: Address, stable: bool, block: Block
    ) -> UniswapV2Pool | None:
        """Resolve the router's stable or volatile pool at the requested block."""
        raise NotImplementedError

    @stuck_coro_debugger
    async def get_routes_from_path(self, path: Path, block: Block, pools: tuple[Pool, ...] = ()):
        """Return every eligible stable/volatile route for this path at this block."""
        choices = []
        for index, (start, end) in enumerate(zip(path, path[1:])):
            found = await gather_owned(
                self.get_pool(start, end, stable, block, sync=False) for stable in (False, True)
            )
            routes = []
            for stable, pool in zip((False, True), found):
                if pool is None or (pools and pool_address(pool) != pool_address(pools[index])):
                    continue
                routes.append(self._encode_route(start, end, stable))
            choices.append(routes)
        return [list(routes) for routes in product(*choices)]


class SolidlyPool(UniswapV2Pool):
    """
    Represents a liquidity pool in the Solidly protocol.

    This class inherits from :class:`~y.prices.dex.uniswap.v2.UniswapV2Pool` and
    provides the same interface for interacting with liquidity pools.

    See Also:
        - :class:`~y.prices.dex.uniswap.v2.UniswapV2Pool`
    """


class SolidlyRouter(SolidlyRouterBase):
    """
    A router for interacting with the Solidly protocol.

    This class extends :class:`~SolidlyRouterBase` to provide additional
    functionality specific to the Solidly protocol, such as determining the
    appropriate pool for a token pair and calculating swap routes.

    See Also:
        - :class:`~SolidlyRouterBase`
    """

    @stuck_coro_debugger
    @a_sync_ttl_cache
    async def pair_for(self, input_token: Address, output_token: Address, stable: bool) -> Address:
        """
        Get the address of the pool for a given token pair.

        This method returns the address of the pool that contains the specified
        input and output tokens, and indicates whether the pool is stable.

        Args:
            input_token: The address of the input token.
            output_token: The address of the output token.
            stable: A boolean indicating whether to look for a stable pool.

        Returns:
            The address of the pool.

        Examples:
            >>> router = SolidlyRouter("0xRouterAddress")
            >>> pool_address = await router.pair_for("0xTokenA", "0xTokenB", True)
            >>> print(pool_address)
        """
        return await self.contract.pairFor.coroutine(input_token, output_token, stable)

    @stuck_coro_debugger
    @a_sync_ttl_cache
    async def get_pool(
        self, input_token: Address, output_token: Address, stable: bool, block: Block
    ) -> SolidlyPool | None:
        """
        Get the pool object for a given token pair.

        This method returns a :class:`~SolidlyPool` object representing the pool
        that contains the specified input and output tokens, and indicates
        whether the pool is stable.

        Args:
            input_token: The address of the input token.
            output_token: The address of the output token.
            stable: A boolean indicating whether to look for a stable pool.
            block: The block number to query.

        Returns:
            A :class:`~SolidlyPool` object if the pool exists, otherwise None.

        Examples:
            >>> router = SolidlyRouter("0xRouterAddress")
            >>> pool = await router.get_pool("0xTokenA", "0xTokenB", True, 12345678)
            >>> print(pool)
        """
        pool_address = await self.pair_for(input_token, output_token, stable, sync=False)
        if await self.contract.isPair.coroutine(pool_address, block_identifier=block):
            return SolidlyPool(pool_address, asynchronous=self.asynchronous)
