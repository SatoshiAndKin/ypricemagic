#!/usr/bin/env python3
"""Build and run isolated Linux validation. No project imports run on the host."""

import argparse
from collections.abc import Iterable
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tarfile
import tempfile
import time
import tomllib
from typing import Any

from common import ConsoleLog, write_json

ROOT = Path(__file__).resolve().parents[2]
BUILDER = "ypricemagic-validation"
LOCK = "ypricemagic-validation-lock"
CONTAINER = "ypricemagic-validation-job"


def output(*command: str) -> str:
    return subprocess.check_output(command, text=True).strip()


def docker(*command: str) -> str:
    return output("docker", *command)


def builder_memory(container: str) -> dict[str, Any]:
    lines = docker(
        "exec", container, "cat", "/sys/fs/cgroup/memory.peak", "/sys/fs/cgroup/memory.events"
    ).splitlines()
    return {"peak_bytes": int(lines[0]), "events": dict(line.split() for line in lines[1:])}


def snapshot(source: Path, revision: str, target: Path) -> dict[str, str]:
    sha = output(
        "git",
        "-C",
        str(source),
        "rev-parse",
        "HEAD" if revision == "worktree" else revision + "^{commit}",
    )
    archive = target / "source.tar"
    if revision == "worktree":
        names = output(
            "git", "-C", str(source), "ls-files", "-z", "--cached", "--others", "--exclude-standard"
        ).split("\0")
        with tarfile.open(archive, "w") as tar:
            for name in sorted(set(names)):
                if not name or name.startswith(("build/", "audits/results/", ".git/")):
                    continue
                path = source / name
                if path.is_file():
                    tar.add(path, arcname=name, recursive=False)
    else:
        with archive.open("wb") as stream:
            subprocess.run(["git", "-C", str(source), "archive", sha], stdout=stream, check=True)
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with tarfile.open(archive) as tar:
        tar.extractall(target / "source", filter="data")
    # Generated host artifacts have no place in a Linux build.
    shutil.rmtree(target / "source/build", ignore_errors=True)
    return {"source_sha": sha, "source_revision": revision, "source_archive_sha256": digest}


def logged(command: list[str], report: Path, name: str) -> int:
    log = ConsoleLog(report / f"{name}.log")
    try:
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            assert process.stdout is not None
            try:
                while data := os.read(process.stdout.fileno(), 65536):
                    log.write(data)
                return process.wait()
            except BaseException:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise
    finally:
        log.close()


def freeze_files(source: Path, target: Path, names: Iterable[str]) -> dict[str, str]:
    """Record and execute one immutable copy even if the checkout changes later."""
    target.mkdir()
    hashes = {}
    for name in names:
        content = (source / name).read_bytes()
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        shutil.copymode(source / name, destination)
        hashes[name] = hashlib.sha256(content).hexdigest()
    return hashes


