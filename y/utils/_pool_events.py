"""Decode immutable static factory fields without Brownie's pool wrappers."""

from collections import OrderedDict
from collections.abc import Iterable, Mapping
from functools import lru_cache
from hashlib import blake2b
from threading import Lock
from types import MappingProxyType
from typing import Any, cast

from brownie.network.event import _deployment_topics
from eth_abi.abi import decode
from eth_typing import ChecksumAddress, HexStr
from evmspec import Log
from msgspec import json

_STATIC_TYPES = frozenset({"address", "bool", "bytes32", "int24", "uint24", "uint256"})


class _MetadataCache:
    """Own a bounded catalog of immutable decoded pages, without raw events."""

    def __init__(self, max_rows: int = 65536, max_pages: int = 128) -> None:
        self.max_rows = max_rows
        self.max_pages = max_pages
        self.rows = 0
        self.pages: OrderedDict[bytes, tuple[Mapping[str, Any], ...]] = OrderedDict()
        self.lock = Lock()

    def get(self, key: bytes) -> tuple[Mapping[str, Any], ...] | None:
        with self.lock:
            page = self.pages.get(key)
            if page is not None:
                self.pages.move_to_end(key)
            return page

    def put(self, key: bytes, page: tuple[Mapping[str, Any], ...]) -> None:
        if len(page) > self.max_rows:
            return
        with self.lock:
            if old := self.pages.pop(key, None):
                self.rows -= len(old)
            self.pages[key] = page
            self.rows += len(page)
            while self.rows > self.max_rows or len(self.pages) > self.max_pages:
                _, oldest = self.pages.popitem(last=False)
                self.rows -= len(oldest)


@lru_cache(maxsize=1)
def _metadata_cache() -> _MetadataCache:
    return _MetadataCache()


def decode_pool_logs(rows: list[Log]) -> Iterable[Any]:
    """Use the registered event ABI, retaining the generic decoder for other logs.

    All supported factory fields occupy one ABI word. Indexed and non-indexed
    words can be decoded together with the same strict ABI validation, avoiding
    checksum/wrapper creation for addresses immediately normalized by consumers.
    """
    from y.utils.events import decode_logs

    if not rows:
        return ()
    if not all(isinstance(row, Log) and row.topics for row in rows):
        return decode_logs(rows)
    first = rows[0]
    topic = "0x" + first.topics[0].hex().removeprefix("0x")
    entry = _deployment_topics.get(cast(ChecksumAddress, str(first.address)), {}).get(
        cast(HexStr, topic)
    )
    if entry is None:
        return decode_logs(rows)
    inputs = entry["inputs"]
    if any(field["type"] not in _STATIC_TYPES for field in inputs):
        return decode_logs(rows)
    ordered = [field for field in inputs if field["indexed"]]
    indexed_count = len(ordered)
    ordered.extend(field for field in inputs if not field["indexed"])
    types = [field["type"] for field in ordered]
    names = [field["name"] for field in ordered]
    if any(row.address != first.address or row.topics[0] != first.topics[0] for row in rows):
        return decode_logs(rows)
    fingerprint = blake2b(json.encode((str(first.address), entry)))
    # Only event fields and their ABI affect this metadata. Block selection is
    # still performed by the disk query, and state remains keyed by block hash.
    # Include every word and row boundary so changed pages cannot hit old data.
    for row in rows:
        if len(row.topics) != indexed_count + 1:
            raise ValueError("Factory event has a different indexed field count")
        if row.data is None:
            raise ValueError("Factory event omitted its ABI data")
        fingerprint.update(len(row.topics).to_bytes(4, "big"))
        for word in row.topics:
            fingerprint.update(bytes(word))
        fingerprint.update(len(row.data).to_bytes(4, "big"))
        fingerprint.update(bytes(row.data))
    key = fingerprint.digest()
    cache = _metadata_cache()
    if cached := cache.get(key):
        return cached
    decoded = []
    for row in rows:
        if len(row.topics) != indexed_count + 1:
            raise ValueError("Factory event has a different indexed field count")
        if row.data is None:
            raise ValueError("Factory event omitted its ABI data")
        payload = b"".join(bytes(value) for value in row.topics[1:]) + bytes(row.data)
        decoded.append(MappingProxyType(dict(zip(names, decode(types, payload)))))
    page = tuple(decoded)
    cache.put(key, page)
    return page
