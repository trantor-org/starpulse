"""A connection accepted as `SIGTERM` arrives is answered, however slow the server is to hand it to a worker."""

import os
import signal
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler
from typing import Any

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.server.server import StarPulseServer, serve_until_stopped
from starpulse.tests.machines import MACHINES


class _Ok(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_: Any) -> None:
        pass


class _SignalledMidAccept(StarPulseServer):
    """A server whose host is so loaded that `SIGTERM` lands while it hands an accepted connection to a worker."""

    def process_request(self, request: Any, client_address: Any) -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(0.3)  # the handler runs here, as it does while a starved `Thread.start` waits for its thread
        super().process_request(request, client_address)


def test_a_connection_accepted_as_sigterm_arrives_is_answered() -> None:
    server = _SignalledMidAccept(("127.0.0.1", 0), _Ok)
    port = server.server_address[1]
    outcome: list[object] = []

    def ask() -> None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as resp:
                outcome.append(resp.status)
        except OSError as exc:
            outcome.append(exc)

    client = threading.Thread(target=ask)
    client.start()
    before = signal.getsignal(signal.SIGTERM)
    try:
        serve_until_stopped(server, BoardFeed(machines=MACHINES))
    except SystemExit:
        pass
    finally:
        signal.signal(signal.SIGTERM, before)
        client.join(timeout=10)
        server.server_close()

    assert outcome == [200]
