"""Stored events must decode without reading or writing ORM entities."""

from unittest.mock import Mock

import pytest
from evmspec.data._main import _decode_hook
from msgspec import ValidationError, json

from y._db.log import Log
from y._db.utils import logs


@pytest.fixture
def event() -> Log:
    return json.decode(
        json.encode(
            [
                ["0x" + "ab" * 32],
                "0x0000000000000000000000000000000000000001",
                "0x0001",
                False,
                "0x1234",
                "0x" + "ef" * 32,
                "0x2",
                "0x3",
            ]
        ),
        type=Log,
        dec_hook=_decode_hook,
    )


def test_cached_json_round_trip_needs_no_database(
    event: Log, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbidden = Mock(side_effect=AssertionError("cache decoding must not access the database"))
    monkeypatch.setattr(logs, "_get_hash", forbidden)
    monkeypatch.setattr(logs, "commit", forbidden)
    encoded = logs._encode_log(event)
    assert encoded.startswith(b"[")
    for _ in range(2):
        restored = logs._decode_log(encoded)
        assert restored == event
        assert restored.address == "0x0000000000000000000000000000000000000001"
        assert restored.blockNumber == 0x1234
        assert restored.logIndex == 2
        assert restored.transactionIndex == 3
    forbidden.assert_not_called()


def test_invalid_cached_event_keeps_validation_error() -> None:
    with pytest.raises(ValidationError):
        logs._decode_log(b'["invalid topics"]')
