"""The conditional GitHub client against a local server: the ETag it sends, the 304 it reads and the next page it follows."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from starpulse.github.adapters.outbound.rest import connect_client


class Handler(BaseHTTPRequestHandler):
    seen: list[dict[str, str]] = []

    def do_GET(self) -> None:  # noqa: N802
        self.seen.append({"path": self.path, "auth": self.headers.get("Authorization", ""), "match": self.headers.get("If-None-Match", "")})
        if self.headers.get("If-None-Match") == '"v1"':
            self.send_response(304)
            self.end_headers()
            return
        body = json.dumps([{"n": 1}] if self.path == "/list" else {"ok": True}).encode()
        self.send_response(200 if self.path != "/missing" else 404)
        self.send_header("ETag", '"v1"')
        if self.path == "/list":
            page = f"http://{self.headers['Host']}/list?page=2"
            self.send_header("Link", f'<{page}>; rel="prev", <{page}>; rel="next"')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        return None


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("GITHUB_API_URL", base)
    Handler.seen = []
    yield base
    server.shutdown()
    server.server_close()


def test_the_client_signs_in_sends_the_etag_and_reads_a_304_and_the_next_page(api: str) -> None:
    client = connect_client(lambda: "app-token")

    first = client("GET", "/list", None)
    again = client("GET", "/list", first.etag)
    other = client("GET", "/thing", None)
    missing = client("GET", "/missing", None)

    assert (first.status, first.body, first.etag) == (200, {"items": [{"n": 1}]}, '"v1"')
    assert first.next == "/list?page=2"
    assert (again.status, again.etag) == (304, '"v1"')
    assert (other.status, other.body) == (200, {"ok": True})
    assert missing.status == 404
    assert Handler.seen[0]["auth"] == "Bearer app-token"
    assert [seen["match"] for seen in Handler.seen[:2]] == ["", '"v1"']
