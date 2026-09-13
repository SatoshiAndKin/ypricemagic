"""Small runner checks use the standard library and need no RPC or project imports."""

import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

from common import ConsoleLog


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


class ComparisonTests(unittest.TestCase):
    def test_dependency_drift_and_missing_reports_prevent_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("before", "after"):
                path = root / name
                path.mkdir()
                (path / "run.json").write_text(json.dumps({"complete": True, "image": "same"}))
                (path / "dependencies-after.txt").write_text(f"dependency=={name}\n")
                (path / "pytest-events.jsonl").write_text("")
                (path / "pytest-summary.json").write_text("{}")
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
            (root / "after/pytest-events.jsonl").unlink()
            subprocess.run(command, check=True)
            report = json.loads((root / "result.json").read_text())
            self.assertFalse(report["comparable"])
            self.assertEqual(report["missing_reports"], [str(root / "after/pytest-events.jsonl")])


if __name__ == "__main__":
    unittest.main()
