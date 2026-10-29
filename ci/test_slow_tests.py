"""Flagging slow tests: a test whose setup, call and teardown together pass the threshold is named, never failed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CI = Path(__file__).resolve().parent

TESTS = "import time\n\ndef test_fast():\n    pass\n\n\ndef test_slow():\n    time.sleep(0.8)\n"


def run(tree: Path, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
    """Run pytest in `tree` with the `slow_tests` plugin on, a 0.6 s wall threshold, a 60 s gate bound and no GitHub Actions unless `env` sets it.

    Only the plugins the run needs load: autoloading every installed pytest plugin costs seconds per run.
    """
    plugins = ["-p", "xdist"] if "-n" in args else []
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "slow_tests", *plugins, "-p", "no:cacheprovider", *args],
        cwd=tree,
        env={
            **os.environ,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "SLOW_TEST_LOAD_SCALE": "0",
            "PYTHONPATH": str(CI),
            "SLOW_TEST_SECONDS": "0.6",
            "SLOW_TEST_CPU_SECONDS": "0.3",
            "SLOW_TEST_FAIL_SECONDS": "60",
            "PYTEST_ADDOPTS": "",
            "GITHUB_ACTIONS": "",
            "TEST_COST_REPORT": "1",
            "TEST_COST_REPORT_PATH": str(tree / "test-cost.json"),
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
        # Under pyproject's 120 s pytest-timeout a stalled run would hit its SIGALRM inside the worker's stdout write and
        # die with "reentrant call" (INTERNALERROR, TASK-7828). A bound here fails the test cleanly first.
        timeout=60,
    )


@pytest.mark.parametrize("workers", [[], ["-n", "1"]], ids=["serial", "xdist"])
def test_a_test_past_the_threshold_is_named_once_with_its_seconds_and_a_fast_one_is_not(tmp_path, workers):
    (tmp_path / "test_x.py").write_text(TESTS)

    done = run(tmp_path, *workers)

    assert done.returncode == 0, done.stdout + done.stderr
    flagged = [line for line in done.stdout.splitlines() if "test_x.py::" in line and line.lstrip()[0].isdigit()]
    assert [line.split()[-1] for line in flagged] == ["test_x.py::test_slow"]
    assert 0.8 <= float(flagged[0].split()[0].rstrip("s")) < 5
    assert "::warning" not in done.stdout


def test_under_github_actions_a_slow_test_is_annotated_on_its_line_and_added_to_the_job_summary(tmp_path):
    (tmp_path / "test_x.py").write_text(TESTS)
    summary = tmp_path / "summary.md"

    done = run(tmp_path, GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(summary))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "::warning file=test_x.py,line=7,title=Slow test::test_x.py::test_slow took " in done.stdout
    assert "test_fast" not in summary.read_text()
    assert "| `test_x.py::test_slow` |" in summary.read_text()
    assert "| Wall s | CPU s | Peak MB | Test |" in summary.read_text()


def test_a_run_with_no_slow_test_names_none_and_writes_an_empty_report(tmp_path):
    (tmp_path / "test_x.py").write_text("def test_fast():\n    pass\n")

    done = run(tmp_path, GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(tmp_path / "summary.md"))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "slow test" not in done.stdout.lower()
    assert not (tmp_path / "summary.md").exists()
    assert json.loads((tmp_path / "test-cost.json").read_text()) == {"tests": []}


BUSY = "import time\n\ndef test_busy():\n    end = time.process_time() + 0.4\n    while time.process_time() < end:\n        pass\n"


def listed(stdout: str, section: str, test: str) -> list[str]:
    """The fields of `test`'s line under the `section` heading of the run output, or [] when it is not listed there."""
    lines = stdout.split("=== ")
    body = next((chunk for chunk in lines if chunk.startswith(section)), "")
    return next((line.split() for line in body.splitlines() if line.endswith(test)), [])


@pytest.mark.parametrize("workers", [[], ["-n", "1"]], ids=["serial", "xdist"])
def test_a_cpu_bound_test_is_listed_with_its_cpu_seconds_and_a_sleeping_one_by_wall_time_only(tmp_path, workers):
    (tmp_path / "test_x.py").write_text(TESTS + "\n\n" + BUSY.split("\n\n", 1)[1])

    done = run(tmp_path, *workers)

    assert done.returncode == 0, done.stdout + done.stderr
    busy = listed(done.stdout, "costly tests", "test_x.py::test_busy")
    assert 0.4 <= float(busy[0].rstrip("s")) < 5, done.stdout
    assert listed(done.stdout, "costly tests", "test_x.py::test_slow") == []
    assert listed(done.stdout, "slow tests", "test_x.py::test_slow") != []
    assert "outside" in done.stdout


def test_the_job_summary_row_carries_wall_cpu_and_peak_memory_for_a_costly_test(tmp_path):
    (tmp_path / "test_x.py").write_text(BUSY)
    summary = tmp_path / "summary.md"

    done = run(tmp_path, GITHUB_ACTIONS="true", SLOW_TEST_SECONDS="60", GITHUB_STEP_SUMMARY=str(summary))

    assert done.returncode == 0, done.stdout + done.stderr
    row = next(line for line in summary.read_text().splitlines() if "test_busy" in line)
    wall, cpu, peak = (float(cell) for cell in row.split("|")[1:4])
    assert 0.4 <= cpu <= wall + 0.2 and peak >= 0
    assert "title=Costly test::test_x.py::test_busy took " in done.stdout
    assert "containers" in summary.read_text()


