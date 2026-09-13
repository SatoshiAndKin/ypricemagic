"""Exercise cancellation, duplicate exclusion, and real console rotation."""

import argparse
import json
from pathlib import Path
import signal
import subprocess
import sys
import time

from common import write_json


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report.mkdir(parents=True, exist_ok=False)
    runner = Path(__file__).with_name("run.py")
    command = [sys.executable, str(runner), "--revision", "worktree", "--image", args.image]
    cancelled = args.report / "cancelled"
    child = subprocess.Popen(
        [
            *command,
            "--report",
            str(cancelled),
            "--",
            "python",
            "-c",
            "import time; print('ready', flush=True); time.sleep(3600)",
        ],
        stdout=subprocess.DEVNULL,
    )
    try:
        started = time.monotonic()
        while (
            not (cancelled / "console.log").exists()
            or b"ready" not in (cancelled / "console.log").read_bytes()
        ):
            if child.poll() is not None or time.monotonic() - started > 60:
                raise AssertionError("Cancellation fixture did not start")
            time.sleep(0.25)
        duplicate = subprocess.run(
            [*command, "--report", str(args.report / "duplicate"), "--", "true"],
            capture_output=True,
        )
        assert duplicate.returncode != 0 and b"Cannot reserve validation lock" in duplicate.stderr
        assert child.poll() is None
    finally:
        if child.poll() is None:
            child.send_signal(signal.SIGTERM)
        child.wait(timeout=60)
    cancel_run = json.loads((cancelled / "run.json").read_text())
    assert not cancel_run["complete"] and cancel_run["interrupted"]
    assert not cancel_run["oom_killed"]
    assert (cancelled / "container-state.json").is_file()
    assert json.loads((cancelled / "command.json").read_text())["interrupted"]
    rotation = args.report / "rotation"
    subprocess.run(
        [
            *command,
            "--report",
            str(rotation),
            "--",
            "python",
            "-c",
            "import os; chunk = b'x' * 65536; " "[(os.write(1, chunk)) for _ in range(9600)]",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )
    retention = json.loads((rotation / "console.retention.json").read_text())
    assert retention["total_bytes"] == 600 * 1024**2
    assert retention["expired_bytes"] == 100 * 1024**2
    logs = list(rotation.glob("console.log*"))
    assert len(logs) == 5
    assert all(path.stat().st_size == 100 * 1024**2 for path in logs)
    assert json.loads((rotation / "run.json").read_text())["complete"]
    write_json(
        args.report / "verification.json",
        {"cancellation": cancel_run, "duplicate_prevented": True, "rotation": retention},
    )


if __name__ == "__main__":
    main()
