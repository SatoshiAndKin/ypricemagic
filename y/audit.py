"""Historical comparison reports. DeFiLlama is never a production price source."""

import asyncio
import csv
import json
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation, localcontext
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.request import urlopen

from y._decorators import stuck_coro_debugger


def utc_timestamp(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise ValueError("timestamps must specify UTC (Z or +00:00)")
    return int(parsed.timestamp())


def quarterly_samples(latest_timestamp: int, start_year: int = 2021) -> list[int]:
    latest = datetime.fromtimestamp(latest_timestamp, timezone.utc)
    result = []
    for year in range(start_year, latest.year + 1):
        for month in (1, 4, 7, 10):
            next_year, next_month = (year + 1, 1) if month == 10 else (year, month + 3)
            end = int(datetime(next_year, next_month, 1, tzinfo=timezone.utc).timestamp()) - 1
            if end <= latest_timestamp:
                result.append(end)
    return result


def reference_status(
    reference: dict[str, Any] | None, timestamp: int, max_age: int
) -> tuple[str | None, dict[str, Any]]:
    if not reference:
        return "missing reference", {}
    try:
        price = Decimal(str(reference["price"]))
        confidence = Decimal(str(reference["confidence"]))
        returned_time = int(reference["timestamp"])
    except (KeyError, ValueError, TypeError, InvalidOperation):
        return "invalid reference fields", {"reference": json.dumps(reference, default=str)}
    age = abs(timestamp - returned_time)
    details = {
        "reference_price": str(price),
        "reference_confidence": str(confidence),
        "reference_timestamp": returned_time,
        "reference_age_seconds": age,
    }
    if not price.is_finite() or price <= 0:
        return "reference must be positive and finite", details
    if not confidence.is_finite() or confidence < Decimal("0.9"):
        return "reference confidence below 0.9", details
    if age > max_age:
        return "stale reference", details
    return None, details


class AuditClient:
    """RPC and HTTP boundary, replaced by controlled clients in tests."""

    def __init__(self) -> None:
        self.blocks: dict[int, dict[str, Any]] = {}
        self.block_calls = 0
        self.http_calls = 0

    async def block(self, number: int | Literal["latest"]) -> dict[str, Any]:
        from dank_mids.brownie_patch import dank_web3

        if isinstance(number, int) and number in self.blocks:
            return self.blocks[number]
        self.block_calls += 1
        raw = await dank_web3.eth.get_block(number)
        result: dict[str, Any] = {
            "number": int(raw["number"]),
            "hash": "0x" + bytes(raw["hash"]).hex(),
            "timestamp": int(raw["timestamp"]),
        }
        self.blocks[result["number"]] = result
        return result

    async def at_or_before(self, timestamp: int) -> dict[str, Any]:
        latest = await self.block("latest")
        if timestamp > latest["timestamp"]:
            raise ValueError("timestamp is beyond the archive node's latest block")
        low, high = 0, latest["number"]
        if timestamp < (await self.block(0))["timestamp"]:
            raise ValueError("timestamp is before genesis")
        while low < high:
            middle = (low + high + 1) // 2
            if (await self.block(middle))["timestamp"] <= timestamp:
                low = middle
            else:
                high = middle - 1
        return await self.block(low)

    async def references(self, timestamp: int, identifiers: list[str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for start in range(0, len(identifiers), 50):
            url = f"https://coins.llama.fi/prices/historical/{timestamp}/" + ",".join(
                identifiers[start : start + 50]
            )
            self.http_calls += 1

            def fetch() -> dict[str, Any]:
                with urlopen(url, timeout=60) as response:
                    payload: dict[str, Any] = json.load(response)["coins"]
                    return payload

            result.update(await asyncio.to_thread(fetch))
        return result

    async def price(self, token: str, block: int, amount: Decimal | None = None) -> Any:
        from y.prices.magic import get_price

        lookup: Any = get_price
        return await lookup(token, block, amount=amount, skip_cache=True, sync=False)

    async def decimals(self, token: str, block: int) -> int:
        from y.prices._rpc import BlockRef, read

        return int(await read(token, "decimals()(uint8)", await BlockRef.resolve(block)))

    async def boundaries(self, tokens: list[str], latest: int) -> list[dict[str, Any]]:
        from y.contracts import contract_creation_block_async
        from y.prices import chainlink

        samples: list[dict[str, Any]] = []
        for token in tokens:
            deployed = int(await contract_creation_block_async(token))
            samples.extend(
                {"block": b, "tokens": [token], "label": "deployment boundary"}
                for b in (deployed - 1, deployed)
                if b >= 0
            )
        if chainlink and chainlink._feeds_from_events:
            tokens_lower = {t.lower() for t in tokens}
            events: Any = chainlink._feeds_from_events
            async for feed in events.objects(to_block=latest):
                if str(feed.asset).lower() in tokens_lower:
                    samples.extend(
                        {"block": b, "tokens": [str(feed.asset)], "label": "feed boundary"}
                        for b in (feed.start_block - 1, feed.start_block)
                        if b >= 0
                    )
        return samples

    def counts(self) -> dict[str, int]:
        from dank_mids.controller import instances

        # These counters describe logical calls and generated batches separately.
        # They are process-wide; the audit runs samples sequentially.
        return {
            "block_rpc": self.block_calls,
            "http": self.http_calls,
            **{
                name: sum(
                    getattr(controller, name).latest + 1
                    for group in instances.values()
                    for controller in group
                )
                for name in ("call_uid", "request_uid", "multicall_uid", "jsonrpc_batch_uid")
            },
        }


def manifest_samples(manifest: dict[str, Any], latest_timestamp: int) -> list[dict[str, Any]]:
    samples = list(manifest.get("samples", []))
    if manifest.get("quarterly", False):
        samples.extend(
            {
                "timestamp": datetime.fromtimestamp(t, timezone.utc).isoformat(),
                "label": "quarter end",
            }
            for t in quarterly_samples(latest_timestamp, int(manifest.get("start_year", 2021)))
        )
    if not samples:
        raise ValueError("manifest must contain samples or enable quarterly sampling")
    return samples


@stuck_coro_debugger
async def audit(manifest: dict[str, Any], client: AuditClient) -> dict[str, Any]:
    started = perf_counter()
    tokens = manifest["tokens"]
    if not tokens or not isinstance(tokens, list):
        raise ValueError("tokens must be a nonempty list")
    addresses = [item["address"] if isinstance(item, dict) else item for item in tokens]
    from eth_utils.address import is_address

    if any(not is_address(token) for token in addresses):
        raise ValueError("manifest tokens must be complete EVM addresses")
    try:
        latest = await client.block("latest")
    except Exception as exc:
        failure = f"latest block: {type(exc).__name__}: {exc}"
        requested = manifest.get("samples", [])
        if manifest.get("quarterly"):
            requested = [
                *requested,
                {"quarterly": True, "start_year": manifest.get("start_year", 2021)},
            ]
        rows: list[dict[str, Any]] = [
            dict(token=token, requested_sample=sample, status="incomplete", failure=failure)
            for sample in requested
            for token in sample.get("tokens", addresses)
        ]
        return {
            "manifest": manifest,
            "network": manifest["network"],
            "rows": rows,
            "preparation_errors": [failure],
            "summary": {"pass": 0, "price_failure": 0, "incomplete": max(1, len(rows))},
            "rpc_counts": client.counts(),
            "elapsed_seconds": perf_counter() - started,
            "exit_code": 2,
        }
    samples = manifest_samples(manifest, latest["timestamp"])
    preparation_errors = []
    if manifest.get("boundaries"):
        try:
            samples.extend(await client.boundaries(addresses, latest["number"]))
        except Exception as exc:
            preparation_errors.append(f"boundary coverage: {type(exc).__name__}: {exc}")
    chain = manifest.get("llama_chain", "ethereum")
    rows = []
    for sample in samples:
        sample_tokens = sample.get("tokens", addresses)
        base: dict[str, Any] = {
            "requested_sample": sample,
            "reference_source": "DeFiLlama historical prices",
        }
        try:
            if ("block" in sample) == ("timestamp" in sample):
                raise ValueError("each sample needs exactly one block or UTC timestamp")
            block = (
                await client.block(int(sample["block"]))
                if "block" in sample
                else await client.at_or_before(utc_timestamp(sample["timestamp"]))
            )
            base.update(
                {
                    "block_number": block["number"],
                    "block_hash": block["hash"],
                    "block_timestamp": block["timestamp"],
                }
            )
        except Exception as exc:
            rows.extend(
                dict(
                    base,
                    token=t,
                    status="incomplete",
                    failure=f"block resolution: {type(exc).__name__}: {exc}",
                )
                for t in sample_tokens
            )
            continue
        reference_error = None
        try:
            references = await client.references(
                block["timestamp"], [f"{chain}:{t.lower()}" for t in sample_tokens]
            )
        except Exception as exc:
            references = {}
            reference_error = f"reference request: {type(exc).__name__}: {exc}"
        for token in sample_tokens:
            identifier = f"{chain}:{token.lower()}"
            reference = references.get(identifier)
            error, details = reference_status(
                reference, block["timestamp"], 900 if sample.get("stress") else 3600
            )
            row = dict(base, token=token, reference_identifier=identifier, **details)
            if error:
                rows.append(
                    dict(row, mode="spot", status="incomplete", failure=reference_error or error)
                )
                for size in sample.get("amounts", manifest.get("amounts", [])):
                    rows.append(
                        dict(
                            row,
                            mode="sale",
                            amount=str(size),
                            status="incomplete",
                            failure=reference_error or error,
                        )
                    )
                # Keep unsized amount comparisons visible too.
                for size in manifest.get("usd_amounts", []):
                    rows.append(
                        dict(
                            row,
                            mode="sale",
                            requested_usd=str(size),
                            status="incomplete",
                            failure="reference unavailable for sizing",
                        )
                    )
                continue
            sizes: list[tuple[Decimal | None, str | None]] = [(None, None)]
            try:
                sizes.extend(
                    (Decimal(str(size)), None)
                    for size in sample.get("amounts", manifest.get("amounts", []))
                )
                if manifest.get("usd_amounts"):
                    decimals = await client.decimals(token, block["number"])
                    with localcontext() as context:
                        context.prec = 100
                        sizes.extend(
                            (
                                (Decimal(str(usd)) / Decimal(details["reference_price"])).quantize(
                                    Decimal(1).scaleb(-decimals), rounding=ROUND_DOWN
                                ),
                                str(usd),
                            )
                            for usd in manifest["usd_amounts"]
                        )
            except Exception as exc:
                rows.append(
                    dict(
                        row,
                        mode="sale",
                        status="incomplete",
                        failure=f"amount sizing: {type(exc).__name__}: {exc}",
                    )
                )
            for amount, requested_usd in sizes:
                began, counts = perf_counter(), client.counts()
                result_row = dict(
                    row,
                    mode="spot" if amount is None else "sale",
                    amount=None if amount is None else str(amount),
                    requested_usd=requested_usd,
                )
                try:
                    result = await client.price(token, block["number"], amount)
                    value = Decimal(str(float(result)))
                    if not value.is_finite() or value <= 0:
                        raise ValueError("price must be positive and finite")
                    deviation = abs(value / Decimal(details["reference_price"]) - 1)
                    result_row.update(
                        price=str(value),
                        path=[asdict(step) for step in result.path],
                        quote=asdict(result.quote) if result.quote else None,
                    )
                    if amount is None:
                        result_row.update(
                            deviation=str(deviation),
                            status="pass" if deviation <= Decimal("0.05") else "price_failure",
                        )
                    else:
                        if result.quote is None:
                            raise ValueError("amount request returned no structured native quote")
                        result_row.update(
                            sale_impact=str(1 - value / Decimal(details["reference_price"])),
                            status="pass",
                        )
                except Exception as exc:
                    result_row.update(
                        status="price_failure", failure=f"{type(exc).__name__}: {exc}"
                    )
                result_row["elapsed_seconds"] = perf_counter() - began
                result_row["rpc_counts"] = {
                    key: value - counts.get(key, 0) for key, value in client.counts().items()
                }
                rows.append(result_row)
    summary = {
        status: sum(row["status"] == status for row in rows)
        for status in ("pass", "price_failure", "incomplete")
    }
    summary["incomplete"] += len(preparation_errors)
    return {
        "manifest": manifest,
        "network": manifest["network"],
        "chain": chain,
        "latest_block": latest,
        "spot_tolerance": "0.05",
        "rows": rows,
        "preparation_errors": preparation_errors,
        "summary": summary,
        "rpc_counts": client.counts(),
        "elapsed_seconds": perf_counter() - started,
        "exit_code": 1 if summary["price_failure"] else 2 if summary["incomplete"] else 0,
    }


def write_reports(report: dict[str, Any], json_path: Path, csv_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, default=str, allow_nan=False) + "\n")
    fields = sorted({key for row in report["rows"] for key in row})
    with csv_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fields, lineterminator="\n")
        writer.writeheader()
        for row in report["rows"]:
            writer.writerow(
                {
                    key: (
                        json.dumps(value, default=str) if isinstance(value, (dict, list)) else value
                    )
                    for key, value in row.items()
                }
            )


def run_manifest(manifest_path: Path, json_path: Path, csv_path: Path) -> int:
    from brownie.network.main import show_active

    manifest = json.loads(manifest_path.read_text(), parse_float=Decimal)
    if manifest["network"] != show_active():
        raise ValueError(
            f"manifest requests {manifest['network']}; set BROWNIE_NETWORK_ID to that network before starting"
        )
    report = asyncio.get_event_loop().run_until_complete(audit(manifest, AuditClient()))
    write_reports(report, json_path, csv_path)
    print(json.dumps(report["summary"]))
    return int(report["exit_code"])
