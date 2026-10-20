"""How many pytest-xdist workers a self-hosted runner gets, and that the pytest job uses that count."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from xdist_workers import (
    PEAK_WORKER_RSS_MIB,
    SLICE_MEMORY_HIGH_GIB,
    SLICE_WORKERS,
    slice_workers,
    workers_for,
    workers_for_file,
)

GIB = 1024**3
CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


@pytest.mark.parametrize(
    ("limit", "workers"),
    [("max", 2), ("", 2), (str(1 * GIB), 1), (str(4 * GIB), 2), (str(6 * GIB), 2), (str(64 * GIB), 2)],
)
def test_a_runner_gets_one_worker_per_2_gib_of_its_memory_limit_up_to_two(limit, workers):
    assert workers_for(limit) == workers


def test_a_runner_with_no_cgroup_memory_file_gets_two(tmp_path):
    assert workers_for_file(tmp_path / "memory.max") == 2


def test_the_pytest_job_sizes_its_workers_before_it_runs_pytest():
    runs = [step.get("run", "") for step in yaml.safe_load(CI.read_text())["jobs"]["python-shard"]["steps"]]
    sizing = next(i for i, run in enumerate(runs) if "ci/xdist_workers.py" in run)
    assert "PYTEST_ADDOPTS=-n" in runs[sizing]
    assert "--dist worksteal" in runs[sizing]  # idle workers take queued tests, so a long file spreads over them
    assert sizing < next(i for i, run in enumerate(runs) if "pytest $PYTEST_TARGETS" in run)


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
