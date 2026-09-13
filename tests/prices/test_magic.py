# sourcery skip: dont-import-test-modules
import asyncio
from collections.abc import Iterable
from typing import Any

import a_sync
import pytest
from brownie import chain
from eth_typing import ChecksumAddress

from tests.prices.dex.test_uniswap import V1_TOKENS, V2_TOKENS
from tests.prices.lending.test_aave import ATOKENS
from tests.prices.lending.test_compound import CTOKENS
from tests.prices.test_chainlink import FEEDS
from tests.prices.test_popsicle import POPSICLES
from tests.prices.test_synthetix import SYNTHS
from tests.test_pricing_correctness import run_async_test
from y import convert
from y.contracts import contract_creation_block_async
from y.datatypes import AnyAddressType
from y.exceptions import CantFetchParam, PriceError
from y.prices import magic

START_TESTS_AT_BLOCK = 11_000_000
NUM_ITERATIONS = 10
INCREMENT = (chain.height - START_TESTS_AT_BLOCK) // NUM_ITERATIONS
BLOCKS = [START_TESTS_AT_BLOCK + INCREMENT * i for i in range(NUM_ITERATIONS)]

ALL_TOKENS: list = V1_TOKENS + V2_TOKENS + ATOKENS + CTOKENS + FEEDS + POPSICLES + SYNTHS

# subtraction underflow, not relevant to point of test
ALL_TOKENS.remove("0x892B14321a4FCba80669aE30Bd0cd99a7ECF6aC0")
# ALL_TOKENS.remove('0x892B14321a4FCba80669aE30Bd0cd99a7ECF6aC0')
# ALL_TOKENS.remove('0x892b14321a4fcba80669ae30bd0cd99a7ecf6ac0')
# ALL_TOKENS.remove('0x892B14321A4FCBA80669AE30BD0CD99A7ECF6AC0')

# ibibBTC, not relevant to point of test
# ALL_TOKENS.remove('0x2a867fd776b83e1bd4e13c6611afd2f6af07ea6d')
# ALL_TOKENS.remove('0x2A867FD776B83E1BD4E13C6611AFD2F6AF07EA6D')
# ALL_TOKENS.remove('0x2A867fd776B83e1bd4e13C6611AFd2F6af07EA6D')
# ALL_TOKENS.remove('0x2A867fd776B83e1bd4e13C6611AFd2F6af07EA6D')

# multicall aggregate failed, not relevant to point of test
# ALL_TOKENS.remove('0x4ee15f44c6f0d8d1136c83efd2e8e4ac768954c6')
# ALL_TOKENS.remove('0x4EE15F44C6F0D8D1136C83EFD2E8E4AC768954C6')
# ALL_TOKENS.remove('0x4EE15f44c6F0d8d1136c83EfD2e8E4AC768954c6')
# ALL_TOKENS.remove('0x4EE15f44c6F0d8d1136c83EfD2e8E4AC768954c6')
# ALL_TOKENS.remove('0x9baf8a5236d44ac410c0186fe39178d5aad0bb87')
# ALL_TOKENS.remove('0x9BAF8A5236D44AC410C0186FE39178D5AAD0BB87')
# ALL_TOKENS.remove('0x9baF8a5236d44AC410c0186Fe39178d5AAD0Bb87')
# ALL_TOKENS.remove('0x9baF8a5236d44AC410c0186Fe39178d5AAD0Bb87')


@pytest.mark.parametrize("block", BLOCKS)
@pytest.mark.asyncio_cooperative
async def test_get_prices(block: int) -> None:
    """
    Sometimes this will fail unnecessarily because Chainlink has added some more fiat feeds.
    Just add the failing identifier to 'chainlink_identifiers_not_tokens' below.
    """
    tokens = await relevant_tokens(ALL_TOKENS, block)
    prices = a_sync.map(get_price, tokens, block=block)
    try:
        checked_separately = await prices.values()
    finally:
        await prices.close()
    # ez-a-sync supplies the sync keyword at runtime.
    lookup: Any = magic.get_prices
    checked_together = await lookup(tokens, block, fail_to_None=True, skip_cache=True, sync=False)
    for i in range(len(checked_together)):
        assert (
            checked_together[i] == checked_separately[i]
        ), f"magic.get_prices price discrepancy for {tokens[i]}"


