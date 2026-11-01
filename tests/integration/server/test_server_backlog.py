"""The listen backlog: a crowd of pages connecting at once is queued for accept, not dropped into a SYN retransmit."""

import socket
import subprocess
from http.client import HTTPConnection
from typing import Any, cast

from starpulse.views.adapters.inbound.page_server import PageServer


def _listen_send_queue(port: int) -> int:
    """The backlog the kernel keeps for the listener on `port`: its Send-Q in `ss`."""
    row = subprocess.run(["ss", "-H", "-ltn", f"sport = :{port}"], capture_output=True, text=True, check=True).stdout
    return int(row.split()[2])


def test_a_socket_inherited_at_backlog_1024_keeps_it_once_the_server_serves() -> None:
    async def app(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

    with socket.create_server(("127.0.0.1", 0)) as listening:
        listening.listen(1024)  # the backlog `starpulse.socket` (Backlog=1024) leaves the kernel with
        server = PageServer(cast(Any, app), listening=listening)
        server.start()
        try:
            page = HTTPConnection("127.0.0.1", server.server_port, timeout=10)  # queued until the server accepts it
            page.request("GET", "/")
            assert page.getresponse().status == 200
            page.close()

            assert _listen_send_queue(server.server_port) == 1024
        finally:
            server.close()


def test_fifty_pages_connecting_before_any_is_accepted_all_connect() -> None:
    server = PageServer(None, ("127.0.0.1", 0))  # type: ignore[arg-type] # never started: nothing is accepted
    pages = []
    try:
        for _ in range(50):
            pages.append(socket.create_connection(("127.0.0.1", server.server_port), timeout=0.5))
    finally:
        for page in pages:
            page.close()
        server.socket.close()

    assert len(pages) == 50
