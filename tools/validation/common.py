"""Small, bounded report writers shared by the host and container."""

import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import Any


def peak_rss_bytes() -> int:
    """Read Linux's KiB peak RSS without inventing metrics on another platform."""
    if sys.platform != "linux":
        raise RuntimeError("Run resource measurements inside the Linux validation container")
    import resource

    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024


def page_size() -> int:
    if sys.platform != "linux":
        raise RuntimeError("Run resource measurements inside the Linux validation container")
    import os

    return os.sysconf("SC_PAGE_SIZE")


def register_stack_dump() -> None:
    if sys.platform != "linux":
        raise RuntimeError("Run signal diagnostics inside the Linux validation container")
    import faulthandler
    import signal

    faulthandler.register(signal.SIGUSR1, all_threads=True)


def signal_process_group(pid: int, signum: int) -> None:
    if sys.platform != "linux":
        raise RuntimeError("Run process supervision inside the Linux validation container")
    import os

    os.killpg(pid, signum)


def configure_alarm(handler: Callable[[int, FrameType | None], object]) -> None:
    if sys.platform != "linux":
        raise RuntimeError("Run diagnostic deadlines inside the Linux validation container")
    import signal

    signal.signal(signal.SIGALRM, handler)


def set_alarm(seconds: int) -> int:
    if sys.platform != "linux":
        raise RuntimeError("Run diagnostic deadlines inside the Linux validation container")
    import signal

    return signal.alarm(seconds)


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


class ConsoleLog:
    """Retain five files, each at most 100 MiB; report discarded bytes."""

    def __init__(self, path: Path, limit: int = 100 * 1024**2, files: int = 5) -> None:
        if limit < 1 or files < 1:
            raise ValueError("log limits must be positive")
        self.path, self.limit, self.files = path, limit, files
        self.size = self.total = self.expired = self.rotations = 0
        self.stream = path.open("wb")

    def write(self, data: bytes) -> None:
        self.total += len(data)
        while data:
            if self.size == self.limit:
                self.stream.close()
                oldest = self.path.with_name(f"{self.path.name}.{self.files - 1}")
                if self.files == 1:
                    oldest = self.path
                if oldest.exists():
                    self.expired += oldest.stat().st_size
                    oldest.unlink()
                for index in range(self.files - 2, -1, -1):
                    source = (
                        self.path.with_name(f"{self.path.name}.{index}") if index else self.path
                    )
                    if source.exists():
                        source.replace(self.path.with_name(f"{self.path.name}.{index + 1}"))
                self.stream = self.path.open("wb")
                self.size = 0
                self.rotations += 1
            chunk, data = data[: self.limit - self.size], data[self.limit - self.size :]
            self.stream.write(chunk)
            self.stream.flush()
            self.size += len(chunk)

    def close(self) -> None:
        self.stream.close()
        write_json(
            self.path.with_suffix(".retention.json"),
            {
                "total_bytes": self.total,
                "expired_bytes": self.expired,
                "rotations": self.rotations,
                "file_limit_bytes": self.limit,
                "retained_files": self.files,
            },
        )
