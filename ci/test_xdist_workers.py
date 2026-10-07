"""How many pytest-xdist workers a validate runner gets, and that both pytest jobs use that count."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from xdist_workers import workers_for, workers_for_file

GIB = 1024**3
CI = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


@pytest.mark.parametrize(
    ("limit", "workers"),
    [("max", 4), ("", 4), (str(1 * GIB), 1), (str(4 * GIB), 2), (str(6 * GIB), 3), (str(64 * GIB), 4)],
)
def test_a_runner_gets_one_worker_per_2_gib_of_its_memory_limit_up_to_four(limit, workers):
    assert workers_for(limit) == workers


def test_a_runner_with_no_cgroup_memory_file_gets_four(tmp_path):
    assert workers_for_file(tmp_path / "memory.max") == 4


@pytest.mark.parametrize("name", ["python", "ic"])
def test_each_pytest_job_sizes_its_workers_before_it_runs_pytest(name):
    runs = [step.get("run", "") for step in yaml.safe_load(CI.read_text())["jobs"][name]["steps"]]
    sizing = next(i for i, run in enumerate(runs) if "ci/xdist_workers.py" in run)
    assert "PYTEST_ADDOPTS=-n" in runs[sizing]
    assert "--dist loadgroup" in runs[sizing]  # keeps each xdist_group (shared checkout state) on one worker
    assert sizing < next(i for i, run in enumerate(runs) if run.endswith("pytest $PYTEST_TARGETS"))