def build(source: Path, report: Path, version: str, harness: Path) -> str:
    context = report / "build-input"
    context.mkdir()
    for name in ("requirements.txt", "requirements-dev.txt"):
        shutil.copyfile(source / name, context / name)
    lock = source / f"tools/validation/dependencies-{version}.lock"
    (context / "constraints.txt").write_text(lock.read_text() if lock.is_file() else "")
    config = tomllib.loads((source / "pyproject.toml").read_text())
    requirements = config["build-system"]["requires"] + ["setuptools<81", "setuptools-scm", "black"]
    (context / "requirements-build.txt").write_text("\n".join(requirements) + "\n")
    shutil.copyfile(harness / "Dockerfile", context / "Dockerfile")
    digest = hashlib.sha256(
        version.encode() + b"".join(p.read_bytes() for p in sorted(context.iterdir()))
    ).hexdigest()[:20]
    image = f"ypricemagic-validation:py{version}-{digest}"
    if (
        subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode
        == 0
    ):
        return docker("image", "inspect", image, "--format", "{{.Id}}")
    if subprocess.run(
        ["docker", "buildx", "inspect", BUILDER],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode:
        docker(
            "buildx",
            "create",
            "--name",
            BUILDER,
            "--driver",
            "docker-container",
            "--driver-opt",
            "memory=8g,memory-swap=8g,cpu-period=100000,cpu-quota=400000",
        )
    builder_container = f"buildx_buildkit_{BUILDER}0"
    existing = subprocess.run(
        ["docker", "inspect", builder_container], capture_output=True, text=True
    )
    if existing.returncode == 0:
        state = json.loads(existing.stdout)[0]["State"]
        if state["Running"]:
            raise RuntimeError("BuildKit is already running. Inspect its owner before starting.")
        # Keep BuildKit's named cache volume, but give each build fresh cgroup counters.
        docker("rm", builder_container)
    docker("buildx", "inspect", BUILDER, "--bootstrap")
    try:
        docker(
            "update",
            "--memory=8g",
            "--memory-swap=8g",
            "--cpu-period=100000",
            "--cpu-quota=400000",
            "--pids-limit=512",
            builder_container,
        )
        info = json.loads(docker("inspect", builder_container))[0]
        write_json(
            report / "builder-limits.json",
            {
                "HostConfig": {
                    key: info["HostConfig"][key]
                    for key in ("Memory", "MemorySwap", "CpuPeriod", "CpuQuota", "PidsLimit")
                }
            },
        )
        status = logged(
            [
                "docker",
                "buildx",
                "build",
                "--builder",
                BUILDER,
                "--platform",
                "linux/arm64",
                "--build-arg",
                f"PYTHON_VERSION={version}",
                "--load",
                "--progress=plain",
                "-t",
                image,
                str(context),
            ],
            report,
            "build",
        )
        metrics = builder_memory(builder_container)
        write_json(
            report / "build-status.json",
            {
                "exit_code": status,
                "state": json.loads(docker("inspect", builder_container))[0]["State"],
                "cgroup": metrics,
            },
        )
        if status:
            raise RuntimeError(f"Dependency build failed ({status}); see {report}/build.log")
        if any(int(metrics["events"][name]) for name in ("oom", "oom_kill")):
            raise RuntimeError(f"Dependency build had an OOM event; see {report}/build-status.json")
    finally:
        state = json.loads(docker("inspect", builder_container))[0]["State"]
        if state["Paused"]:
            docker("unpause", builder_container)
        docker("buildx", "stop", BUILDER)
    return docker("image", "inspect", image, "--format", "{{.Id}}")


def main() -> int:
    global BUILDER
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docker-context",
        default="colima-ypricemagic",
        help="Explicit Docker context for this task",
    )
    parser.add_argument(
        "--revision",
        default="HEAD",
        help="Git revision, or worktree for an explicitly recorded development snapshot",
    )
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--image", help="Reuse this exact dependency image for comparisons")
    parser.add_argument("--python", choices=("3.11", "3.12", "3.13"), default="3.12")
    parser.add_argument(
        "--env-file", type=Path, help="Docker env file; never copied into reports or images"
    )
    parser.add_argument("--require-report", action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    # This affects only this supervisor and its children, never the user's
    # active Docker context or another task's Colima profile.
    os.environ["DOCKER_CONTEXT"] = args.docker_context
    BUILDER = (
        "ypricemagic-validation-" + hashlib.sha256(args.docker_context.encode()).hexdigest()[:12]
    )
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        command = ["make", "test"]
    if command == ["make", "test"]:
        args.require_report += ["pytest-summary.json", "compiled-modules.json"]
    report = args.report.resolve()
    report.mkdir(parents=True, exist_ok=False)
    metadata: dict[str, Any] = {
        "command": command,
        "docker_context": args.docker_context,
        "builder": BUILDER,
        "complete": False,
        "started_unix": time.time(),
    }
    harness = ROOT / "tools/validation"
    write_json(report / "run.json", metadata)
    # Docker's atomic name reservation covers all checkouts and both build/test phases.
    try:
        docker(
            "create",
            "--name",
            LOCK,
            "--label",
            "ypricemagic.validation=lock",
            "busybox:latest",
            "true",
        )
    except subprocess.CalledProcessError:
        raise RuntimeError(
            "Cannot reserve validation lock. Check Docker and the existing job; do not remove a live lock."
        ) from None
    created = False
    interrupted = False

    def stop(signum: int, _frame: object) -> None:
        nonlocal interrupted
        interrupted = True
        if created:
            subprocess.run(["docker", "stop", "--time", "15", CONTAINER], stdout=subprocess.DEVNULL)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        with tempfile.TemporaryDirectory(prefix="yprice-validation-") as scratch:
            work = Path(scratch)
            frozen_harness = work / "runner"
            write_json(
                report / "runner-files.json",
                freeze_files(
                    harness,
                    frozen_harness,
                    [path.name for path in sorted(harness.iterdir()) if path.is_file()],
                ),
            )
            workload = work / "workloads"
            write_json(
                report / "workload-files.json",
                freeze_files(
                    ROOT / "tests",
                    workload,
                    ("test_routing_scaling.py", "data/sushi-mainnet-topology.json"),
                ),
            )
            metadata.update(snapshot(args.source.resolve(), args.revision, work))
            metadata["image"] = (
                docker("image", "inspect", args.image, "--format", "{{.Id}}")
                if args.image
                else build(work / "source", report, args.python, frozen_harness)
            )
            write_json(report / "run.json", metadata)
            # Also stop a cached builder before tests. One heavy job at a time.
            if (
                subprocess.run(
                    ["docker", "buildx", "inspect", BUILDER],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ).returncode
                == 0
            ):
                docker("buildx", "stop", BUILDER)
            create = [
                "create",
                "--name",
                CONTAINER,
                "--platform=linux/arm64",
                "--init",
                "--memory=8g",
                "--memory-swap=8g",
                "--cpus=4",
                "--pids-limit=512",
                "--log-driver=json-file",
                "--log-opt=max-size=100m",
                "--log-opt=max-file=5",
                "--workdir=/work",
                "--env=BROWNIE_NETWORK=mainnet",
                "--env=BROWNIE_NETWORK_ID=mainnet",
                "--env=PYTEST_ADDOPTS=-p no:pytest_ethereum",
                "--env=PYTEST_PLUGINS=pytest_report",
                "--env=PYTHONPATH=/runner:/work",
                "--env=YPRICEMAGIC_SQLITE_PATH=/data/prices.sqlite",
                "--env=SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0",
                "--env=VALIDATION_REPORT=/reports",
                "--env=PYTHONUNBUFFERED=1",
            ]
            if args.env_file:
                create += ["--env-file", str(args.env_file.resolve())]
            create += [
                metadata["image"],
                "python",
                "/runner/container.py",
                "--report",
                "/reports",
                "--",
                *command,
            ]
            docker(*create)
            created = True
            docker("cp", str(work / "source") + "/.", CONTAINER + ":/work")
            docker("cp", str(frozen_harness), CONTAINER + ":/runner")
            # Use one recorded test workload against both pricing revisions.
            # Production source and each revision's tests remain unchanged.
            docker("cp", str(workload), CONTAINER + ":/runner/workloads")
            docker(
                "cp",
                CONTAINER + ":/opt/validation/dependencies.txt",
                str(report / "dependencies.txt"),
            )
            # /data belongs to this container and is never reused by another revision.
            # Create it in the isolated source before upload, through a copied directory.
            (work / "data").mkdir()
            docker("cp", str(work / "data"), CONTAINER + ":/data")
            (work / "reports").mkdir()
            docker("cp", str(work / "reports"), CONTAINER + ":/reports")
            metadata["exit_code"] = logged(
                ["docker", "start", "--attach", CONTAINER], report, "console"
            )
    except KeyboardInterrupt:
        metadata["interrupted"] = True
        metadata["exit_code"] = 130
    except Exception as exc:
        metadata["error"] = str(exc)
        raise
    finally:
        try:
            if created:
                state = json.loads(docker("inspect", CONTAINER))[0]
                if state["State"]["Running"]:
                    docker("stop", "--time", "15", CONTAINER)
                    state = json.loads(docker("inspect", CONTAINER))[0]
                docker("cp", CONTAINER + ":/reports/.", str(report))
                # Exclude environment variables (which can contain RPC credentials).
                write_json(
                    report / "container-state.json",
                    {
                        "State": state["State"],
                        "Image": state["Image"],
                        "HostConfig": {
                            key: state["HostConfig"][key]
                            for key in (
                                "Memory",
                                "MemorySwap",
                                "NanoCpus",
                                "PidsLimit",
                                "LogConfig",
                            )
                        },
                    },
                )
                metadata["oom_killed"] = state["State"]["OOMKilled"]
                missing = [
                    name
                    for name in ["command.json", *args.require_report]
                    if not (report / name).is_file()
                ]
                metadata["missing_reports"] = missing
                if not missing:
                    metrics = json.loads((report / "command.json").read_text())
                    events = dict(
                        line.split()
                        for line in metrics["cgroup_after"]["memory.events"].splitlines()
                    )
                    metadata["complete"] = not (
                        interrupted
                        or metrics["interrupted"]
                        or metadata["oom_killed"]
                        or int(events["oom"])
                        or int(events["oom_kill"])
                    )
                    metadata["below_memory_target"] = (
                        int(metrics["cgroup_after"]["memory.peak"]) < 7 * 1024**3
                    )
                docker("rm", CONTAINER)
        finally:
            metadata["elapsed_seconds"] = time.time() - metadata["started_unix"]
            write_json(report / "run.json", metadata)
            docker("rm", LOCK)
    print(json.dumps(metadata, indent=2))
    return int(metadata.get("exit_code", 1)) if metadata["complete"] else 125


if __name__ == "__main__":
    raise SystemExit(main())
