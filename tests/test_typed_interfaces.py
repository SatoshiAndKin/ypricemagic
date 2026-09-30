"""Behavior at interfaces clarified by the strict typing checks."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.test_log_cache import event_database as event_database  # noqa: F401
from tests.test_pricing_correctness import BLOCK, CHILD, TOKEN, run_async_test
from y.utils import _erc20, raw_calls


def test_special_swap_path_preserves_configured_tuple() -> None:
    from tests.test_pricing_correctness import instance
    from y.prices.dex.uniswap.v2 import UniswapRouterV2

    usdc = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    configured = (TOKEN, CHILD, usdc)
    router = instance(UniswapRouterV2)
    router.label = "test"
    router.special_paths = {TOKEN: configured}
    result = router._smol_brain_path_selector(TOKEN, usdc, CHILD)
    assert result is configured


@run_async_test
async def test_mooniswap_preserves_decimal_price(monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal
    from types import SimpleNamespace

    from y.prices import magic
    from y.prices.dex import mooniswap

    monkeypatch.setattr(mooniswap, "gather_methods", AsyncMock(return_value=(TOKEN, CHILD)))
    balances = AsyncMock(return_value=Decimal("1.000000000000000001"))
    supply = AsyncMock(return_value=Decimal(3))
    monkeypatch.setattr(
        mooniswap,
        "ERC20",
        lambda *a, **kw: SimpleNamespace(
            balance_of_readable=balances, total_supply_readable=supply
        ),
    )
    monkeypatch.setattr(magic, "get_price", AsyncMock(return_value=1))
    result = await mooniswap.get_pool_price(TOKEN, BLOCK, skip_cache=True, sync=False)
    assert type(result) is Decimal
    assert result == Decimal("2.000000000000000002") / 3


def test_prepare_data_without_inputs() -> None:
    assert raw_calls.prepare_data("decimals()") == "0x313ce567"


@run_async_test
@pytest.mark.parametrize("multiple", [False, True])
async def test_readable_supply_accepts_decoded_integer_and_batch(
    monkeypatch: pytest.MonkeyPatch,
    multiple: bool,
) -> None:
    supply = AsyncMock(return_value=[1234567, 987654321] if multiple else 1234567)
    decimals = AsyncMock(return_value=[6, 8] if multiple else 6)
    monkeypatch.setattr(_erc20, "multicall_totalSupply" if multiple else "_totalSupply", supply)
    monkeypatch.setattr(_erc20, "multicall_decimals" if multiple else "_decimals", decimals)
    addresses: Any = [TOKEN, CHILD] if multiple else TOKEN
    result = await _erc20.totalSupplyReadable(addresses, BLOCK, sync=False)
    assert result == ([1.234567, 9.87654321] if multiple else 1.234567)
    for function in (supply, decimals):
        function.assert_awaited_once_with(
            addresses,
            block=BLOCK,
            return_None_on_failure=False,
            sync=False,
        )


@run_async_test
async def test_readable_supply_preserves_unavailable_batch_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_erc20, "multicall_totalSupply", AsyncMock(return_value=[1234567, None]))
    monkeypatch.setattr(_erc20, "multicall_decimals", AsyncMock(return_value=[6, 8]))
    assert await _erc20.totalSupplyReadable(
        [TOKEN, CHILD],
        BLOCK,
        return_None_on_failure=True,
        sync=False,
    ) == [1.234567, None]


@run_async_test
@pytest.mark.parametrize("optional", [False, True])
async def test_balance_missing_result_obeys_failure_option(
    monkeypatch: pytest.MonkeyPatch,
    optional: bool,
) -> None:
    from y.exceptions import NonStandardERC20

    response = AsyncMock(return_value=None)
    monkeypatch.setattr(raw_calls, "raw_call", response)
    if optional:
        assert await raw_calls.balanceOf(TOKEN, CHILD, BLOCK, True, sync=False) is None
    else:
        with pytest.raises(NonStandardERC20, match="Unable to fetch `balanceOf`"):
            await raw_calls.balanceOf(TOKEN, CHILD, BLOCK, sync=False)
    response.assert_awaited_once_with(
        TOKEN,
        "balanceOf(address)",
        block=BLOCK,
        inputs=CHILD,
        output="int",
        return_None_on_failure=True,
        sync=False,
    )


@run_async_test
async def test_balance_zero_is_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(raw_calls, "raw_call", AsyncMock(return_value=0))
    assert await raw_calls.balanceOf(TOKEN, CHILD, BLOCK, sync=False) == 0


@run_async_test
@pytest.mark.parametrize("transform", [False, True])
async def test_multicall_no_input_decodes_named_results(
    monkeypatch: pytest.MonkeyPatch,
    transform: bool,
) -> None:
    from eth_abi.abi import encode
    from multicall import Call

    from y.utils import multicall

    async def response(self: Call) -> Any:
        assert self.block_id == BLOCK
        amount = 7 if self.target.lower() == TOKEN.lower() else 11
        return Call.decode_output(encode(["uint256"], [amount]), self.signature, self.returns)

    monkeypatch.setattr(Call, "coroutine", response)
    assert await multicall.multicall_same_func_no_input(
        [TOKEN, CHILD],
        "totalSupply()(uint256)",
        block=BLOCK,
        apply_func=(lambda value: value * 3) if transform else None,
        sync=False,
    ) == ([21, 33] if transform else [7, 11])


@run_async_test
async def test_saddle_resolves_pool_before_loading_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    from y.prices.stable_swap import saddle

    pool = AsyncMock(return_value=CHILD)
    tokens = AsyncMock(return_value=[TOKEN, None, CHILD])
    monkeypatch.setattr(saddle, "get_pool", pool)
    monkeypatch.setattr(saddle, "multicall_same_func_same_contract_different_inputs", tokens)
    result = await saddle.get_tokens(TOKEN, BLOCK, sync=False)
    assert [str(token) for token in result] == [TOKEN, CHILD]
    pool.assert_awaited_once_with(TOKEN, sync=False)
    tokens.assert_awaited_once_with(
        CHILD,
        "getToken(uint8)(address)",
        inputs=tuple(range(8)),
        block=BLOCK,
        return_None_on_failure=True,
        sync=False,
    )


@run_async_test
async def test_saddle_missing_pool_does_not_request_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    from y.prices.stable_swap import saddle

    monkeypatch.setattr(saddle, "get_pool", AsyncMock(return_value=None))
    tokens = AsyncMock()
    monkeypatch.setattr(saddle, "multicall_same_func_same_contract_different_inputs", tokens)
    with pytest.raises(ValueError, match="No Saddle pool"):
        await saddle.get_tokens(TOKEN, BLOCK, sync=False)
    tokens.assert_not_called()


@run_async_test
async def test_aave_missing_market_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_pricing_correctness import instance
    from y.prices.lending.aave import AaveRegistry

    registry = instance(AaveRegistry)
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(AaveRegistry, "pool_for_atoken", lookup)
    with pytest.raises(ValueError, match="No Aave market"):
        await registry.underlying(TOKEN, sync=False)
    lookup.assert_awaited_once_with(TOKEN, sync=False)


@run_async_test
async def test_synthetix_missing_resolver_entry_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_pricing_correctness import instance
    from y.prices.synthetix import Synthetix

    oracle = instance(Synthetix)
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(Synthetix, "get_address", lookup)
    with pytest.raises(ValueError, match="ProxyERC20 is not registered"):
        await oracle.__synths__
    lookup.assert_awaited_once_with("ProxyERC20", sync=False)


@run_async_test
@pytest.mark.parametrize("balances", [[100, None], [None, 100]])
async def test_curve_partial_balances_are_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    balances: list[int | None],
) -> None:
    from types import SimpleNamespace

    from tests.test_pricing_correctness import Ready
    from y.prices.stable_swap.curve import CurvePool

    pool = CurvePool(TOKEN, asynchronous=True)
    lookup = AsyncMock(return_value=balances)
    factory = SimpleNamespace(get_balances=SimpleNamespace(coroutine=lookup))
    monkeypatch.setattr(CurvePool, "__coins__", Ready([TOKEN, CHILD]))
    monkeypatch.setattr(CurvePool, "__factory__", Ready(factory))
    with pytest.raises(ValueError, match="could not fetch balances"):
        await pool.get_balances(BLOCK, sync=False)
    lookup.assert_awaited_once_with(TOKEN, block_identifier=BLOCK)


def test_token_insert_propagates_unrelated_integrity_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from unittest.mock import Mock

    from pony.orm import TransactionIntegrityError

    from y._db.utils import token

    error = TransactionIntegrityError("unrelated constraint")
    monkeypatch.setattr(token, "Address", SimpleNamespace(get=Mock(return_value=None)))
    insert = Mock(side_effect=error)
    monkeypatch.setattr(token, "insert", insert)
    with pytest.raises(TransactionIntegrityError) as raised:
        token.get_token(TOKEN, sync=True)
    assert raised.value is error
    insert.assert_called_once()


@pytest.mark.parametrize("network", [None, "mainnet"])
def test_curve_debug_command_uses_optional_network(
    monkeypatch: pytest.MonkeyPatch,
    network: str | None,
) -> None:
    import subprocess
    import sys
    from unittest.mock import Mock

    from y import cli

    monkeypatch.setattr(
        sys, "argv", ["y", "debug", "curve", "--token", TOKEN, "--block", str(BLOCK)]
    )
    if network is None:
        monkeypatch.delenv("BROWNIE_NETWORK_ID", raising=False)
    else:
        monkeypatch.setenv("BROWNIE_NETWORK_ID", network)
    run = Mock()
    monkeypatch.setattr(subprocess, "run", run)
    cli.main()
    command = ["brownie", "run", "debug-curve"]
    if network is not None:
        command.extend(["--network", network])
    assert run.call_args is not None
    assert run.call_args.args == (command,)
    assert run.call_args.kwargs["env"]["BAD"] == TOKEN
    assert run.call_args.kwargs["env"]["BLOCK"] == str(BLOCK)


from types import ModuleType


@pytest.mark.parametrize("selector", ["address", "symbol", "block"])
def test_db_clear_uses_requested_selector(
    event_database: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    selector: str,
) -> None:
    from pony.orm import db_session, select

    from y import cli
    from y._db import entities
    from y.constants import CHAINID

    isolated = event_database
    monkeypatch.setattr(entities, "Token", isolated.Token)
    monkeypatch.setattr(entities, "Price", isolated.Price)
    with db_session:
        chain = isolated.Chain(id=CHAINID)
        token = isolated.Token(chain=chain, address=TOKEN, symbol="TOK")
        other = isolated.Token(chain=chain, address=CHILD, symbol="OTHER")
        block = isolated.Block(chain=chain, number=BLOCK)
        later = isolated.Block(chain=chain, number=BLOCK + 1)
        isolated.Price(token=token, block=block, price=2)
        isolated.Price(token=token, block=later, price=3)
        isolated.Price(token=other, block=later, price=4)
        isolated.Price(token=other, block=block, price=5)
    if selector == "block":
        cli.db_clear(block=str(BLOCK))
    else:
        cli.db_clear(token=TOKEN if selector == "address" else "tok")
    with db_session:
        remaining = sorted(
            select((p.token.address, p.block.number, p.price) for p in isolated.Price)
        )
    expected = [(CHILD, BLOCK + 1, 4)]
    if selector == "block":
        expected.append((TOKEN, BLOCK + 1, 3))
    else:
        expected.append((CHILD, BLOCK, 5))
    assert remaining == sorted(expected)


@run_async_test
async def test_ellipsis_keeps_reserves_in_native_units(monkeypatch: pytest.MonkeyPatch) -> None:
    from decimal import Decimal
    from types import SimpleNamespace

    from y.prices.stable_swap import ellipsis

    coins = AsyncMock(side_effect=[CHILD, ValueError("end of coins")])
    balances = AsyncMock(side_effect=[1234567, ValueError("end of coins")])
    contract = SimpleNamespace(
        coins=SimpleNamespace(coroutine=coins),
        balances=SimpleNamespace(coroutine=balances),
    )
    monkeypatch.setattr(ellipsis, "raw_call", AsyncMock(return_value=TOKEN))
    monkeypatch.setattr(
        ellipsis, "Contract", SimpleNamespace(coroutine=AsyncMock(return_value=contract))
    )
    observed = []

    class Balance:
        def __init__(self, amount: int, token: str, block: int, *, skip_cache: bool) -> None:
            observed.append((amount, token, block, skip_cache))

        @staticmethod
        async def total(items: Any, *, sync: bool) -> Decimal:
            assert len(items) == 1
            return Decimal(6)

        value_usd = SimpleNamespace(sum=total)

    supply = AsyncMock(return_value=3)
    monkeypatch.setattr(ellipsis, "WeiBalance", Balance)

    def token(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(total_supply_readable=supply)

    setattr(token, "_get_scale_for", AsyncMock(return_value=10**6))
    monkeypatch.setattr(ellipsis, "ERC20", token)
    result = await ellipsis.get_price(TOKEN, BLOCK, skip_cache=True, sync=False)
    assert float(result) == 2
    assert observed == [(1234567, CHILD, BLOCK, True)]
    supply.assert_awaited_once_with(BLOCK, sync=False)
