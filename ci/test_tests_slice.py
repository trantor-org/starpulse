"""The `tests_slice` plugin moves a pytest run into `tests.slice` when the host has one, and does nothing when it has not."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import tests_slice

IN_SLICE = "0::/tests.slice/tests-pytest-1.scope\n"
OUTSIDE = "0::/user.slice/user-1000.slice/session-2.scope\n"


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A host with `tests.slice`, a `busctl`, and a pytest process outside the slice; `host.calls` records each command run.

    systemd moves the process after the call returns: it is in the slice once the run has napped `host.lag` times.
    """
    (tmp_path / "tests.slice").mkdir()
    own = tmp_path / "self-cgroup"
    own.write_text(OUTSIDE)
    monkeypatch.setattr(tests_slice, "CGROUP_ROOT", tmp_path)
    monkeypatch.setattr(tests_slice, "SELF_CGROUP", own)
    monkeypatch.setattr(tests_slice.shutil, "which", lambda name: f"/usr/bin/{name}")
    calls: list[list[str]] = []

    def run(command, **_):
        calls.append(command)
        return subprocess.CompletedProcess(command, host.returncode, stdout="", stderr=host.stderr)

    def sleep(_seconds):
        host.naps += 1
        if host.naps == host.lag:
            own.write_text(IN_SLICE)

    monkeypatch.setattr(tests_slice.subprocess, "run", run)
    # Swap the module's `time`, not `time.sleep`: the latter is process-wide and counts every other sleeper.
    monkeypatch.setattr(tests_slice, "time", SimpleNamespace(sleep=sleep))
    host = SimpleNamespace(calls=calls, own=own, root=tmp_path, returncode=0, stderr="", naps=0, lag=2)
    return host


def test_pytest_enters_the_slice_through_a_task_capped_scope_holding_its_own_pid(host):
    tests_slice.pytest_configure(SimpleNamespace())

    (command,) = host.calls
    assert command[0] == "busctl"
    assert command[command.index("StartTransientUnit") + 2 :] == [
        f"tests-pytest-{os.getpid()}.scope", "fail", "3",
        "PIDs", "au", "1", str(os.getpid()),
        "Slice", "s", "tests.slice",
        "TasksMax", "t", "2048",
        "0",
    ]  # fmt: skip


def test_pytest_waits_for_the_move_to_land_before_it_goes_on(host):
    tests_slice.pytest_configure(SimpleNamespace())

    assert host.naps == host.lag
    assert tests_slice.in_slice()


def test_a_scope_that_never_takes_the_process_warns_once(host, capsys):
    host.lag = None

    tests_slice.pytest_configure(SimpleNamespace())

    assert capsys.readouterr().err.count("tests.slice") == 1


def test_a_host_without_the_slice_runs_in_place_without_a_word(host, capsys):
    (host.root / "tests.slice").rmdir()

    tests_slice.pytest_configure(SimpleNamespace())

    assert host.calls == []
    assert capsys.readouterr().err == ""


def test_a_host_without_busctl_runs_in_place_without_a_word(host, monkeypatch, capsys):
    monkeypatch.setattr(tests_slice.shutil, "which", lambda name: None)

    tests_slice.pytest_configure(SimpleNamespace())

    assert host.calls == []
    assert capsys.readouterr().err == ""


def test_a_run_already_in_the_slice_stays_where_it_is(host):
    host.own.write_text(IN_SLICE)

    tests_slice.pytest_configure(SimpleNamespace())

    assert host.calls == []


def test_an_xdist_worker_stays_in_its_controllers_scope(host):
    tests_slice.pytest_configure(SimpleNamespace(workerinput={}))

    assert host.calls == []


def test_a_refused_scope_warns_once_and_lets_the_run_continue(host, capsys):
    host.returncode, host.stderr = 1, "Interactive authentication required.\n"

    tests_slice.pytest_configure(SimpleNamespace())

    err = capsys.readouterr().err
    assert err.count("tests.slice") == 1
    assert "Interactive authentication required." in err


