"""A `serve` that re-executes into a new release keeps the Page API answering: the new release's API starts beside the old
one before anything ends, and the next image adopts it in place of starting a third."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from starpulse.runtime import launch
from starpulse.runtime.config import load
from starpulse.runtime.closure import SELF, Reading
from starpulse.runtime.hold import ADOPT_ENV, LISTEN_FD_ENV, adopted_from_env
from starpulse.runtime.supervisor import Adopted, Supervisor, spawn_child, worker_commands

# an API stand-in: answers its pid on the socket it was handed, announces itself ready, and ends when its stdin closes
API = """
import os, socket, sys, threading
listening = socket.socket(fileno=int(os.environ["STARPULSE_LISTEN_FD"]))
ready = os.environ.pop("STARPULSE_READY_FD", None)
if ready:
    os.write(int(ready), b"1")
    os.close(int(ready))
threading.Thread(target=lambda: (sys.stdin.buffer.read(), os._exit(0)), daemon=True).start()
while True:
    conn, _ = listening.accept()
    conn.sendall(str(os.getpid()).encode())
    conn.close()
"""
SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]


def _reading(code: str) -> Reading:
    return Reading(frozenset({("starpulse/x.py", code)}), None, None)


class _Asking(threading.Thread):
    """Connects to the socket every 20 ms and records the pid that answers, or the failure, and the slowest answer."""

    def __init__(self, address: tuple[str, int]) -> None:
        super().__init__(daemon=True)
        self.address = address
        self.answers: list[int | str] = []
        self.slowest = 0.0
        self.stopped = threading.Event()

    def run(self) -> None:
        while not self.stopped.is_set():
            began = time.monotonic()
            try:
                with socket.create_connection(self.address, timeout=1.0) as client:
                    self.answers.append(int(client.recv(16)))
            except (OSError, ValueError) as exc:
                self.answers.append(repr(exc))
            self.slowest = max(self.slowest, time.monotonic() - began)
            time.sleep(0.02)


@pytest.fixture
def served() -> Iterator[tuple[socket.socket, list[Supervisor]]]:
    listening = socket.create_server(("127.0.0.1", 0))
    started: list[Supervisor] = []
    yield listening, started
    for each in started:
        each.stop()
    listening.close()


def test_worker_commands_run_on_the_launchers_interpreter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch, "interpreter", lambda *_: "/srv/current/.venv/bin/python")
    commands = worker_commands(load(None), None)

    assert {command[0] for command in commands.values()} == {"/srv/current/.venv/bin/python"}


def test_the_page_api_answers_throughout_a_serve_that_re_executes_into_a_new_release(
    served: tuple[socket.socket, list[Supervisor]], monkeypatch: pytest.MonkeyPatch
) -> None:
    listening, started = served
    monkeypatch.setenv(ADOPT_ENV, "")  # `reexec` writes both; the test's env gets them back
    monkeypatch.setenv(LISTEN_FD_ENV, "0")
    release = {"code": "a"}
    handed: dict[str, str] = {}

    def next_image() -> None:  # what `os.execv` hands the process that replaces this one
        handed.update({ADOPT_ENV: os.environ[ADOPT_ENV]})

    first = Supervisor(
        {"api": [sys.executable, "-c", API], "pulls": SLEEP},
        sockets={"api": listening},
        read=lambda name: _reading(release["code"]),
        execute=next_image,
        poll=0.02,
        warm=10.0,
    )
    started.append(first)
    first.start()
    asking = _Asking(listening.getsockname())
    deadline = time.monotonic() + 10
    asking.start()
    while not asking.answers and time.monotonic() < deadline:
        time.sleep(0.02)
    before = set(asking.answers)

    release["code"] = "b"
    assert first.reload()["supervisor"] == "re-executed"
    first.reexec()
    pid, fd = handed[ADOPT_ENV].split(":")  # one process stands in for two: the next image owns a copy of the fd
    monkeypatch.setenv(ADOPT_ENV, f"{pid}:{os.dup(int(fd))}")
    adopted = adopted_from_env(os.environ)
    assert adopted is not None
    second = Supervisor(
        {"api": [sys.executable, "-c", API], "pulls": SLEEP},
        sockets={"api": listening},
        read=lambda name: _reading("b"),
        poll=0.02,
        adopted={"api": adopted},
    )
    started.append(second)
    second.start()
    time.sleep(0.5)
    asking.stopped.set()
    asking.join()

    assert all(isinstance(answer, int) for answer in asking.answers), asking.answers
    assert asking.slowest < 1.0
    assert len(before) == 1
    assert set(asking.answers) - before == {
        adopted.pid
    }  # the API the old image started beside the first is the one kept
    assert second._children["api"].proc is adopted
    assert adopted.poll() is None


def test_the_re_executing_serve_does_not_pass_the_old_images_page_build_to_the_api_it_starts_beside_the_old_one(
    served: tuple[socket.socket, list[Supervisor]], monkeypatch: pytest.MonkeyPatch
) -> None:
    listening, started = served
    monkeypatch.setenv("STARPULSE_STATIC", "/srv/releases/old/static")
    seen: list[str | None] = []

    def spawn(command: Any, *handed: Any) -> Any:
        seen.append(os.environ.get("STARPULSE_STATIC"))
        return spawn_child(command, *handed)

    release = {"code": "a"}
    supervisor = Supervisor(
        {"api": [sys.executable, "-c", API]},
        spawn=spawn,
        sockets={"api": listening},
        read=lambda name: _reading(release["code"]),
        execute=lambda: None,
        poll=0.02,
    )
    started.append(supervisor)
    supervisor.start()
    release["code"] = "b"
    supervisor.reload()

    assert seen == ["/srv/releases/old/static", None]


def test_an_adopted_process_is_polled_ended_and_killed_like_a_child(tmp_path: Any) -> None:
    child = subprocess.Popen(SLEEP, stdin=subprocess.PIPE)
    adopted = Adopted(child.pid, os.dup(child.stdin.fileno()))

    assert adopted.poll() is None
    adopted.terminate()
    adopted.wait(5)
    assert adopted.poll() is not None
    child.wait()


def test_an_adopted_process_that_will_not_end_times_out_its_wait() -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", "import signal, time; signal.signal(15, signal.SIG_IGN); time.sleep(60)"]
    )
    time.sleep(0.3)
    adopted = Adopted(child.pid, -1)

    adopted.terminate()
    with pytest.raises(subprocess.TimeoutExpired):
        adopted.wait(0.3)
    adopted.kill()
    adopted.wait(5)
    child.wait()


def test_the_adoption_variable_names_the_pid_and_descriptor_and_is_consumed() -> None:
    environ = {ADOPT_ENV: "4321:9"}

    adopted = adopted_from_env(environ)

    assert (adopted.pid, adopted.fd) == (4321, 9)  # type: ignore[union-attr]
    assert ADOPT_ENV not in environ
    assert adopted_from_env({}) is None
    assert adopted_from_env({ADOPT_ENV: "garbage"}) is None


def test_serve_closure_is_unchanged_so_a_kept_supervisor_hands_nothing_over(
    served: tuple[socket.socket, list[Supervisor]],
) -> None:
    listening, started = served
    supervisor = Supervisor(
        {"api": [sys.executable, "-c", API]},
        sockets={"api": listening},
        read=lambda name: _reading("a"),
        poll=0.02,
    )
    started.append(supervisor)
    supervisor.start()

    assert supervisor.reload() == {"supervisor": "kept", "reads": "launcher", "children": {"api": "kept"}}
    assert SELF  # the serve reading is part of every report's basis
