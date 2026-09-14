"""Exercise the configured pytest deadline and cooperative concurrency in Docker."""

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


class TimeoutTests(unittest.TestCase):
    def test_missing_plugin_rejects_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_bytes(
                (Path(__file__).resolve().parents[2] / "pyproject.toml").read_bytes()
            )
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_must_not_run.py").write_text(
                "from pathlib import Path\n\ndef test_must_not_run():\n"
                "    Path('unexpected.txt').write_text('ran')\n"
            )
            result = subprocess.run(
                [sys.executable, "-m", "pytest"],
                cwd=root,
                env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
                capture_output=True,
                text=True,
                timeout=15,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 4, output)
            self.assertIn("Missing required plugins: pytest-timeout", output)
            self.assertFalse((root / "unexpected.txt").exists())

    def test_sync_timeout_releases_fixture_and_keeps_cooperative_concurrency(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pyproject.toml").write_bytes(
                (Path(__file__).resolve().parents[2] / "pyproject.toml").read_bytes()
            )
            tests = root / "tests"
            tests.mkdir()
            (tests / "conftest.py").write_text(
                textwrap.dedent(
                    """
                    import asyncio
                    import json
                    from pathlib import Path
                    import pytest

                    @pytest.fixture(scope="session")
                    def barrier():
                        return {"entered": set(), "ready": asyncio.Event()}

                    @pytest.fixture
                    def owned_state():
                        path = Path("lifecycle.json")
                        path.write_text(json.dumps(["setup"]))
                        yield path
                        path.write_text(json.dumps(json.loads(path.read_text()) + ["teardown"]))
                    """
                )
            )
            (tests / "test_deadline.py").write_text(
                textwrap.dedent(
                    """
                    import asyncio
                    import json
                    import time
                    from pathlib import Path
                    import pytest

                    @pytest.mark.asyncio_cooperative
                    @pytest.mark.parametrize("number", range(100))
                    async def test_cooperative_barrier(number, barrier):
                        barrier["entered"].add(number)
                        if len(barrier["entered"]) == 100:
                            barrier["ready"].set()
                        await asyncio.wait_for(barrier["ready"].wait(), 5)
                        assert barrier["entered"] == set(range(100))

                    @pytest.mark.timeout(1)
                    def test_sync_deadline(owned_state, request):
                        assert float(request.config.getini("timeout")) == 600
                        try:
                            time.sleep(30)
                        finally:
                            owned_state.write_text(json.dumps(["setup", "finally"]))

                    def test_after_timeout():
                        path = Path("lifecycle.json")
                        assert json.loads(path.read_text()) == ["setup", "finally", "teardown"]
                        path.write_text(json.dumps(["setup", "finally", "teardown", "next"]))
                    """
                )
            )
            result = subprocess.run(
                [sys.executable, "-m", "pytest"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=15,
            )
            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, output)
            self.assertIn("Failed: Timeout >1.0s", output)
            self.assertIn("1 failed, 101 passed", output)
            self.assertEqual(
                json.loads((root / "lifecycle.json").read_text()),
                ["setup", "finally", "teardown", "next"],
            )


if __name__ == "__main__":
    unittest.main()
