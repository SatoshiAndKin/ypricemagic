"""Concurrent event queries must not invalidate the same Pony translator twice."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError
from types import SimpleNamespace
from typing import Any, cast

import pytest
from pony.orm.core import Query

from y._db.utils import logs


def test_event_query_builders_serialize_pony_fixed_parameter_invalidation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendezvous = Barrier(2)

    class FixedParameters(dict[str, str]):
        def items(self) -> Any:
            # Reproduce two readers holding the same translator before either
            # deletes it. A protected query builder admits only the first reader.
            try:
                rendezvous.wait(timeout=0.1)
            except BrokenBarrierError:
                pass
            return super().items()

    key = "event query with a changed topic attribute"
    translator = SimpleNamespace(
        func_extractors_map={}, fixed_param_values=FixedParameters(topic_id="topic1")
    )
    database = SimpleNamespace(_translator_cache={key: translator})
    query = SimpleNamespace(_database=database)
    projection = SimpleNamespace()

    def factory_query(self: Any, start: int, end: int) -> Any:
        assert (start, end) == (1, 2)
        assert getattr(Query, "_get_translator")(query, key, {"topic_id": "topic2"}) == (
            None,
            {"topic_id": "topic2"},
        )
        return projection

    monkeypatch.setattr(logs.LogCache, "_factory_query", factory_query)
    monkeypatch.setattr(logs.LogCache, "_get_query", lambda *args: projection)
    monkeypatch.setattr(
        logs,
        "_factory_statistics",
        lambda database: SimpleNamespace(ensure=lambda database: None),
    )
    cache = logs.LogCache(None, None)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(cache._page_queries, 1, 2, None, 512) for _ in range(2)]
        results = [future.result() for future in futures]
        assert all(left is projection and right is projection for left, right in cast(Any, results))
    assert database._translator_cache == {}
