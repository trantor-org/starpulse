"""Fail a slow test in the gate; name every slow or costly test, failing none, when `TEST_COST_REPORT=1` (the nightly).

A run without it is the gate (the `python` shards, a local run): a test whose wall time passes the gate's bound,
`SLOW_TEST_FAIL_SECONDS` (default three times the 5 s ceiling), fails at teardown unless it carries `@pytest.mark.slow`
or an `OVER_CEILING` entry, and the run prints no section, no annotation and no summary row and writes no report. The
bound keeps the gate's test window inside its budget (a 30 s budget for the gate's test window: no selected test over
~15 s) and sits above the ceiling because the gate's host is shared: one 0.7 s test took 9.4 s at a load of 4.6 per CPU.
The wall time the bound judges has the seconds the process's threads waited on a run queue taken off (`_waited`), so a host at its CPU cap fails the test that is slow, not the one that was kept off a CPU. The bound is stretched by the host's 1-minute load per CPU when that exceeds 1 (`gate_bound`); `SLOW_TEST_LOAD_SCALE=0` turns this off. The nightly names every test over the ceiling itself. A budget test that cannot fit is marked `nightly`, which the gate
deselects. With `TEST_COST_REPORT=1`, the flagged tests' node id, wall seconds, CPU seconds and peak-RSS growth in MB
are also written to the JSON file `TEST_COST_REPORT_PATH` (default `test-cost.json`) as `{"tests": [...]}`, empty when
nothing was flagged; ci/memray_flagged.py reruns exactly them.

Slow: setup, call and teardown together take more than `SLOW_TEST_SECONDS` (default 5) of wall time. Costly: they burn
more than `SLOW_TEST_CPU_SECONDS` (default 5) of CPU, this process plus the children it waited for. Wall time on a
saturated host measures the host; CPU seconds measure the test. Each phase's CPU seconds and growth of the worker's peak
RSS ride on its report, so under xdist they reach the controller, which alone prints. The nightly only reports. The
lists print at the end, worst first. Under GitHub Actions each flagged test is also a warning annotation on its `def`
line and a row in the job summary.

Containers a test starts run outside the process tree, so their CPU and memory are not counted.
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
FAIL_SECONDS = float(os.environ.get("SLOW_TEST_FAIL_SECONDS") or 3 * SECONDS)


def gate_bound(base: float, load1: float, cpus: int) -> float:
    """The gate's wall bound stretched by the host's 1-minute load per CPU: a shared runner at load 4.6/CPU runs a 15 s test in ~70 s."""
    return base * max(1.0, load1 / cpus)


def _bound() -> float:
    """`FAIL_SECONDS` stretched by host load unless `SLOW_TEST_LOAD_SCALE=0` (the plugin's own tests, whose bounds are tenths of a second)."""
    if os.environ.get("SLOW_TEST_LOAD_SCALE") == "0":
        return FAIL_SECONDS
    return gate_bound(FAIL_SECONDS, os.getloadavg()[0], os.cpu_count() or 1)


GAP = "CPU counts this process and the children it waited for; containers a test starts run outside it and are not counted."

# Tests at or over 4 s, a 1 s margin under the ceiling, when the gate's bound landed, each the slice that brings it under: the ceiling's grace, removed by that slice.
# Keyed `path::name`, without parameters or xdist group, so every case of a parametrized test shares its entry.
OVER_CEILING = {}

_cost: defaultdict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0])
_line: dict[str, tuple[str, int]] = {}
_wall: defaultdict[str, float] = defaultdict(float)
_failed: set[str] = set()
_waits: defaultdict[str, float] = defaultdict(float)
_last = [0.0, 0.0, 0.0]


def _now() -> tuple[float, float, float]:
    """CPU seconds so far (self and waited-for children), the process's peak RSS in MB and the seconds its live threads
    have spent runnable but not running."""
    own, kids = resource.getrusage(resource.RUSAGE_SELF), resource.getrusage(resource.RUSAGE_CHILDREN)
    cpu = own.ru_utime + own.ru_stime + kids.ru_utime + kids.ru_stime
    return cpu, own.ru_maxrss / 1024, _waited()


def _waited() -> float:
    """Seconds this process's live threads have waited on a run queue (`run_delay`, the second `schedstat` field): time
    the host kept a ready test off a CPU. Zero where the kernel keeps no schedstat."""
    total = 0
    for path in Path("/proc/self/task").glob("*/schedstat"):
        try:
            total += int(path.read_text().split()[1])
        except OSError, IndexError, ValueError:
            continue  # the thread exited between the listing and the read
    return total / 1e9


def pytest_runtest_logstart(nodeid, location):
    _last[:] = _now()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    cpu, peak, waited = _now()
    report.user_properties += [("cpu_s", cpu - _last[0]), ("peak_mb", max(0.0, peak - _last[1]))]
    _waits[item.nodeid] += max(0.0, waited - _last[2])  # a thread that exited since the last read took its wait with it
    _last[:] = cpu, peak, waited
    _wall[item.nodeid] += report.duration
    wall = _wall[item.nodeid] - _waits[item.nodeid]
    if report.failed:
        _failed.add(item.nodeid)
    exempt = item.get_closest_marker("slow") or f"{item.nodeid.split('::')[0]}::{item.originalname}" in OVER_CEILING
    over = call.when == "teardown" and wall > _bound() and not exempt
    if over and os.environ.get("TEST_COST_REPORT") != "1" and item.nodeid not in _failed:
        report.outcome = "failed"
        report.longrepr = f"{item.nodeid} took {wall:.1f} s once its CPU wait is taken off, over the gate's {FAIL_SECONDS:g} s bound: make it faster, mark it slow or nightly"
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
