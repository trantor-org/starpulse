"""The load test's rules: where an event-stream event ends, and which routes break the budget under load."""

from __future__ import annotations

import gzip
import http.server
import importlib.util
import sys
import threading
import time
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[1] / "bench"
sys.path.insert(0, str(_BENCH))
# Locust monkey-patches the interpreter with gevent on import, which a test process cannot survive; the rules need none.
sys.modules.setdefault("gevent", None)
_spec = importlib.util.spec_from_file_location("load", _BENCH / "load.py")
assert _spec and _spec.loader
load = sys.modules["load"] = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(load)


def test_an_event_ends_at_its_blank_line():
    lines = [
        b"event: snapshot\n",
        b"data: ref /api/events/body/abc\n",
        b"\n",
        b"event: ledgers\n",
        b"data: {}\n",
        b"\n",
    ]
    assert list(load.events(lines)) == [("snapshot", "ref /api/events/body/abc"), ("ledgers", "{}")]


def test_a_comment_and_an_unnamed_event_are_messages():
    lines = [b": keepalive\n", b"\n", b"data: a\r\n", b"data: b\r\n", b"\r\n"]
    assert list(load.events(lines)) == [("message", "a\nb")]


def test_a_stream_cut_mid_event_yields_nothing_for_it():
    assert list(load.events([b"event: snapshot\n", b"data: x\n"])) == []


def test_a_route_over_the_budget_fails_the_run():
    p95s = {"/api/snapshot": 12.0, "/api/level": 80.0, "Aggregated": 60.0}
    assert load.over_budget(p95s, {}) == ["/api/level p95 80 ms > 50 ms"]


def test_a_failed_request_fails_the_run_even_when_fast():
    assert load.over_budget({"/api/pulls": 5.0}, {"/api/pulls": 3}) == ["/api/pulls 3 failed"]


def test_a_run_inside_the_budget_passes():
    assert load.over_budget({"/api/snapshot": 49.0, "/api/events first snapshot": 50.0}, {}) == []


def test_the_discovery_reads_are_not_judged():
    assert load.over_budget({load.DISCOVERY: 900.0}, {load.DISCOVERY: 2}) == []


def test_viewers_arriving_together_discover_once():
    made, started = [], threading.Barrier(5)

    def make() -> str:
        made.append(1)
        time.sleep(0.05)  # the first viewer is still discovering when the rest arrive
        return "paths"

    once, got = load.Once(threading.Lock()), []

    def viewer() -> None:
        started.wait()
        got.append(once.get(make))

    viewers = [threading.Thread(target=viewer) for _ in range(5)]
    for thread in viewers:
        thread.start()
    for thread in viewers:
        thread.join()
    assert (len(made), got) == (1, ["paths"] * 5)


def test_the_snapshot_body_is_read_compressed_as_the_server_sent_it():
    packed = gzip.compress(b"x" * 100_000)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = packed if "gzip" in self.headers.get("accept-encoding", "") else b"x" * 100_000
            self.send_response(200 if self.path == "/api/events/body/abc" else 404)
            self.send_header("content-encoding", "gzip")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        port = server.server_address[1]
        assert load.compressed_body("127.0.0.1", port, "/api/events/body/abc") == (200, len(packed))
        assert load.compressed_body("127.0.0.1", port, "/api/events/body/gone")[0] == 404
    finally:
        server.shutdown()
        server.server_close()
