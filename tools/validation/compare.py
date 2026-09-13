"""Compare completed reports without turning missing evidence into a pass."""

import argparse
import json
from pathlib import Path
from typing import Any

from common import write_json


def failures(directory: Path) -> dict[str, Any]:
    rows = {}
    with (directory / "pytest-events.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("outcome") == "failed":
                rows[row["test"] + "::" + row["phase"]] = row["error_message"]
    return rows


def complete_test_report(directory: Path) -> bool:
    summary = json.loads((directory / "pytest-summary.json").read_text())
    counts = summary.get("counts", {})
    completed = sum(
        counts.get(key, 0)
        for key in ("call:passed", "call:failed", "call:skipped", "setup:failed", "setup:skipped")
    )
    reported = 0
    last: dict[str, Any] = {}
    with (directory / "pytest-events.jsonl").open() as stream:
        for line in stream:
            last = json.loads(line)
            if last.get("phase") == "call" and last.get("outcome") in (
                "passed",
                "failed",
                "skipped",
            ):
                reported += 1
            elif last.get("phase") == "setup" and last.get("outcome") in ("failed", "skipped"):
                reported += 1
    return bool(
        summary.get("exit_code") in (0, 1)
        and completed == reported == summary.get("collected")
        and last.get("phase") == "sessionfinish"
        and last.get("exit_code") == summary["exit_code"]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("changed", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = json.loads((args.baseline / "run.json").read_text())
    after = json.loads((args.changed / "run.json").read_text())
    required = ["dependencies-after.txt", "pytest-events.jsonl", "pytest-summary.json"]
    if any((path / "unit-dependencies.txt").exists() for path in (args.baseline, args.changed)):
        required.append("unit-dependencies.txt")
    missing = [
        str(path / name)
        for path in (args.baseline, args.changed)
        for name in required
        if not (path / name).is_file()
    ]
    dependencies_equal = not missing and all(
        (args.baseline / name).read_text() == (args.changed / name).read_text()
        for name in required
        if name.endswith("dependencies.txt") or name == "dependencies-after.txt"
    )
    test_reports_complete = not missing and all(
        complete_test_report(path) for path in (args.baseline, args.changed)
    )
    failures_comparable = bool(
        test_reports_complete and before["image"] == after["image"] and dependencies_equal
    )
    comparison: dict[str, Any] = {
        "baseline": before,
        "changed": after,
        "missing_reports": missing,
        "dependencies_equal": dependencies_equal,
        "test_reports_complete": test_reports_complete,
        "failures_comparable": failures_comparable,
        "comparable": bool(before["complete"] and after["complete"] and failures_comparable),
    }
    # A known process-exit failure can follow a complete pytest session. Keep
    # its test/error comparison while still marking execution incomparable.
    if failures_comparable:
        old, new = failures(args.baseline), failures(args.changed)
        comparison.update(
            unchanged={key: value for key, value in new.items() if old.get(key) == value},
            changed_errors={
                key: {"baseline": old[key], "changed": new[key]}
                for key in new.keys() & old.keys()
                if new[key] != old[key]
            },
            new_failures={key: new[key] for key in new.keys() - old.keys()},
            removed_failures={key: old[key] for key in old.keys() - new.keys()},
        )
    write_json(args.output, comparison)


if __name__ == "__main__":
    main()
