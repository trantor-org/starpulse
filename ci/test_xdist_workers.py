"""How many pytest-xdist workers a self-hosted runner gets, and that the pytest job uses that count."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from xdist_workers import (
    PEAK_WORKER_RSS_MIB,
    SLICE_MEMORY_HIGH_GIB,
    SLICE_WORKERS,
    slice_workers,
    workers_for,
    workers_for_file,
)

GIB = 1024**3
ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("limit", "workers"),
    [("max", 2), ("", 2), (str(1 * GIB), 1), (str(4 * GIB), 2), (str(6 * GIB), 2), (str(64 * GIB), 2)],
)
def test_a_runner_gets_one_worker_per_2_gib_of_its_memory_limit_up_to_two(limit, workers):
    assert workers_for(limit) == workers


def test_a_runner_with_no_cgroup_memory_file_gets_two(tmp_path):
    assert workers_for_file(tmp_path / "memory.max") == 2


def test_the_pytest_job_sizes_its_workers_before_it_runs_pytest():
    script = (ROOT / "ci/run.sh").read_text()
    body = script.split("cmd_python_tests() {")[1].split("\n}\n")[0]
    assert 'workers="${PYTEST_WORKERS:-$(uv run --no-sync python ci/xdist_workers.py $sizing)}"' in body
    assert 'addopts="-n $workers' in body
    assert "sizing=--slice" in body  # the build host's tests.slice budget, not a runner's memory limit
    assert "--dist worksteal" in body  # idle workers take queued tests, so a long file spreads over them
    assert "--dist worksteal -rA" in body  # the log names every test's outcome, not just totals
    assert body.index("ci/xdist_workers.py") < body.index("pytest ${PYTEST_TARGETS")


@pytest.mark.parametrize(
    ("peak_mib", "high_gib", "workers"),
    [(1024, 20, 20), (1500, 20, 13), (1024, 8, 8), (30_000, 20, 1)],
)
def test_the_slice_holds_as_many_workers_as_its_memory_high_allows_for_the_measured_peak(peak_mib, high_gib, workers):
    assert slice_workers(peak_mib, high_gib) == workers


def test_the_recorded_slice_worker_count_fits_the_recorded_peak_inside_memory_high():
    assert SLICE_WORKERS == slice_workers(PEAK_WORKER_RSS_MIB, SLICE_MEMORY_HIGH_GIB)
    assert SLICE_WORKERS * PEAK_WORKER_RSS_MIB <= SLICE_MEMORY_HIGH_GIB * 1024


def test_slice_flag_prints_the_slice_worker_count():
    ran = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("xdist_workers.py")), "--slice"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert ran.stdout.strip() == str(SLICE_WORKERS)


def test_the_pytest_session_runs_the_worker_count_its_caller_hands_it(tmp_path):
    """A caller that shares tests.slice with other CI runs passes its share as PYTEST_WORKERS; the session uses it, not the whole-slice count."""
    (tmp_path / "uv").write_text(f'#!/usr/bin/env bash\n[[ "$*" == *pytest* ]] && echo "$PYTEST_ADDOPTS" > {tmp_path}/addopts\nexit 0\n')
    (tmp_path / "uv").chmod(0o755)
    subprocess.run(
        [str(Path(__file__).with_name("run.sh")), "python-tests"],
        env={"PATH": f"{tmp_path}:/usr/bin:/bin", "PYTEST_WORKERS": "3", "PYTEST_LOG": str(tmp_path / "pytest.log")},
        capture_output=True,
        check=True,
    )
    assert (tmp_path / "addopts").read_text().split() == ["-n", "3", "--dist", "worksteal", "-rA"]
