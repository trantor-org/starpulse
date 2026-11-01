"""Worker children forked from one preloaded process: their parent, exit codes, fallback and the code a reload forks."""

from __future__ import annotations

import hashlib
import logging
import os
import resource
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from starpulse.runtime import zygote
from starpulse.runtime.closure import SELF, Reading
from starpulse.runtime.supervisor import Supervisor
from starpulse.runtime.zygote import Forker

NEW_MARKER = 'VALUE = "changed"\n'
ENTRY = "tests.zygote_entry:main"
PREFIX = [sys.executable, "-m", "starpulse"]

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="forks from a preloaded process on Linux")


def _wait_for(check: Callable[[], object], timeout: float = 10.0) -> object:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if found := check():
            return found
        time.sleep(0.02)
    raise AssertionError("condition not reached")


def _terminable(child: Any) -> Any:
    """Wait until the child's `hold` caught `SIGTERM`: sent before, it ends the child by the signal (-15), not with 0."""

    _wait_for(lambda: _term_caught(Path(f"/proc/{child.pid}/status").read_text()))
    return child


def _term_caught(status: str) -> bool:
    mask = next(line for line in status.splitlines() if line.startswith("SigCgt:"))
    return bool(int(mask.split()[1], 16) >> (signal.SIGTERM - 1) & 1)


def _parent(pid: int) -> int:
    return int(subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout)


@pytest.fixture(autouse=True)
def preloaded_answers_however_loaded_the_host_is(monkeypatch: pytest.MonkeyPatch) -> None:
    """A starved host can keep the preloaded process past `_ANSWER_S`, and the `Forker` then starts the child with
    `subprocess` (`starpulse hold`, which never catches `SIGTERM` in time): these tests judge forks, not that timeout."""
    monkeypatch.setattr(zygote, "_ANSWER_S", 3600.0)


@pytest.fixture
def forker() -> Iterator[Forker]:
    made = Forker([], entry=ENTRY)
    yield made
    made.close()


@pytest.fixture
def fds_past_select_limit() -> Iterator[None]:
    """Hold every descriptor below 1100, as a long single-process run does, so the next one is past FD_SETSIZE."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(max(soft, 1200), hard), hard))
    held: list[int] = []
    try:
        while (fd := os.dup(0)) < 1100:
            held.append(fd)
        held.append(fd)
        yield
    finally:
        for fd in held:
            os.close(fd)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def test_the_zygote_serves_a_fork_when_its_socket_is_past_the_select_limit(fds_past_select_limit: None) -> None:
    made = Forker([], entry=ENTRY)
    try:
        child = made([*PREFIX, "hold"])
        assert _parent(child.pid) != os.getpid()
    finally:
        made.close()


def test_a_forked_child_is_not_a_child_of_serve_and_ends_when_it_is_terminated(forker: Forker) -> None:
    child = _terminable(forker([*PREFIX, "hold"]))

    assert child.poll() is None
    assert _parent(child.pid) not in (os.getpid(), 1)

    child.terminate()

    assert child.wait(10) == 0
    assert child.poll() == 0


def test_a_preloaded_process_serve_forked_itself_forks_children_and_ends_with_the_forker() -> None:
    forked = Forker([], entry=ENTRY)
    forked.start(forked=True)
    preloaded = forked._current.proc
    try:
        child = _terminable(forked([*PREFIX, "hold"]))

        assert _parent(child.pid) == preloaded.pid
        assert preloaded.poll() is None
        child.terminate()
        assert child.wait(10) == 0
    finally:
        forked.close()
    assert preloaded.poll() is not None


def test_a_preloaded_process_serve_forked_itself_drops_the_term_handler_serve_had() -> None:
    previous = signal.signal(signal.SIGTERM, lambda *_: None)
    forked = Forker([], entry=ENTRY)
    try:
        forked.start(forked=True)
        status = Path(f"/proc/{forked._current.proc.pid}/status")

        _wait_for(lambda: not _term_caught(status.read_text()), timeout=3)
    finally:
        forked.close()
        signal.signal(signal.SIGTERM, previous)


def test_a_forked_child_still_starting_ends_when_serve_closes_its_pipe_without_a_signal() -> None:
    forked = Forker([], entry=ENTRY)
    child = forked([*PREFIX, "stall"])
    try:
        assert child.poll() is None
        forked.close()

        _wait_for(lambda: child.poll() is not None)
    finally:
        child.kill()


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


def test_a_platform_that_cannot_fork_starts_the_child_with_the_socket_the_forker_holds(monkeypatch) -> None:
    monkeypatch.setattr(zygote, "fork_supported", lambda: False)  # macOS
    started: list[tuple[object, ...]] = []
    listening = socket.socket()
    held = Forker([], entry=ENTRY, fallback=lambda *args: started.append(args) or "child", listening=listening)

    child = held([*PREFIX, "api"], listening)

    assert child == "child"
    assert started == [([*PREFIX, "api"], listening)]
    listening.close()


def test_a_child_handed_a_ready_descriptor_starts_with_the_fallback_beside_the_socket_the_forker_holds() -> None:
    started: list[tuple[object, ...]] = []
    listening = socket.socket()
    held = Forker([], entry=ENTRY, fallback=lambda *args: started.append(args) or "child", listening=listening)

    child = held([*PREFIX, "api"], listening, 7)

    assert child == "child"
    assert started == [([*PREFIX, "api"], listening, 7)]
    listening.close()


def test_a_child_handed_the_socket_the_forker_holds_forks_with_it_named_in_its_environment(tmp_path: Path) -> None:
    listening = socket.socket()
    listening.bind(("127.0.0.1", 0))
    listening.listen()
    held = Forker([], entry=ENTRY, fallback=lambda *args: pytest.fail("a held socket forks"), listening=listening)
    report = tmp_path / "port"
    try:
        child = held([*PREFIX, "port", str(report)], listening)

        assert _wait_for(lambda: report.exists() and report.read_text())  # `write_text` truncates before it writes
        assert report.read_text() == str(listening.getsockname()[1])
        assert held._current is not None  # the preloaded process, not a subprocess, started it
        child.kill()
    finally:
        held.close()
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
