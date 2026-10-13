"""Name every test whose setup, call and teardown together take more than `SLOW_TEST_SECONDS` (default 5).

The run never fails for it: CI runner timing is noisy. The list prints at the end of the run, slowest first. Under GitHub
Actions each slow test is also a warning annotation on its `def` line and a row in the job summary. Under xdist the
reports reach the controller, which alone prints.
"""

from __future__ import annotations

import os
from collections import defaultdict

SECONDS = float(os.environ.get("SLOW_TEST_SECONDS") or 5)

_took: defaultdict[str, float] = defaultdict(float)
_line: dict[str, tuple[str, int]] = {}


def pytest_runtest_logreport(report):
    _took[report.nodeid] += report.duration
    _line[report.nodeid] = (report.location[0], report.location[1] + 1)


def pytest_terminal_summary(terminalreporter, config):
    if hasattr(config, "workerinput"):
        return
    slow = sorted(((took, test) for test, took in _took.items() if took > SECONDS), reverse=True)
    if not slow:
        return
    terminalreporter.section(f"slow tests: over {SECONDS:g} s each, flagged, not failed")
    for took, test in slow:
        terminalreporter.write_line(f"{took:6.2f}s {test}")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for took, test in slow:
        path, line = _line[test]
        terminalreporter.write_line(f"::warning file={path},line={line},title=Slow test::{test} took {took:.1f} s")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as out:
            out.write(f"### Slow tests (over {SECONDS:g} s)\n\n| Seconds | Test |\n| ---: | --- |\n")
            out.writelines(f"| {took:.1f} | `{test}` |\n" for took, test in slow)
