"""Static factory metadata must match the existing ABI decoder exactly."""

from typing import Any, cast
from unittest.mock import Mock

import pytest
from brownie.network.event import _deployment_topics
from eth_abi.abi import decode, encode
from eth_abi.exceptions import DecodingError
from eth_event import get_topic_map
from eth_event.main import TopicMapData
from eth_typing import ABIEvent, ChecksumAddress
from evmspec import Log
from evmspec.data._main import _decode_hook
from msgspec import json
from msgspec.structs import replace

from y.utils import _pool_events as metadata
from y.utils import events
from y.utils._pool_events import decode_pool_logs

FACTORY = "0x000000000000000000000000000000000000F999"
TOKEN0 = "0x0000000000000000000000000000000000000011"
TOKEN1 = "0x0000000000000000000000000000000000000022"
POOL = "0x0000000000000000000000000000000000000033"


def event(
    monkeypatch: pytest.MonkeyPatch, fields: list[tuple[str, str, bool, Any]]
) -> tuple[Log, dict[str, Any]]:
    abi: ABIEvent = {
        "anonymous": False,
        "name": "PoolCreated",
        "type": "event",
        "inputs": [
            {"name": name, "type": kind, "indexed": indexed} for name, kind, indexed, _ in fields
        ],
    }
    topic_map = get_topic_map([abi])
    topics: list[str] = [next(iter(topic_map))]
    topics.extend("0x" + encode([kind], [value]).hex() for _, kind, idx, value in fields if idx)
    nonindexed = [(kind, value) for _, kind, idx, value in fields if not idx]
    row = json.decode(
        json.encode(
            {
                "address": FACTORY,
                "topics": topics,
                "data": "0x"
                + encode([kind for kind, _ in nonindexed], [v for _, v in nonindexed]).hex(),
                "blockNumber": "0x1234",
                "transactionHash": "0x" + "ef" * 32,
                "transactionIndex": "0x3",
                "logIndex": "0x2",
                "removed": False,
            }
        ),
        type=Log,
        dec_hook=_decode_hook,
    )
    monkeypatch.setitem(_deployment_topics, cast(ChecksumAddress, str(row.address)), topic_map)
    return row, {name: value for name, _, _, value in fields}


@pytest.mark.parametrize("protocol", ["v2", "solidly", "velodrome", "v3", "slipstream"])
def test_static_fields_match_registered_factory_abi_without_mutation(
    monkeypatch: pytest.MonkeyPatch, protocol: str
) -> None:
    fields: list[tuple[str, str, bool, Any]] = [
        ("token0", "address", True, TOKEN0),
        ("token1", "address", True, TOKEN1),
    ]
    if protocol in ("solidly", "velodrome"):
        fields.append(("stable", "bool", False, protocol == "solidly"))
    if protocol == "v3":
        fields.append(("fee", "uint24", True, 3000))
    if protocol in ("v3", "slipstream"):
        fields.append(("tickSpacing", "int24", protocol == "slipstream", -60))
    fields.append(
        ("pair" if protocol in ("v2", "solidly", "velodrome") else "pool", "address", False, POOL)
    )
    if protocol in ("v2", "solidly", "velodrome"):
        fields.append(("", "uint256", False, 9007199254740993))
    row, expected = event(monkeypatch, fields)
    topics = row.topics
    original = events.decode_logs([row])[0]
    for name, kind, _, _ in fields:
        value = original[name]
        assert (str(value).lower() if kind == "address" else value) == expected[name]
    fallback = Mock(side_effect=AssertionError("static metadata used the generic decoder"))
    monkeypatch.setattr(events, "decode_logs", fallback)
    assert list(decode_pool_logs([row, row])) == [expected, expected]
    assert row.topics == topics
    fallback.assert_not_called()


def test_static_metadata_keeps_strict_abi_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    row, _ = event(monkeypatch, [("stable", "bool", False, True)])
    from evmspec.structs.log import Data

    with pytest.raises(DecodingError):
        decode_pool_logs([replace(row, data=Data(encode(["uint256"], [2])))])
    with pytest.raises(DecodingError):
        decode_pool_logs([replace(row, data=Data(b"\x00"))])
    with pytest.raises(ValueError, match="indexed field count"):
        decode_pool_logs([replace(row, topics=(*row.topics, row.topics[0]))])


@pytest.mark.parametrize("registered", [False, True])
def test_unknown_or_dynamic_abi_keeps_generic_decoder_and_errors(
    monkeypatch: pytest.MonkeyPatch, registered: bool
) -> None:
    row, _ = event(monkeypatch, [("values", "uint256[]", False, [1, 2, 3])])
    if not registered:
        monkeypatch.delitem(_deployment_topics, cast(ChecksumAddress, str(row.address)))
    fallback = Mock(side_effect=RuntimeError("original decoder failure"))
    monkeypatch.setattr(events, "decode_logs", fallback)
    with pytest.raises(RuntimeError, match="original decoder failure"):
        decode_pool_logs([row])
    fallback.assert_called_once_with([row])


def test_empty_metadata_has_no_decoder_or_database_work(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback = Mock(side_effect=AssertionError("decoded empty metadata"))
    monkeypatch.setattr(events, "decode_logs", fallback)
    assert list(decode_pool_logs([])) == []
    fallback.assert_not_called()


def test_metadata_reuse_preserves_changed_events_and_registered_abi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evmspec.data import BlockNumber
    from evmspec.structs.log import Data

    row, expected = event(monkeypatch, [("stable", "bool", False, True)])
    cache = metadata._MetadataCache()
    monkeypatch.setattr(metadata, "_metadata_cache", lambda: cache)
    decoder = Mock(wraps=decode)
    monkeypatch.setattr(metadata, "decode", decoder)
    first = list(decode_pool_logs([row]))
    later = list(decode_pool_logs([replace(row, blockNumber=BlockNumber(99999))]))
    assert first == later == [expected]
    assert decoder.call_count == 1
    with pytest.raises(TypeError):
        first[0]["stable"] = False
    changed = replace(row, data=Data(encode(["bool"], [False])))
    assert list(decode_pool_logs([changed])) == [{"stable": False}]
    assert decoder.call_count == 2
    entry = _deployment_topics[cast(ChecksumAddress, str(row.address))][
        next(iter(_deployment_topics[cast(ChecksumAddress, str(row.address))]))
    ]
    renamed = {**entry, "inputs": [{**entry["inputs"][0], "name": "renamed"}]}
    monkeypatch.setitem(
        _deployment_topics[cast(ChecksumAddress, str(row.address))],
        next(iter(_deployment_topics[cast(ChecksumAddress, str(row.address))])),
        cast(TopicMapData, renamed),
    )
    assert list(decode_pool_logs([row])) == [{"renamed": True}]
    assert decoder.call_count == 3


def test_metadata_cache_eviction_and_oversized_pages_preserve_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evmspec.structs.log import Data

    row, _ = event(monkeypatch, [("value", "uint256", False, 1)])
    cache = metadata._MetadataCache(max_rows=2, max_pages=2)
    monkeypatch.setattr(metadata, "_metadata_cache", lambda: cache)
    decoder = Mock(wraps=decode)
    monkeypatch.setattr(metadata, "decode", decoder)
    for value in (1, 2, 3, 1):
        changed = replace(row, data=Data(encode(["uint256"], [value])))
        assert list(decode_pool_logs([changed])) == [{"value": value}]
    assert decoder.call_count == 4
    assert list(decode_pool_logs([row, row, row])) == [{"value": 1}] * 3
    assert list(decode_pool_logs([row, row, row])) == [{"value": 1}] * 3
    assert decoder.call_count == 10
