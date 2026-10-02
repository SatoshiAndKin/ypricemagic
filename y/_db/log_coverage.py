"""Pure filter-containment and completed-range calculations."""

from collections.abc import Iterable, Sequence
from typing import Any


def _choices(topic: Any) -> set[str] | None:
    if topic is None:
        return None
    if isinstance(topic, (str, bytes)):
        topic = [topic]
    return {
        value.lower().removeprefix("0x") if isinstance(value, str) else bytes(value).hex()
        for value in topic
    }


def topics_cover(cached: Sequence[Any] | None, requested: Sequence[Any] | None) -> bool:
    """A broad filter must contain every result allowed by the requested filter."""
    cached, requested = cached or (), requested or ()
    if len(cached) > len(requested):
        return False
    for position, constraint in enumerate(cached):
        allowed = _choices(constraint)
        wanted = _choices(requested[position])
        if allowed is not None and (wanted is None or not wanted <= allowed):
            return False
    return True


def completed_thru(start: int, ranges: Iterable[tuple[int, int]]) -> int:
    """Join overlapping/adjacent completed intervals, stopping at the first gap."""
    end = start - 1
    for first, last in sorted(ranges):
        if first > end + 1:
            break
        if last >= start:
            end = max(end, last)
    return end if end >= start else 0
