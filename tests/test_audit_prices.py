"""Controlled HTTP/RPC audit coverage, including stress-period reference age."""

import json
from decimal import Decimal
from typing import Any

import pytest

from tests.test_amount_quotes import TOKEN, USD
from tests.test_pricing_correctness import run_async_test
from y.audit import (
    AuditClient,
    audit,
    quarterly_samples,
    reference_status,
    utc_timestamp,
    write_reports,
)
from y.datatypes import PriceResult, PriceStep, QuoteAsset, QuoteDetails, UsdPrice


class ControlledClient(AuditClient):
    def __init__(
        self, reference_price: Any = 1, spot_price: Any = 1, age: Any = 0, confidence: Any = 1
    ) -> None:
        super().__init__()
        self.reference_price, self.spot_price = reference_price, spot_price
        self.age, self.confidence = age, confidence
        self.calls: list[Any] = []

    async def block(self, number: Any) -> Any:
        self.block_calls += 1
        number = 100 if number == "latest" else number
        return {"number": number, "hash": "0x" + f"{number:064x}", "timestamp": 1000 + number * 12}

    async def references(self, timestamp: Any, identifiers: Any) -> Any:
        self.http_calls += 1
        return {
            identifier: {
                "price": self.reference_price,
                "timestamp": timestamp - self.age,
                "confidence": self.confidence,
            }
            for identifier in identifiers
        }

    async def decimals(self, token: Any, block: Any) -> Any:
        return 6

    async def price(self, token: Any, block: Any, amount: Any = None) -> Any:
        self.calls.append((token, block, amount))
        if amount is None:
            return PriceResult(
                UsdPrice(self.spot_price),
                [PriceStep(token, UsdPrice(self.spot_price), "controlled historical feed")],
            )
        # A large sale can have substantial impact without failing the spot test.
        return PriceResult(
            UsdPrice("0.8"),
            [],
            QuoteDetails(
                QuoteAsset(token, int(amount * 10**6), 6),
                (QuoteAsset(USD, int(amount * 800000), 6),),
                amount * Decimal("0.8"),
                block,
                "0x" + f"{block:064x}",
                (),
            ),
        )

    def counts(self) -> Any:
        return {"block_rpc": self.block_calls, "http": self.http_calls, "quotes": len(self.calls)}


@pytest.mark.parametrize(
    "price,confidence,age,error",
    [
        (1, 1, 0, None),
        (0, 1, 0, "positive"),
        (-1, 1, 0, "positive"),
        ("NaN", 1, 0, "positive"),
        ("invalid", 1, 0, "invalid reference"),
        (1, "NaN", 0, "confidence"),
        (1, 0.89, 0, "confidence"),
        (1, 0.9, 3600, None),
        (1, 1, 3601, "stale"),
    ],
)
def test_reference_quality(price: Any, confidence: Any, age: Any, error: Any) -> None:
    actual, _ = reference_status(
        {"price": price, "confidence": confidence, "timestamp": 10000 - age}, 10000, 3600
    )
    if error is None:
        assert actual is None
    else:
        assert actual is not None and error in actual


@run_async_test
async def test_timestamp_resolves_last_block_at_or_before() -> None:
    client = ControlledClient()
    assert (await client.at_or_before(1119))["number"] == 9
    assert (await client.at_or_before(1120))["number"] == 10
    with pytest.raises(ValueError, match="latest"):
        await client.at_or_before(2201)


def test_quarters_stop_at_latest_completed_quarter_and_require_utc() -> None:
    latest = utc_timestamp("2023-05-01T00:00:00Z")
    samples = quarterly_samples(latest)
    assert len(samples) == 9
    assert samples[0] == utc_timestamp("2021-03-31T23:59:59Z")
    assert samples[-1] == utc_timestamp("2023-03-31T23:59:59Z")
    with pytest.raises(ValueError, match="UTC"):
        utc_timestamp("2023-05-01T00:00:00")


@run_async_test
@pytest.mark.parametrize(
    "spot,status,exit_code",
    [
        (1.05, "pass", 0),
        (1.050001, "price_failure", 1),
        (0.95, "pass", 0),
        (0.949999, "price_failure", 1),
    ],
)
async def test_spot_tolerance_and_separate_sale_impact(
    tmp_path: Any, spot: Any, status: Any, exit_code: Any
) -> None:
    client = ControlledClient(spot_price=spot)
    manifest = {
        "network": "mainnet",
        "tokens": [TOKEN],
        "samples": [{"block": 50}],
        "usd_amounts": [10, 1000, 100000],
    }
    report = await audit(manifest, client)
    assert report["exit_code"] == exit_code
    assert report["rows"][0]["status"] == status
    assert [row["amount"] for row in report["rows"]] == [
        None,
        "10.000000",
        "1000.000000",
        "100000.000000",
    ]
    assert all(
        row["sale_impact"] == "0.2" and row["status"] == "pass" for row in report["rows"][1:]
    )
    assert report["rows"][0]["token"] == TOKEN
    assert report["rpc_counts"]["http"] == 1
    write_reports(report, tmp_path / "report.json", tmp_path / "report.csv")
    assert json.loads((tmp_path / "report.json").read_text())["exit_code"] == exit_code
    assert TOKEN in (tmp_path / "report.csv").read_text()


@run_async_test
async def test_stress_reference_is_incomplete_and_keeps_sale_rows() -> None:
    report = await audit(
        {
            "network": "mainnet",
            "tokens": [TOKEN],
            "samples": [{"block": 50, "stress": True}],
            "amounts": ["1.23"],
            "usd_amounts": [10, 1000, 100000],
        },
        ControlledClient(age=901),
    )
    assert report["summary"] == {"pass": 0, "price_failure": 0, "incomplete": 5}
    assert report["rows"][1]["amount"] == "1.23"
    assert report["exit_code"] == 2


@run_async_test
async def test_missing_reference_or_price_failure_is_never_removed(monkeypatch: Any) -> None:
    client = ControlledClient()

    async def references(*args: Any) -> Any:
        raise OSError("HTTP response failed")

    monkeypatch.setattr(client, "references", references)
    report = await audit(
        {"network": "mainnet", "tokens": [TOKEN, USD], "samples": [{"block": 50}]}, client
    )
    assert len(report["rows"]) == 2
    assert report["exit_code"] == 2
    assert all("HTTP response failed" in row["failure"] for row in report["rows"])