async def get_price(token, block):
    """This is just to diagnose issues with the test itself. We may need to exclude certain tokens."""
    try:
        return await magic.get_price(
            token, block, fail_to_None=True, skip_cache=True, asynchronous=True
        )
    except CantFetchParam as e:
        raise CantFetchParam(token, str(e))
    except PriceError:
        return None
    except TypeError as e:
        raise TypeError(token, str(e))
    except ValueError as e:
        raise ValueError(token, str(e))


chainlink_identifiers_not_tokens = [
    "0x0000000000000000000000000000000000000024",
    "0x000000000000000000000000000000000000007c",
    "0x000000000000000000000000000000000000009c",
    "0x0000000000000000000000000000000000000188",
    "0x000000000000000000000000000000000000019a",
    "0x0000000000000000000000000000000000000164",
    "0x000000000000000000000000000000000000022A",
    "0x0000000000000000000000000000000000000236",
    "0x0000000000000000000000000000000000000260",
    "0x00000000000000000000000000000000000002be",
    "0x00000000000000000000000000000000000002c6",
    "0x00000000000000000000000000000000000002F4",
    "0x000000000000000000000000000000000000033a",
    "0x00000000000000000000000000000000000003d2",
    "0x00000000000000000000000000000000000003Da",
    "0xbBbBBBBbbBBBbbbBbbBbbbbBBbBbbbbBbBbbBBbB",
    "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE",
]


async def relevant_tokens(tokens: Iterable[AnyAddressType], block: int) -> list[ChecksumAddress]:
    addresses = (
        await convert.to_address_async(token)
        for token in tokens
        if token not in chainlink_identifiers_not_tokens
    )
    deployments: a_sync.TaskMapping[ChecksumAddress, int] = a_sync.map(
        contract_creation_block_async, addresses
    )
    try:
        return [
            token
            async for token, deploy_block in deployments
            if deploy_block and deploy_block <= block
        ]
    finally:
        await deployments.close()


@run_async_test
@pytest.mark.parametrize("phase", ["prices", "deployments"])
@pytest.mark.parametrize("outcome", ["failure", "cancel"])
async def test_bulk_fixture_releases_mapped_requests(
    monkeypatch: pytest.MonkeyPatch, phase: str, outcome: str
) -> None:
    """A failed historical case must not leave work running into later cases."""
    tokens = [f"0x{index:040x}" for index in range(1, 4)]
    entered, release = asyncio.Event(), asyncio.Event()
    requests: set[asyncio.Task[Any]] = set()
    active: set[str] = set()
    failure = RuntimeError("failed mapped fixture request")

    async def request(token: str, block: int | None = None) -> int:
        task = asyncio.current_task()
        assert task is not None
        requests.add(task)
        active.add(token)
        try:
            if len(active) == len(tokens):
                entered.set()
            await release.wait()
            if outcome == "failure" and token == tokens[0]:
                raise failure
            await asyncio.Event().wait()
            raise AssertionError("Pending request resumed without cancellation")
        finally:
            active.remove(token)

    parent: asyncio.Task[Any]
    if phase == "prices":

        async def relevant(addresses: list[str], block: int) -> list[str]:
            assert addresses == tokens
            return addresses

        monkeypatch.setattr(__name__ + ".ALL_TOKENS", tokens)
        monkeypatch.setattr(__name__ + ".relevant_tokens", relevant)
        monkeypatch.setattr(__name__ + ".get_price", request)
        parent = asyncio.create_task(test_get_prices(18_000_000))
    else:

        async def normalize(address: str) -> str:
            return address

        monkeypatch.setattr(convert, "to_address_async", normalize)
        monkeypatch.setattr(__name__ + ".contract_creation_block_async", request)
        parent = asyncio.create_task(relevant_tokens(tokens, 18_000_000))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert len(requests) == len(tokens)
        if outcome == "cancel":
            parent.cancel()
            with pytest.raises(asyncio.CancelledError):
                await parent
        else:
            release.set()
            with pytest.raises(RuntimeError) as caught:
                await parent
            assert caught.value is failure
        await asyncio.sleep(0)
        assert not active
        assert all(task.done() for task in requests)
    finally:
        # Cleanup after the assertions also keeps the failing control isolated.
        parent.cancel()
        for task in requests:
            task.cancel()
        await asyncio.gather(parent, *requests, return_exceptions=True)
