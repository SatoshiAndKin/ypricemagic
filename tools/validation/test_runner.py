"""Small runner checks use the standard library and need no RPC or project imports."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

from common import ConsoleLog
import run


class LogTests(unittest.TestCase):
    def test_rotation_retains_exact_tail_and_discloses_expired_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "console.log"
            log = ConsoleLog(path, limit=10, files=5)
            content = bytes(range(87))
            for chunk in (content[:3], content[3:60], content[60:]):
                log.write(chunk)
            log.close()
            kept = (
                b"".join(path.with_name(f"console.log.{i}").read_bytes() for i in range(4, 0, -1))
                + path.read_bytes()
            )
            self.assertEqual(kept, content[40:])
            result = json.loads(path.with_suffix(".retention.json").read_text())
            self.assertEqual(result["expired_bytes"], 40)
            self.assertEqual(result["total_bytes"], 87)
            self.assertEqual(result["rotations"], 8)
            self.assertTrue(
                all(p.stat().st_size <= 10 for p in Path(directory).glob("console.log*"))
            )

    def test_single_file_rotation_and_invalid_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "console.log"
            log = ConsoleLog(path, limit=4, files=1)
            log.write(b"123456789")
            log.close()
            self.assertEqual(path.read_bytes(), b"9")
            self.assertEqual(
                json.loads(path.with_suffix(".retention.json").read_text())["expired_bytes"], 8
            )
            with self.assertRaises(ValueError):
                ConsoleLog(path, limit=0)


class BuildTests(unittest.TestCase):
    def test_frozen_helpers_execute_recorded_content_after_checkout_edits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, frozen = root / "source", root / "frozen"
            source.mkdir()
            original = b"print('original')\n"
            (source / "probe.py").write_bytes(original)
            hashes = run.freeze_files(source, frozen, ["probe.py"])
            (source / "probe.py").write_text("raise RuntimeError('checkout changed')\n")
            (source / "later.py").write_text("raise RuntimeError('added during build')\n")
            self.assertEqual(
                subprocess.check_output([sys.executable, str(frozen / "probe.py")], text=True),
                "original\n",
            )
            self.assertEqual(hashes, {"probe.py": hashlib.sha256(original).hexdigest()})
            self.assertFalse((frozen / "later.py").exists())

    def test_build_failures_preserve_evidence_and_stop_before_image_use(self) -> None:
        for scenario in (
            "worker_oom",
            "interrupted_build",
            "interrupted_bootstrap",
            "interrupted_bootstrap_absent",
            "daemon_oom",
            "missing_metrics",
        ):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source, report = root / "source", root / "report"
                source.mkdir()
                report.mkdir()
                for name in ("requirements.txt", "requirements-dev.txt"):
                    (source / name).write_text("")
                (source / "pyproject.toml").write_text("[build-system]\nrequires=[]\n")
                inspection = json.dumps(
                    [
                        {
                            "State": {"Paused": False, "OOMKilled": scenario == "daemon_oom"},
                            "HostConfig": {
                                "Memory": 8 * 1024**3,
                                "MemorySwap": 8 * 1024**3,
                                "CpuPeriod": 100000,
                                "CpuQuota": 400000,
                                "PidsLimit": 512,
                            },
                        }
                    ]
                )

                def inspect(*command: str, scenario: str = scenario) -> str:
                    if (
                        scenario.startswith("interrupted_bootstrap")
                        and command[-1] == "--bootstrap"
                    ):
                        raise KeyboardInterrupt
                    if scenario == "interrupted_bootstrap_absent" and command[0] == "inspect":
                        raise subprocess.CalledProcessError(1, ["docker", *command])
                    return inspection

                unreadable = scenario in ("daemon_oom", "missing_metrics")
                status = 1 if scenario == "daemon_oom" else 0
                with (
                    patch.object(
                        subprocess, "run", return_value=subprocess.CompletedProcess([], 1)
                    ),
                    patch.object(run, "docker", side_effect=inspect) as docker,
                    patch.object(
                        run,
                        "logged",
                        return_value=status,
                        side_effect=KeyboardInterrupt if scenario == "interrupted_build" else None,
                    ),
                    patch.object(
                        run,
                        "builder_memory",
                        side_effect=(
                            subprocess.CalledProcessError(1, ["docker", "exec"])
                            if unreadable
                            else None
                        ),
                        return_value={
                            "peak_bytes": 8 * 1024**3,
                            "events": {
                                "oom": str(int(scenario == "worker_oom")),
                                "oom_kill": str(int(scenario == "worker_oom")),
                            },
                        },
                    ),
                ):
                    expected = (
                        KeyboardInterrupt if scenario.startswith("interrupted") else RuntimeError
                    )
                    with self.assertRaises(expected) as raised:
                        run.build(source, report, "3.12", Path(run.__file__).parent)
                    docker.assert_any_call("buildx", "stop", run.BUILDER)
                recorded = json.loads((report / "build-status.json").read_text())
                self.assertEqual(
                    recorded["exit_code"], None if scenario.startswith("interrupted") else status
                )
                if scenario == "interrupted_bootstrap_absent":
                    self.assertIsNone(recorded["state"])
                    self.assertIsNone(recorded["cgroup"])
                    self.assertIn("state_error", recorded)
                else:
                    self.assertEqual(recorded["state"]["OOMKilled"], scenario == "daemon_oom")
                    if unreadable:
                        self.assertIsNone(recorded["cgroup"])
                        self.assertIn("cgroup_error", recorded)
                    else:
                        self.assertEqual(recorded["cgroup"]["peak_bytes"], 8 * 1024**3)
                        self.assertEqual(
                            recorded["cgroup"]["events"]["oom_kill"],
                            str(int(scenario == "worker_oom")),
                        )
                if scenario.endswith("oom"):
                    self.assertIn("OOM event", str(raised.exception))
                elif scenario == "missing_metrics":
                    self.assertIn("Missing build cgroup metrics", str(raised.exception))


class ComparisonTests(unittest.TestCase):
    def test_dependency_drift_and_missing_reports_prevent_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("before", "after"):
                path = root / name
                path.mkdir()
                (path / "run.json").write_text(json.dumps({"complete": True, "image": "same"}))
                (path / "dependencies-after.txt").write_text(f"dependency=={name}\n")
                (path / "pytest-events.jsonl").write_text(
                    "\n".join(
                        json.dumps(row)
                        for row in (
                            {"phase": "call", "outcome": "passed", "test": "first"},
                            {"phase": "call", "outcome": "passed", "test": "second"},
                            {"phase": "sessionfinish", "exit_code": 0},
                        )
                    )
                    + "\n"
                )
                (path / "pytest-summary.json").write_text(
                    json.dumps({"exit_code": 0, "collected": 2, "counts": {"call:passed": 2}})
                )
            command = [
                sys.executable,
                str(Path(__file__).with_name("compare.py")),
                str(root / "before"),
                str(root / "after"),
                "--output",
                str(root / "result.json"),
            ]
            subprocess.run(command, check=True)
            report = json.loads((root / "result.json").read_text())
            self.assertFalse(report["comparable"])
            self.assertFalse(report["dependencies_equal"])
            (root / "after/dependencies-after.txt").write_text("dependency==before\n")
            subprocess.run(command, check=True)
            self.assertTrue(json.loads((root / "result.json").read_text())["comparable"])
            events = root / "after/pytest-events.jsonl"
            original = events.read_text()
            events.write_text(original.replace('"second"', '"third"'))
            subprocess.run(command, check=True)
            report = json.loads((root / "result.json").read_text())
            self.assertEqual(report["added_test_cases"], ["third"])
            self.assertEqual(report["removed_test_cases"], ["second"])
            self.assertFalse(report["coverage_preserved"])
            events.write_text(original.replace('"second"', '"first"'))
            subprocess.run(command, check=True)
            self.assertFalse(
                json.loads((root / "result.json").read_text())["test_reports_complete"]
            )
            events.write_text(original)
            # A process can hang after all tests report. Its test outcomes stay
            # comparable, but that must never turn incomplete execution green.
            (root / "before/run.json").write_text(json.dumps({"complete": False, "image": "same"}))
            subprocess.run(command, check=True)
            report = json.loads((root / "result.json").read_text())
            self.assertTrue(report["failures_comparable"])
            self.assertFalse(report["comparable"])
            (root / "after/pytest-summary.json").write_text(
                json.dumps({"exit_code": 1, "collected": 2, "counts": {"call:passed": 1}})
            )
            subprocess.run(command, check=True)
            report = json.loads((root / "result.json").read_text())
            self.assertFalse(report["failures_comparable"])
            self.assertFalse(report["test_reports_complete"])
            (root / "after/pytest-events.jsonl").unlink()
            subprocess.run(command, check=True)
            report = json.loads((root / "result.json").read_text())
            self.assertFalse(report["comparable"])
            self.assertEqual(report["missing_reports"], [str(root / "after/pytest-events.jsonl")])
            self.assertTrue(report["dependencies_equal"])


if __name__ == "__main__":
    unittest.main()
