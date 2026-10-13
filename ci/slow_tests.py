"""Name every test that is slow or costly, never fail one, but only when `TEST_COST_REPORT=1` (the nightly full suite).

A run without it prints no section, no annotation and no summary row and writes no report. With it, the flagged tests'
node id, wall seconds, CPU seconds and peak-RSS growth in MB are also written to the JSON file `TEST_COST_REPORT_PATH`
(default `test-cost.json`) as `{"tests": [...]}`, empty when nothing was flagged; ci/test_cost_memray.py reruns exactly them.

Slow: setup, call and teardown together take more than `SLOW_TEST_SECONDS` (default 5) of wall time. Costly: they burn
more than `SLOW_TEST_CPU_SECONDS` (default 5) of CPU, this process plus the children it waited for. Wall time on a
saturated host measures the host; CPU seconds measure the test. Each phase's CPU seconds and growth of the worker's peak
RSS ride on its report, so under xdist they reach the controller, which alone prints. CI runner timing is noisy, so a
flagged test never fails the run. The lists print at the end, worst first. Under GitHub Actions each flagged test is also a
warning annotation on its `def` line and a row in the job summary.

Containers a test starts (Postgres, mock-oauth2) run outside the process tree, so their CPU and memory are not counted.
"""

from __future__ import annotations

import json
import os
import resource
from collections import defaultdict
from pathlib import Path

import pytest

SECONDS = float(os.environ.get("SLOW_TEST_SECONDS") or 5)
CPU_SECONDS = float(os.environ.get("SLOW_TEST_CPU_SECONDS") or 5)
GAP = "CPU counts this process and the children it waited for; containers a test starts (Postgres, mock-oauth2) run outside it and are not counted."

_cost: defaultdict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
_line: dict[str, tuple[str, int]] = {}
_last = [0.0, 0.0]


def _now() -> tuple[float, float]:
    """CPU seconds so far (self and waited-for children) and the process's peak RSS in MB."""
    own, kids = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = own.ru_utime + own.ru_stime + kids.ru_utime + kids.ru_stime
    return cpu, own.ru_maxrss / 1024


def pytest_runtest_logstart(nodeid, location):
    _last[:] = _now()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    cpu, peak = _now()
    report.user_properties += [("cpu_s", cpu - _last[0]), ("peak_mb", max(0.0, peak - _last[1]))]
    _last[:] = cpu, peak
    return report


def pytest_runtest_logreport(report):
    props = dict(report.user_properties)
    total = _cost[report.nodeid]
    total[0] += report.duration
    total[1] += props.get("cpu_s", 0.0)
    total[2] += props.get("peak_mb", 0.0)
    _line[report.nodeid] = (report.location[0], report.location[1] + 1)


def pytest_terminal_summary(terminalreporter, config):
    if hasattr(config, "workerinput") or os.environ.get("TEST_COST_REPORT") != "1":
        return
    slow = sorted(((wall, test) for test, (wall, _, _) in _cost.items() if wall > SECONDS), reverse=True)
    costly = sorted(((cpu, test) for test, (_, cpu, _) in _cost.items() if cpu > CPU_SECONDS), reverse=True)
    flagged = sorted({test for _, test in slow} | {test for _, test in costly}, key=lambda t: -_cost[t][0])
    rows = [dict(zip(("nodeid", "wall_s", "cpu_s", "peak_mb"), (test, *_cost[test]), strict=True)) for test in flagged]
    Path(os.environ.get("TEST_COST_REPORT_PATH") or "test-cost.json").write_text(json.dumps({"tests": rows}, indent=2))
    if not flagged:
        return
    if slow:
        terminalreporter.section(f"slow tests: over {SECONDS:g} s each, flagged, not failed")
        for wall, test in slow:
            terminalreporter.write_line(f"{wall:6.2f}s {test}")
    if costly:
        terminalreporter.section(f"costly tests: over {CPU_SECONDS:g} CPU-s each, flagged, not failed")
        for cpu, test in costly:
            terminalreporter.write_line(f"{cpu:6.2f}s {_cost[test][2]:6.1f} MB {test}")
    terminalreporter.write_line(GAP)
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for test in flagged:
        wall, cpu, peak = _cost[test]
        path, line = _line[test]
        title = "Slow test" if wall > SECONDS else "Costly test"
        message = f"{test} took {wall:.1f} s, {cpu:.1f} CPU-s, +{peak:.0f} MB peak"
        terminalreporter.write_line(f"::warning file={path},line={line},title={title}::{message}")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as out:
            out.write(
                f"### Slow and costly tests (over {SECONDS:g} s or {CPU_SECONDS:g} CPU-s)\n\n"
                "| Wall s | CPU s | Peak MB | Test |\n| ---: | ---: | ---: | --- |\n"
            )
            out.writelines(f"| {_cost[t][0]:.1f} | {_cost[t][1]:.1f} | {_cost[t][2]:.0f} | `{t}` |\n" for t in flagged)
            out.write(f"\n{GAP}\n")
