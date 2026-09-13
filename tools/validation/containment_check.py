"""Exercise real Docker limits, OOM reporting, cancellation and name exclusion."""

import argparse
import json
from pathlib import Path
import subprocess

from common import write_json
from run import CONTAINER, LOCK, docker


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    args.report.mkdir(parents=True, exist_ok=False)
    docker("create", "--name", LOCK, "busybox:latest", "true")
    try:
        duplicate = subprocess.run(
            ["docker", "create", "--name", LOCK, "busybox:latest", "true"], capture_output=True
        )
        assert duplicate.returncode != 0 and b"already in use" in duplicate.stderr
        record = {"duplicate_prevented": True}
        for label, program in (
            ("oom", "value = bytearray(128 * 1024**2)"),
            ("cancel", "import time; time.sleep(3600)"),
        ):
            docker(
                "create",
                "--name",
                CONTAINER,
                "--platform=linux/arm64",
                "--memory=64m",
                "--memory-swap=64m",
                "--cpus=4",
                "--pids-limit=512",
                "--log-driver=json-file",
                "--log-opt=max-size=100m",
                "--log-opt=max-file=5",
                args.image,
                "python",
                "-c",
                program,
            )
            try:
                docker("start", CONTAINER)
                limits = json.loads(docker("inspect", CONTAINER))[0]["HostConfig"]
                assert (
                    limits["Memory"],
                    limits["MemorySwap"],
                    limits["NanoCpus"],
                    limits["PidsLimit"],
                ) == (64 * 1024**2, 64 * 1024**2, 4_000_000_000, 512)
                if label == "cancel":
                    docker("stop", "--time", "2", CONTAINER)
                docker("wait", CONTAINER)
                state = json.loads(docker("inspect", CONTAINER))[0]["State"]
                assert not state["Running"]
                if label == "oom":
                    assert state["OOMKilled"] and state["ExitCode"] == 137
                else:
                    assert state["ExitCode"] != 0 and not state["OOMKilled"]
                record[label] = state
                write_json(args.report / "containment.json", record)
            finally:
                docker("rm", "--force", CONTAINER)
        # Evidence must still exist after both containers are removed.
        assert json.loads((args.report / "containment.json").read_text())["oom"]["OOMKilled"]
    finally:
        docker("rm", LOCK)


if __name__ == "__main__":
    main()