class Container:
    """What testcontainers' `with_kwargs` does to a container: remember the keyword arguments and return itself."""

    def __init__(self):
        self.kwargs = {}

    def with_kwargs(self, **kwargs):
        self.kwargs |= kwargs
        return self


def test_a_container_joins_the_slice_when_the_host_has_one(host):
    container = Container()

    assert tests_slice.join_slice(container) is container
    assert container.kwargs == {"cgroup_parent": "tests.slice"}


def test_a_container_on_a_host_without_the_slice_is_left_as_it_was(host):
    (host.root / "tests.slice").rmdir()
    container = Container()

    assert tests_slice.join_slice(container) is container
    assert container.kwargs == {}


WRAPPER = Path(__file__).resolve().parents[1] / "starpulse/web/scripts/in-tests-slice.sh"
#: A `busctl` that records its arguments and answers with `$FAKE_BUSCTL_RC`.
#: systemd moves the process after the call returns, so the fake moves `$SELF_CGROUP`'s owner a moment later.
BUSCTL = """#!/bin/sh
echo "$@" >> "$BUSCTL_LOG"
if [ "${FAKE_BUSCTL_RC:-0}" != 0 ]; then
  echo "Interactive authentication required." >&2
  exit 1
fi
(sleep 0.3; echo "0::/tests.slice/x.scope" > "$SELF_CGROUP") >/dev/null 2>&1 &
"""


@pytest.fixture
def wrapper(tmp_path):
    """Run the vitest wrapper on a host with `tests.slice` and a fake `busctl`; `wrapper.log` is what busctl was asked."""
    (tmp_path / "bin").mkdir()
    busctl = tmp_path / "bin/busctl"
    busctl.write_text(BUSCTL)
    busctl.chmod(0o755)
    (tmp_path / "root/tests.slice").mkdir(parents=True)
    (tmp_path / "self-cgroup").write_text(OUTSIDE)
    log = tmp_path / "busctl.log"

    def run(*command, **env):
        env = {
            "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin",
            "CGROUP_ROOT": str(tmp_path / "root"),
            "SELF_CGROUP": str(tmp_path / "self-cgroup"),
            "BUSCTL_LOG": str(log),
            **env,
        }
        return subprocess.run([WRAPPER, *command], env=env, capture_output=True, text=True, check=False)

    run.log = lambda: log.read_text() if log.exists() else ""
    run.tmp = tmp_path
    return run


def test_the_wrapper_moves_the_process_that_becomes_the_command_into_the_slice(wrapper):
    done = wrapper("sh", "-c", "echo $$")

    assert f"PIDs au 1 {done.stdout.strip()} Slice s tests.slice" in wrapper.log()


def test_the_wrapper_starts_the_command_only_once_the_move_has_landed(wrapper):
    done = wrapper("cat", str(wrapper.tmp / "self-cgroup"))

    assert done.stdout == "0::/tests.slice/x.scope\n"


def test_the_wrapper_on_a_host_without_the_slice_runs_the_command_in_place(wrapper):
    (wrapper.tmp / "root/tests.slice").rmdir()

    done = wrapper("echo", "ran")

    assert (done.stdout, done.stderr, wrapper.log()) == ("ran\n", "", "")


def test_the_wrapper_leaves_a_command_already_in_the_slice_where_it_is(wrapper):
    (wrapper.tmp / "self-cgroup").write_text(IN_SLICE)

    done = wrapper("echo", "ran")

    assert (done.stdout, wrapper.log()) == ("ran\n", "")


def test_the_wrapper_warns_when_the_scope_is_refused_and_still_runs_the_command(wrapper):
    done = wrapper("sh", "-c", "echo ran; exit 3", FAKE_BUSCTL_RC="1")

    assert done.stdout == "ran\n"
    assert done.returncode == 3
    assert "not entering tests.slice: Interactive authentication required." in done.stderr
