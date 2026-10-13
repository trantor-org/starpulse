"""Flagging slow tests: a test whose setup, call and teardown together pass the threshold is named, never failed."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

CI = Path(__file__).resolve().parent

TESTS = "import time\n\ndef test_fast():\n    pass\n\n\ndef test_slow():\n    time.sleep(0.5)\n"


def run(tree: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run pytest in `tree` with the `slow_tests` plugin, a 0.3 s threshold and no GitHub Actions unless `env` sets it."""
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "slow_tests", "-p", "no:cacheprovider", *args],
        cwd=tree,
        env={**os.environ, "PYTHONPATH": str(CI), "SLOW_TEST_SECONDS": "0.3", "GITHUB_ACTIONS": "", **env},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("workers", [[], ["-n", "2"]], ids=["serial", "xdist"])
def test_a_test_past_the_threshold_is_named_once_with_its_seconds_and_a_fast_one_is_not(tmp_path, workers):
    (tmp_path / "test_x.py").write_text(TESTS)

    done = run(tmp_path, *workers)

    assert done.returncode == 0, done.stdout + done.stderr
    flagged = [line for line in done.stdout.splitlines() if "test_x.py::" in line and line.lstrip()[0].isdigit()]
    assert [line.split()[-1] for line in flagged] == ["test_x.py::test_slow"]
    assert 0.5 <= float(flagged[0].split()[0].rstrip("s")) < 5
    assert "::warning" not in done.stdout


def test_under_github_actions_a_slow_test_is_annotated_on_its_line_and_added_to_the_job_summary(tmp_path):
    (tmp_path / "test_x.py").write_text(TESTS)
    summary = tmp_path / "summary.md"

    done = run(tmp_path, GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(summary))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "::warning file=test_x.py,line=7,title=Slow test::test_x.py::test_slow took " in done.stdout
    assert "test_fast" not in summary.read_text()
    assert "| `test_x.py::test_slow` |" in summary.read_text()


def test_a_run_with_no_slow_test_names_none(tmp_path):
    (tmp_path / "test_x.py").write_text("def test_fast():\n    pass\n")

    done = run(tmp_path, GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "slow test" not in done.stdout.lower()
    assert not (tmp_path / "summary.md").exists()
