"""Trace cache lookups use the schema's address columns and encoded keys."""

from types import ModuleType

import pytest
from pony.orm import db_session

from tests.test_log_cache import event_database as event_database
from y._db.utils import traces, utils


@pytest.mark.parametrize("nested", [False, True])
def test_trace_address_predicates(nested: bool) -> None:
    action = {"from": "sender", "to": "recipient"}
    trace = {"action": action, "blockNumber": 10, "type": "call"} if nested else action
    assert traces.trace_is_from(["sender"], trace)
    assert traces.trace_is_to(["recipient"], trace)
    assert not traces.trace_is_from(["recipient"], trace)
    assert not traces.trace_is_to(["sender"], trace)


def test_trace_cache_metadata_and_directional_selection(
    event_database: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated = event_database
    sender = "0x0000000000000000000000000000000000000001"
    recipient = "0x0000000000000000000000000000000000000002"
    monkeypatch.setattr(traces, "TraceCacheInfo", isolated.TraceCacheInfo)
    monkeypatch.setattr(traces, "Trace", isolated.Trace)
    with db_session:
        chain = isolated.Chain(id=1)
        monkeypatch.setattr(utils, "get_chain", lambda **kwargs: chain)
        block = isolated.Block(chain=chain, number=10)
        isolated.Trace(
            block=block,
            hash="11" * 32,
            from_address=sender,
            to_address=recipient,
            raw=b'{"marker":"forward"}',
        )
        isolated.Trace(
            block=block,
            hash="22" * 32,
            from_address=recipient,
            to_address=sender,
            raw=b'{"marker":"reverse"}',
        )
        cache = traces.TraceCache([sender], [recipient])
        cache._set_metadata(10, 12)
        info = cache.load_metadata(chain, sender, recipient)
        assert info is not None
        assert (info.cached_from, info.cached_thru) == (10, 12)
        assert cache._is_cached_thru(10) == 12
        assert cache._is_cached_thru(9) == 0
        assert cache._select(10, 10) == [{"marker": "forward"}]
        assert cache._select(11, 12) == []
        cache._set_metadata(8, 14)
        assert (info.cached_from, info.cached_thru) == (8, 14)
        assert traces.TraceCache([recipient], [sender])._select(10, 10) == [{"marker": "reverse"}]
