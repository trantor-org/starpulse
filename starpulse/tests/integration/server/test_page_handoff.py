"""The Page API's listening socket is `serve`'s: it reaches the API child, and a `serve` that re-executes itself, on a
descriptor named by `LISTEN_FD_ENV`, and a stopping API child finishes the requests it took before it exits."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import threading
import time
import urllib.request
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.kit.adapter_kit import serve as _serve
from starpulse._internal.server.hold import LISTEN_FD_ENV
from starpulse._internal.server.page_server import DRAIN_S, PageServer
from starpulse._internal.server.server import inherited_socket, serve_until_stopped
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


class _SlowApp:
    """An ASGI app whose requests wait for `release`, noting what the server asks of it as it stops."""

    def __init__(self, order: list[str], drained: bool = True) -> None:
        self.order = order
        self.drained_in_time = drained
        self.release = threading.Event()
        self.arrived = threading.Event()

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":  # the lifespan
            while (await receive())["type"] != "lifespan.shutdown":
                await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.shutdown.complete"})
            return
        self.arrived.set()
        await asyncio.to_thread(self.release.wait)
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"2")]})
        await send({"type": "http.response.body", "body": b"ok"})

    async def end_streams(self) -> None:
        self.order.append("end streams")

    async def drained(self, timeout: float) -> bool:
        self.order.append(f"drain {timeout}")
        return self.drained_in_time


class _Feed:
    def __init__(self, order: list[str]) -> None:
        self.order = order

    def announce(self, *args: Any) -> None:
        self.order.append("announce")

    def save(self) -> None:
        self.order.append("save")


def _ask(port: int, answers: list[int]) -> threading.Thread:
    def get() -> None:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
            answers.append(resp.status)

    asking = threading.Thread(target=get)
    asking.start()
    return asking


@pytest.mark.parametrize("drained", [True, False])
def test_a_stopping_server_tells_the_streams_then_finishes_its_requests_then_saves(
    drained: bool, caplog: pytest.LogCaptureFixture
) -> None:
    order: list[str] = []
    app = _SlowApp(order, drained)
    feed = _Feed(order)
    server = PageServer(app, ("127.0.0.1", 0), stopping=lambda: feed.announce("restarting"))  # type: ignore[arg-type]
    before = signal.getsignal(signal.SIGTERM)
    answers: list[int] = []
    asking = _ask(server.server_port, answers)  # queued on the bound socket until `serve_until_stopped` starts serving

    def stop_while_the_request_is_taken() -> None:
        assert app.arrived.wait(5)
        signal.raise_signal(signal.SIGTERM)
        threading.Timer(0.5, app.release.set).start()

    stopper = threading.Thread(target=stop_while_the_request_is_taken)
    stopper.start()
    try:
        with caplog.at_level(logging.WARNING):
            serve_until_stopped(server, feed)  # type: ignore[arg-type]
    finally:
        signal.signal(signal.SIGTERM, before)
        app.release.set()
        stopper.join(10)
        asking.join(10)

    assert order == ["announce", "end streams", f"drain {DRAIN_S}", "save"]
    assert answers == [200]  # the request taken before the stop was answered
    assert any("requests still running" in r.getMessage() for r in caplog.records) is (not drained)
    assert DRAIN_S < 10.0  # a supervisor kills a child 10 s after asking it to stop


def test_a_server_adopts_a_listening_socket_as_passed_and_serves_on_it() -> None:
    app = _SlowApp([])
    app.release.set()
    listening = socket.create_server(("127.0.0.1", 0))
    server = PageServer(app, listening=listening)  # type: ignore[arg-type]
    port = listening.getsockname()[1]
    server.start()
    answers: list[int] = []
    try:
        _ask(port, answers).join(10)
    finally:
        server.close()

    assert server.server_port == port
    assert answers == [200]


def test_a_stop_is_not_held_by_a_push_refused_with_its_body_unread(tmp_path: Path) -> None:
    with _serve(tmp_path) as server:
        pusher = HTTPConnection("127.0.0.1", server.server_port, timeout=10)
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):  # the 404 may land before the body is sent
            pusher.request("POST", "/api/nowhere", body=b"x" * 3_000_000, headers={"content-type": "application/json"})
        refused = pusher.getresponse().status
        stopping = time.monotonic()
    stopped_in = time.monotonic() - stopping
    pusher.close()

    assert refused == 404
    assert stopped_in < 3