@pytest.mark.parametrize("workers", [[], ["-n", "1"]], ids=["serial", "xdist"])
def test_a_run_without_test_cost_report_prints_no_section_and_writes_no_report(tmp_path, workers):
    (tmp_path / "test_x.py").write_text(TESTS + "\n\n" + BUSY.split("\n\n", 1)[1])
    summary = tmp_path / "summary.md"

    done = run(tmp_path, *workers, TEST_COST_REPORT="", GITHUB_ACTIONS="true", GITHUB_STEP_SUMMARY=str(summary))

    assert done.returncode == 0, done.stdout + done.stderr
    assert "slow tests" not in done.stdout and "costly tests" not in done.stdout and "::warning" not in done.stdout
    assert not (tmp_path / "test-cost.json").exists() and not summary.exists()


@pytest.mark.parametrize("workers", [[], ["-n", "1"]], ids=["serial", "xdist"])
def test_without_test_cost_report_a_test_past_the_ceiling_fails_unless_exempt(tmp_path, workers):
    marked = "import pytest\n\n\n@pytest.mark.slow\ndef test_marked():\n    __import__('time').sleep(0.4)\n"
    listed = "\n\n@pytest.mark.parametrize('n', [1])\ndef test_listed(n):\n    __import__('time').sleep(0.4)\n"
    (tmp_path / "test_x.py").write_text(TESTS + "\n\n" + marked + listed)
    (tmp_path / "conftest.py").write_text(
        "import slow_tests\n\nslow_tests.OVER_CEILING['test_x.py::test_listed'] = 'TASK-0'\n"
    )

    done = run(tmp_path, *workers, "-rE", TEST_COST_REPORT="", SLOW_TEST_FAIL_SECONDS="0.3")

    assert done.returncode == 1, done.stdout + done.stderr
    assert "1 error" in done.stdout and "4 passed" in done.stdout, done.stdout
    assert "test_x.py::test_slow" in done.stdout and "over the gate's 0.3 s bound" in done.stdout
    assert not [line for line in done.stdout.splitlines() if line.startswith("ERROR") and "test_slow" not in line]


def test_without_test_cost_report_a_slow_test_that_already_failed_is_not_failed_again(tmp_path):
    slow_setup = (
        "import pytest\n\n\n@pytest.fixture\ndef broken():\n    __import__('time').sleep(0.4)\n    raise OSError\n"
    )
    (tmp_path / "test_x.py").write_text(slow_setup + "\n\ndef test_broken(broken):\n    pass\n")

    done = run(tmp_path, "-rE", TEST_COST_REPORT="", SLOW_TEST_FAIL_SECONDS="0.3")

    assert "1 error" in done.stdout and "bound" not in done.stdout, done.stdout


def test_without_test_cost_report_a_test_over_the_ceiling_but_under_three_times_it_passes(tmp_path):
    (tmp_path / "test_x.py").write_text(TESTS)

    done = run(tmp_path, TEST_COST_REPORT="", SLOW_TEST_FAIL_SECONDS="")

    assert done.returncode == 0, done.stdout + done.stderr


@pytest.mark.parametrize("workers", [[], ["-n", "1"]], ids=["serial", "xdist"])
def test_a_run_with_test_cost_report_writes_each_flagged_test_with_its_wall_cpu_and_peak_to_the_json_report(
    tmp_path, workers
):
    (tmp_path / "test_x.py").write_text(TESTS + "\n\n" + BUSY.split("\n\n", 1)[1])

    done = run(tmp_path, *workers)

    assert done.returncode == 0, done.stdout + done.stderr
    flagged = {row["nodeid"]: row for row in json.loads((tmp_path / "test-cost.json").read_text())["tests"]}
    assert set(flagged) == {"test_x.py::test_slow", "test_x.py::test_busy"}
    busy = flagged["test_x.py::test_busy"]
    assert set(busy) == {"nodeid", "wall_s", "cpu_s", "peak_mb"}
    assert 0.4 <= busy["cpu_s"] <= busy["wall_s"] + 0.2 and busy["peak_mb"] >= 0
    assert flagged["test_x.py::test_slow"]["cpu_s"] < 0.3


@pytest.mark.parametrize(
    ("load1", "cpus", "bound"),
    [(2.0, 4, 15.0), (4.0, 4, 15.0), (36.0, 36, 15.0), (167.0, 36, 15.0 * 167.0 / 36)],
)
def test_the_gate_bound_stretches_with_host_load_per_cpu_and_never_shrinks_below_the_base(load1, cpus, bound):
    sys.path.insert(0, str(CI))
    import slow_tests

    assert slow_tests.gate_bound(15.0, load1, cpus) == pytest.approx(bound)


STARVED = """\
import os
import subprocess
import sys
import time


def test_starved():
    cpu = min(os.sched_getaffinity(0))
    os.sched_setaffinity(0, {cpu})
    hogs = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(6)]
    try:
        started = time.process_time()
        while time.process_time() - started < 0.2:
            pass
    finally:
        for hog in hogs:
            hog.kill()
            hog.wait()
"""


def test_without_test_cost_report_a_test_starved_of_cpu_is_not_failed_for_the_wall_time_it_waited(tmp_path):
    """Six busy processes share the test's one CPU: its 0.2 CPU-s take over a second of wall, and the bound is 0.8 s."""
    (tmp_path / "test_x.py").write_text(STARVED)

    done = run(tmp_path, TEST_COST_REPORT="", SLOW_TEST_FAIL_SECONDS="0.8")

    assert done.returncode == 0, done.stdout + done.stderr
