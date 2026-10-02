"""Controlled native RPC responses for quote and historical-state tests."""

from types import SimpleNamespace
from typing import Any

from hexbytes import HexBytes

from y.prices._rpc import BlockRef


def native_rpc(call: Any) -> SimpleNamespace:
    """Expose a logical call stub through the provider's JSON RPC interface."""

    async def request(method: str, params: list[Any]) -> dict[str, str]:
        assert method == "eth_call"
        transaction = {**params[0], "data": HexBytes(params[0]["data"])}
        result = await call(transaction, block_identifier=params[1])
        return {"result": HexBytes(result).hex()}

    return SimpleNamespace(
        eth=SimpleNamespace(w3=SimpleNamespace(provider=SimpleNamespace(make_request=request)))
    )


def quote_read(quote: Any) -> Any:
    """Keep exact-path assertions independent of the contract ABI loader."""

    async def read(target: str, signature: str, block: BlockRef, *args: Any) -> Any:
        if signature == "quoteExactInput(bytes,uint256)(uint256)":
            return await quote(*args, block_identifier=block.identifier)
        if signature == "quoteExactOutput(bytes,uint256)(uint256)":
            return 10**30
        assert signature == "decimals()(uint8)"
        return 6

    return read
