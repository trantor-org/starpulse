"""`ci/run.sh python-tests` writes a junit report only when `PYTEST_JUNIT` names one."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

RUN_SH = Path(__file__).resolve().parent / "run.sh"


@pytest.fixture
def uv_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A `uv` that records its arguments instead of running them."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "uv.log"
    uv = bin_dir / "uv"
    uv.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n')
    uv.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PYTEST_WORKERS", "0")
    monkeypatch.setenv("PYTEST_LOG", str(tmp_path / "pytest.log"))
    monkeypatch.setenv("PYTEST_TARGETS", "ci/test_select_tests.py")
    monkeypatch.delenv("PYTEST_JUNIT", raising=False)
    return log


def _pytest_command(log: Path) -> str:
    return next(line for line in log.read_text().splitlines() if line.startswith("run --no-sync pytest"))


def test_pytest_writes_a_junit_report_to_the_named_path(uv_log: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    junit = tmp_path / "junit.xml"
    monkeypatch.setenv("PYTEST_JUNIT", str(junit))
    subprocess.run(["bash", str(RUN_SH), "python-tests"], check=True, capture_output=True)
    assert f"--junitxml {junit} -o junit_family=xunit1" in _pytest_command(uv_log)


def test_pytest_writes_no_junit_report_without_a_path(uv_log: Path):
    subprocess.run(["bash", str(RUN_SH), "python-tests"], check=True, capture_output=True)
    assert "--junitxml" not in _pytest_command(uv_log)
