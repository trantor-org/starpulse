"""The page server sends a response's head and body without waiting out the client's 40 ms delayed acknowledgement."""

from __future__ import annotations

import socket
from typing import Any, cast

from starpulse.views.page_server import PageServer


def _nodelay(sock: socket.socket) -> int:
    return sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)


def test_a_socket_the_server_binds_sends_each_write_at_once() -> None:
    server = PageServer(cast(Any, object()))
    try:
        assert _nodelay(server.socket) == 1
    finally:
        server.socket.close()


def test_a_socket_the_server_is_given_sends_each_write_at_once() -> None:
    with socket.create_server(("127.0.0.1", 0)) as listening:
        server = PageServer(cast(Any, object()), listening=listening)

        assert _nodelay(server.socket) == 1
