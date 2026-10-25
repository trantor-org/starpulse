"""Replacing the Page API child drains the requests it took and refuses none that arrive meanwhile."""

import http.client
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import closing
from pathlib import Path

import pytest

from starpulse._internal.server.closure import SELF, Reading
from starpulse._internal.server.supervisor import Supervisor
from starpulse.tests.integration.server.test_standalone import _env, build  # noqa: F401 - `build` is a fixture
from starpulse.tests.supervised import running_pids


def _snapshot(port: int) -> None:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshot", timeout=30) as resp:
        assert resp.status == 200
        resp.read()


# starts two real API children (4 s alone), so a loaded host takes it past the gate's bound
@pytest.mark.slow
def test_the_swapped_api_child_answers_every_request_made_across_the_swap(
    build: None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,  # noqa: F811
) -> None:
    for key, value in _env().items():
        monkeypatch.setenv(key, value)
    config = tmp_path / "starpulse.toml"
    config.write_text("")
    version = [0]

    def read(name: str) -> Reading:
        return Reading(frozenset({(name, "0" if name == SELF else str(version[0]))}), (), ())

    command = [sys.executable, "-m", "starpulse", "worker", "api", "--config", str(config), "--hours", "6"]
    answered: list[int] = []
    failed: list[BaseException] = []
    halt = threading.Event()

    def get(port: int) -> int:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshot", timeout=60) as resp:
            resp.read()
            return resp.status

    def ask(port: int) -> None:
        while not halt.is_set():
            try:
                try:
                    answered.append(get(port))
                except (http.client.RemoteDisconnected, ConnectionResetError):
                    # A connection the old child had accepted but not yet read is closed as it stops, before any
                    # byte of a reply; a client resends an idempotent GET then, as a browser does. A refusal or a
                    # timeout is not retried and still fails.
                    answered.append(get(port))
            except (OSError, urllib.error.URLError) as exc:
                failed.append(exc)
            time.sleep(0.05)

    def answered_by(count: int, reason: str) -> None:
        deadline = time.monotonic() + 60
        while len(answered) < count:
            assert time.monotonic() < deadline, reason
            time.sleep(0.05)

    with closing(socket.create_server(("127.0.0.1", 0), backlog=128)) as listening:
        port = listening.getsockname()[1]
        supervisor = Supervisor({"api": command}, sockets={"api": listening}, read=read, poll=0.1)
        supervisor.start()
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    _snapshot(port)
                    break
                except OSError:
                    assert time.monotonic() < deadline, "the first API child never answered"
                    time.sleep(0.05)
            first = running_pids(supervisor)["api"]
            clients = [threading.Thread(target=ask, args=(port,), daemon=True) for _ in range(4)]
            for client in clients:
                client.start()
            answered_by(8, "the first API child never answered the clients")
            version[0] = 1
            assert supervisor.reload()["children"] == {"api": "replaced"}
            second = running_pids(supervisor)["api"]
            answered_by(len(answered) + 8, "the replacement never answered")  # what queued while it started
        finally:
            halt.set()
            supervisor.stop()

    assert first != second
    assert failed == []
    assert set(answered) == {200}
