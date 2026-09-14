"""Supervise one command and persist cgroup data before the container exits."""

import argparse
import os
import platform
import signal
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

from common import write_json


def cgroup() -> dict[str, object]:
    root = Path("/sys/fs/cgroup")
    result: dict[str, object] = {}
    for name in (
        "memory.current",
        "memory.peak",
        "memory.max",
        "memory.swap.max",
        "memory.events",
        "cpu.max",
        "pids.max",
        "pids.current",
    ):
        result[name] = (root / name).read_text().strip()
    return result


def rss() -> int:
    total = 0
    for path in Path("/proc").glob("[0-9]*/status"):
        try:
            for line in path.read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1]) * 1024
        except (FileNotFoundError, ProcessLookupError):
            pass
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    write_json(
        args.report / "environment.json",
        {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "soabi": sysconfig.get_config_var("SOABI"),
        },
    )
    before = cgroup()
    if (
        before["memory.max"] != str(8 * 1024**3)
        or before["memory.swap.max"] != "0"
        or before["cpu.max"] != "400000 100000"
        or before["pids.max"] != "512"
    ):
        raise RuntimeError(f"Unexpected effective limits: {before}")
    started = time.monotonic()
    # Reused images can add packages after writing their build manifest. Record
    # the installed environment before the command, including failed startup.
    with (args.report / "dependencies.txt").open("w") as stream:
        subprocess.run(["python", "-m", "pip", "freeze", "--all"], stdout=stream, check=True)
    subprocess.run(["python", "/runner/configure.py"], check=True)
    child = subprocess.Popen(command, start_new_session=True)
    interrupted = False

    def stop(signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True
        try:
            os.killpg(child.pid, signum)
        except ProcessLookupError:
            pass

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    peak_rss = 0
    while child.poll() is None:
        sampled_rss = rss()
        peak_rss = max(peak_rss, sampled_rss)
        write_json(
            args.report / "progress.json",
            {
                "elapsed_seconds": time.monotonic() - started,
                "sampled_process_rss_bytes": sampled_rss,
                "peak_sampled_process_rss_bytes": peak_rss,
                "cgroup": cgroup(),
            },
        )
        time.sleep(1)
    after = cgroup()
    assert child.returncode is not None
    with (args.report / "dependencies-after.txt").open("w") as stream:
        subprocess.run(["python", "-m", "pip", "freeze", "--all"], stdout=stream, check=True)
    write_json(
        args.report / "command.json",
        {
            "command": command,
            "exit_code": child.returncode,
            "interrupted": interrupted,
            "elapsed_seconds": time.monotonic() - started,
            "peak_sampled_process_rss_bytes": peak_rss,
            "cgroup_before": before,
            "cgroup_after": after,
        },
    )
    return child.returncode if child.returncode >= 0 else 128 - child.returncode


if __name__ == "__main__":
    raise SystemExit(main())
