"""The Claude Code adapter's receiver: a session's OTLP/HTTP log exports in, harness machine events published."""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from starpulse.claude_code import handler
from starpulse.tests.unit.test_claude_code import adapter, exports, replay


def test_the_receiver_publishes_the_events_each_export_maps_to() -> None:
    published: list[dict] = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(adapter(), published.append))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for payload in exports():
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/v1/logs",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()

    assert published == replay()
