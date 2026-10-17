"""Worker children forked from one preloaded process: their parent, exit codes, fallback and the code a reload forks."""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from starpulse._internal.server.closure import SELF, Reading
from starpulse._internal.server.supervisor import Supervisor
from starpulse._internal.server.zygote import Forker

NEW_MARKER = 'VALUE = "changed"\n'
ENTRY = "starpulse.tests.zygote_entry:main"
PREFIX = [sys.executable, "-m", "starpulse"]

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="forks from a preloaded process on Linux")


def _wait_for(check: Callable[[], object], timeout: float = 10.0) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := check():
            return found
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def _parent(pid: int) -> int:
    return int(subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout)


@pytest.fixture
def forker() -> Iterator[Forker]:
    made = Forker([], entry=ENTRY)
    yield made
    made.close()


def test_a_forked_child_is_not_a_child_of_serve_and_ends_when_it_is_terminated(forker: Forker) -> None:
    child = forker([*PREFIX, "hold"])

    assert child.poll() is None
    assert _parent(child.pid) not in (os.getpid(), 1)

    child.terminate()

    assert child.wait(10) == 0
    assert child.poll() == 0


def test_a_forked_child_reports_the_exit_code_its_entry_ended_with(forker: Forker) -> None:
    child = forker([*PREFIX, "exit", "3"])

    _wait_for(lambda: child.poll() is not None)

    assert child.poll() == 3


def test_waiting_for_a_child_that_keeps_running_times_out(forker: Forker) -> None:
    child = forker([*PREFIX, "hold"])

    with pytest.raises(subprocess.TimeoutExpired):
        child.wait(0.05)

    child.kill()
    assert child.wait(10) == -9


def test_a_command_that_is_not_a_starpulse_command_starts_with_subprocess(forker: Forker) -> None:
    child = forker([sys.executable, "-c", "import time; time.sleep(60)"])

    assert _parent(child.pid) == os.getpid()

    child.kill()
    child.wait()


def test_a_child_handed_a_listening_socket_starts_with_the_fallback_and_the_socket() -> None:
    started: list[tuple[object, ...]] = []
    handed = Forker([], entry=ENTRY, fallback=lambda *args: started.append(args) or "child")
    listening = socket.socket()

    child = handed([*PREFIX, "api"], listening)

    assert child == "child"
    assert started == [([*PREFIX, "api"], listening)]
    assert handed._current is None  # no preloaded process was started for it
    listening.close()


def test_a_preloaded_process_that_fails_leaves_the_child_to_subprocess_with_a_warning(caplog) -> None:
    broken = Forker(["no_such_module_to_preload"], entry=ENTRY)
    caplog.set_level(logging.WARNING)

    child = broken([sys.executable, "-c", "import time; time.sleep(60)"])
    command = broken([*PREFIX, "hold"])

    assert _parent(child.pid) == os.getpid()
    assert "preloaded process" in caplog.text
    assert _parent(command.pid) == os.getpid()
    for started in (child, command):
        started.kill()
        started.wait()
    broken.close()


def _read(code: Path) -> Callable[[str], Reading]:
    """A reading whose code is the hash of the `marker` module, the way the real reading hashes the installed files."""

    def read(name: str) -> Reading:
        digest = "serve" if name == SELF else hashlib.sha256(code.read_bytes()).hexdigest()
        return Reading(frozenset({("marker.py", digest)}), "restart", "live")

    return read


def test_a_reload_that_changes_a_preloaded_module_starts_the_replaced_child_on_the_new_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "marker.py"
    marker.write_text('VALUE = "one"\n')
    report = tmp_path / "report"
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(tmp_path), *filter(None, [os.environ.get("PYTHONPATH")])]))
    forker = Forker(["marker"], entry=ENTRY)
    supervisor = Supervisor(
        {"w": [*PREFIX, "report", str(report)]}, spawn=forker, retire=forker.retire, read=_read(marker), poll=60.0
    )
    supervisor.start()
    try:
        _wait_for(lambda: report.exists() and report.read_text())
        assert report.read_text() == "one"
        report.unlink()
        marker.write_text(NEW_MARKER)  # a different size: the bytecode cache keys on size and whole-second mtime

        assert supervisor.reload()["children"] == {"w": "replaced"}

        _wait_for(lambda: report.exists() and report.read_text())
        assert report.read_text() == "changed"
    finally:
        supervisor.stop()
        forker.close()
