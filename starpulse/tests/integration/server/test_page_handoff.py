"""The Page API's listening socket is `serve`'s: it reaches the API child, and a `serve` that re-executes itself, on a
descriptor named by `LISTEN_FD_ENV`, and a stopping API child finishes the requests it took before it exits."""

from __future__ import annotations

import os
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler
from typing import Any

import pytest

from starpulse._internal.server.hold import LISTEN_FD_ENV
from starpulse._internal.server.server import DRAIN_S, StarPulseServer, inherited_socket, serve_until_stopped
from starpulse._internal.server.supervisor import Supervisor


def test_a_socket_named_by_the_handoff_variable_is_adopted_and_not_passed_on() -> None:
    with socket.create_server(("127.0.0.1", 0)) as handed:
        fd = os.dup(handed.fileno())
        try:
            adopted = inherited_socket({LISTEN_FD_ENV: str(fd)})

            assert adopted is not None
            assert adopted.getsockname() == handed.getsockname()
            assert not adopted.get_inheritable()  # the workers `serve` starts must not keep it open
        finally:
            os.close(fd) if adopted is None else adopted.close()


def test_a_handoff_variable_naming_no_socket_is_refused(tmp_path: Any) -> None:
    with open(tmp_path / "file", "w") as plain:
        with pytest.raises(ValueError, match="not a socket"):
            inherited_socket({LISTEN_FD_ENV: str(plain.fileno())})


def test_the_service_manager_protocol_still_adopts_its_socket_for_this_process_only() -> None:
    assert inherited_socket({"LISTEN_PID": str(os.getpid() + 1), "LISTEN_FDS": "1"}) is None
    assert inherited_socket({}) is None


def test_a_serve_that_re_executes_keeps_the_page_socket_open_for_its_next_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LISTEN_FD_ENV, "0")  # restored on exit: `reexec` sets the variable in this process
    seen: list[str | None] = []
    with socket.create_server(("127.0.0.1", 0)) as listening:
        supervisor = Supervisor(
            {"api": ["api"]}, sockets={"api": listening}, execute=lambda: seen.append(os.environ.get(LISTEN_FD_ENV))
        )

        supervisor.reexec()

        assert seen == [str(listening.fileno())]
        assert listening.get_inheritable()  # `execv` keeps it open


class _Held(StarPulseServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), BaseHTTPRequestHandler)
        self.release = threading.Event()
        self.finished = 0

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        self.release.wait()
        self.finished += 1


def test_draining_waits_for_the_requests_taken_and_reports_whether_they_finished() -> None:
    server = _Held()
    try:
        server.process_request(object(), ("127.0.0.1", 1))
        server.process_request(object(), ("127.0.0.1", 2))
        threading.Timer(0.2, server.release.set).start()
        started = time.monotonic()

        drained = server.drain(5.0)

        assert drained
        assert server.finished == 2
        assert time.monotonic() - started >= 0.15
    finally:
        server.release.set()
        server.server_close()


def test_draining_gives_up_after_its_timeout_with_a_request_still_running() -> None:
    server = _Held()
    try:
        server.process_request(object(), ("127.0.0.1", 1))

        assert not server.drain(0.1)
    finally:
        server.release.set()
        server.server_close()


def test_a_stream_is_not_a_request_to_wait_for() -> None:
    server = _Held()
    try:
        server.process_request(object(), ("127.0.0.1", 1))
        assert server.open_stream()  # the worker leaves the request pool for the stream

        assert server.drain(0.1)
    finally:
        server.release.set()
        server.server_close()


class _Stopping:
    """A server `serve_forever` of which returns at once and records when it was drained."""

    def __init__(self, order: list[str], drained: bool = True) -> None:
        self.order = order
        self.drained = drained

    def serve_forever(self) -> None:
        raise KeyboardInterrupt

    def drain(self, timeout: float) -> bool:
        self.order.append(f"drain {timeout}")
        return self.drained


class _Feed:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def announce(self, *args: Any) -> None:
        self.order.append("announce")

    def save(self) -> None:
        self.order.append("save")


@pytest.mark.parametrize("drained", [True, False])
def test_a_stopping_server_tells_the_streams_then_finishes_its_requests_then_saves(drained: bool) -> None:
    order: list[str] = []
    before = signal.getsignal(signal.SIGTERM)
    try:
        serve_until_stopped(_Stopping(order, drained), _Feed(order))  # type: ignore[arg-type]
    finally:
        signal.signal(signal.SIGTERM, before)

    assert order == ["announce", f"drain {DRAIN_S}", "save"]
    assert DRAIN_S < 10.0  # a supervisor kills a child 10 s after asking it to stop
