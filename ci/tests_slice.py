"""Run pytest inside the host's `tests.slice` cgroup when it has one.

A host that budgets test CPU declares a systemd slice named `tests.slice`, and lets its test users start transient
`tests-*.scope` units. At configure time, before xdist forks any worker, this plugin asks systemd to put the pytest process
in such a scope; its workers and everything they fork inherit the cgroup. A host without the slice (a laptop, a CI farm
slot) or without `busctl` runs the test where it was started, silently. A host whose systemd refuses the scope prints one
line to stderr and runs the test where it was started too.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SLICE = "tests.slice"
MOVE_SECONDS = 2.0
# A fork storm in one test run stops here instead of exhausting the host: a run peaks near 550 tasks.
SCOPE_TASKS_MAX = 2048
CGROUP_ROOT = Path("/sys/fs/cgroup")
SELF_CGROUP = Path("/proc/self/cgroup")
# `task-<N>` in the working directory (a task worktree is `task-<N>-*`); a word that merely ends in "task" is not one.
TASK_DIRECTORY = re.compile(r"(?<![A-Za-z0-9])task-(\d+)(?!\d)", re.IGNORECASE)


def slice_exists() -> bool:
    return (CGROUP_ROOT / SLICE).is_dir()


def in_slice() -> bool:
    return f"/{SLICE}/" in SELF_CGROUP.read_text()


def task_tag() -> str:
    """`t<N>-` when the working directory names task N, else empty: it puts the task in the scope name for CPU attribution."""
    found = TASK_DIRECTORY.search(str(Path.cwd()))
    return f"t{found[1]}-" if found else ""


def start_scope(pid: int) -> subprocess.CompletedProcess[str]:
    """Ask the system manager for a task-capped `tests-pytest-[t<N>-]<pid>.scope` under the slice holding `pid` (StartTransientUnit)."""
    properties = ["PIDs", "au", "1", str(pid), "Slice", "s", SLICE, "TasksMax", "t", str(SCOPE_TASKS_MAX)]
    command = ["busctl", "call", "org.freedesktop.systemd1", "/org/freedesktop/systemd1"]
    command += ["org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))"]
    command += [f"tests-pytest-{task_tag()}{pid}.scope", "fail", "3", *properties, "0"]
    return subprocess.run(command, capture_output=True, text=True, check=False)


def wait_until_in_slice() -> bool:
    """Whether the process is in the slice within `MOVE_SECONDS`: systemd moves it after `StartTransientUnit` returns."""
    for _ in range(round(MOVE_SECONDS / 0.1)):
        if in_slice():
            return True
        time.sleep(0.1)
    return in_slice()


def pytest_configure(config: pytest.Config) -> None:
    if hasattr(config, "workerinput") or not shutil.which("busctl") or not slice_exists() or in_slice():
        return
    done = start_scope(os.getpid())
    if done.returncode:
        print(f"warning: not entering {SLICE}: {done.stderr.strip()}", file=sys.stderr)
    elif not wait_until_in_slice():
        print(f"warning: not entering {SLICE}: the scope never took the process", file=sys.stderr)
