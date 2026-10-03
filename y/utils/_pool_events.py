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


def _decode_static_word(kind: str, word: bytes) -> Any:
    """Decode fixed factory fields with the ABI codec's padding and range rules."""
    if len(word) == 32:
        if kind == "address" and word[:12] == bytes(12):
            return "0x" + word[12:].hex()
        if kind == "bytes32":
            return word
        value = int.from_bytes(word, "big", signed=kind == "int24")
        if kind == "uint256":
            return value
        if kind == "uint24" and value < 1 << 24:
            return value
        if kind == "int24" and -(1 << 23) <= value < 1 << 23:
            return value
        if kind == "bool" and value in (0, 1):
            return bool(value)
    # Preserve the primary codec's exact validation and exceptions on malformed
    # words; no invalid padding or out-of-range value becomes valid metadata.
    return decode([kind], word)[0]


def decode_pool_logs(rows: list[Log]) -> Iterable[Any]:
    """Use the registered event ABI, retaining the generic decoder for other logs.

    All supported factory fields occupy one ABI word. Indexed and non-indexed
    words can be decoded together with the same strict ABI validation, avoiding
    checksum/wrapper creation for addresses immediately normalized by consumers.
    """
    from y.utils.events import decode_logs

    if not rows:
        return ()
    if not all(isinstance(row, Log) for row in rows):
        return decode_logs(rows)
    # evmspec lazily wraps fields on attribute access. Retain each immutable
    # field once for validation, fingerprinting, and decoding this page.
    prepared = [(row.address, row.topics, row.data) for row in rows]
    if any(not topics for _, topics, _ in prepared):
        return decode_logs(rows)
    first_address, first_topics, _ = prepared[0]
    topic = "0x" + first_topics[0].hex().removeprefix("0x")
    entry = _deployment_topics.get(cast(ChecksumAddress, str(first_address)), {}).get(
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
    fields = tuple((field["name"], field["type"]) for field in ordered)
    if any(addr != first_address or topics[0] != first_topics[0] for addr, topics, _ in prepared):
        return decode_logs(rows)
    fingerprint = blake2b(json.encode((str(first_address), entry)))
    # Only event fields and their ABI affect this metadata. Block selection is
    # still performed by the disk query, and state remains keyed by block hash.
    # Include every word and row boundary so changed pages cannot hit old data.
    words_and_data = []
    for _, topics, data in prepared:
        if len(topics) != indexed_count + 1:
            raise ValueError("Factory event has a different indexed field count")
        if data is None:
            raise ValueError("Factory event omitted its ABI data")
        topic_words = tuple(bytes(word) for word in topics)
        data_bytes = bytes(data)
        fingerprint.update(
            len(topic_words).to_bytes(4, "big")
            + b"".join(topic_words)
            + len(data_bytes).to_bytes(4, "big")
            + data_bytes
        )
        words_and_data.append((topic_words, data_bytes))
    key = fingerprint.digest()
    cache = _metadata_cache()
    if cached := cache.get(key):
        return cached
    decoded = []
    for topic_words, data_bytes in words_and_data:
        words = list(topic_words[1:])
        words.extend(
            data_bytes[offset : offset + 32]
            for offset in range(0, 32 * (len(fields) - indexed_count), 32)
        )
        decoded.append(
            MappingProxyType(
                {name: _decode_static_word(kind, word) for (name, kind), word in zip(fields, words)}
            )
        )
    page = tuple(decoded)
    cache.put(key, page)
    return page
