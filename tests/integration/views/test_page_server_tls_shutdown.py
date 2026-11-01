"""Stopping the TLS page server while a client reuses a connection logs no traceback: the request is the keep-alive race
of a connection the server is already closing, not a fault."""

from __future__ import annotations

import logging
import socket
import ssl
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest
from starpulse.views.adapters.inbound.page_server import PageServer

REQUEST = b"GET / HTTP/1.1\r\nHost: x\r\n\r\n"


class _Ok:
    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            while (await receive())["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.shutdown.complete"})
            return
        await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", b"2")]})
        await send({"type": "http.response.body", "body": b"ok"})

    async def end_streams(self) -> None: ...

    async def drained(self, timeout: float) -> bool:
        return True


def test_a_request_on_a_connection_the_server_is_closing_logs_no_traceback(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=localhost",
         "-keyout", str(key), "-out", str(cert)],
        check=True,
        capture_output=True,
    )  # fmt: skip
    server = PageServer(_Ok(), tls=(cert, key))  # type: ignore[arg-type]
    client_context = ssl.create_default_context()
    client_context.check_hostname, client_context.verify_mode = False, ssl.CERT_NONE
    client_context.set_alpn_protocols(["http/1.1"])
    server.start()
    connections = []
    for _ in range(10):
        connection = client_context.wrap_socket(socket.create_connection(("127.0.0.1", server.server_port)))
        connection.sendall(REQUEST)
        connection.recv(4096)
        connections.append(connection)
    with caplog.at_level(logging.ERROR):
        server.stop()
        time.sleep(0.05)  # the server's close_notify is out before the client's next request
        for connection in connections:
            try:
                connection.sendall(REQUEST)
            except OSError:
                pass  # the server's close already reached this client
        server.join()
    own = ("hypercorn", "starpulse.views.adapters.inbound.page_server")  # not a thread an earlier test leaked
    assert [(r.name, r.getMessage()) for r in caplog.records if r.exc_info and r.name.startswith(own)] == []
