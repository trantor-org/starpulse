"""The Loki signal store the copy into `starpulse_signals` reads (a fake one speaking its push and query_range API):
what a push, a paged fetch and an outage do. No adapter writes it any more; T4a deletes it."""

import json
import threading
import urllib.parse
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from starpulse.harness_telemetry.adapters.inbound.telemetry import CLAUDE_CODE, Signal
from starpulse.harness_telemetry.adapters.outbound import loki as loki_module
from starpulse.harness_telemetry.adapters.outbound.loki import LokiSignals


def signal(n: int, at: float) -> Signal:
    return Signal(CLAUDE_CODE, "s", "request", at, f"k{n}", model="m", input=n)


def push(store: LokiSignals, found: Iterable[Signal]) -> None:
    """Push `found` as an adapter did before the cutover: one line per signal."""
    store.push(asdict(s) for s in found)


class FakeLoki:
    """The lines pushed to it, served back by stamp the way `query_range` does."""

    def __init__(self) -> None:
        self.lines: list[tuple[int, str]] = []
        self.pushes: list[dict] = []
        self.queries: list[dict[str, str]] = []
        self.down = False
        self.limited = 0  # the next pushes answered 429, as Loki's ingestion rate limit does


@contextmanager
def served(loki: FakeLoki) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if loki.down:
                return self.send_error(503)
            if loki.limited:
                loki.limited -= 1
                return self.send_error(429)
            loki.pushes.append(body)
            for stream in body["streams"]:
                loki.lines += [(int(stamp), line) for stamp, line in stream["values"]]
            self.send_response(204)
            self.end_headers()

        def do_GET(self) -> None:
            if loki.down:
                return self.send_error(503)
            query = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()}
            loki.queries.append(query)
            start, end, limit = int(query["start"]), int(query["end"]), int(query["limit"])
            found = sorted(line for line in loki.lines if start <= line[0] < end)[:limit]
            values = [[str(stamp), text] for stamp, text in found]
            body = json.dumps({"data": {"result": [{"stream": {}, "values": values}] if values else []}}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_a_push_is_one_line_per_signal_in_the_signals_stream() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        push(LokiSignals(url), [signal(1, 100.0), signal(2, 200.0)])

    assert loki.pushes[0]["streams"][0]["stream"] == {"job": "starpulse-signals"}
    assert [json.loads(text)["key"] for _, text in loki.lines] == ["k1", "k2"]


def test_a_fetch_reads_back_what_was_pushed_in_stamp_order() -> None:
    loki = FakeLoki()
    found = [signal(1, 100.0), signal(2, 50.0), signal(3, 200.0)]
    with served(loki) as url:
        push(LokiSignals(url), found)

        assert [row["key"] for _, row in LokiSignals(url).fetch(0)] == ["k1", "k2", "k3"]


def test_a_fetch_after_a_stamp_returns_only_the_lines_stamped_later() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        store = LokiSignals(url)
        push(store, [signal(1, 100.0)])
        last = max(stamp for stamp, _ in store.fetch(0))
        push(store, [signal(2, 200.0)])

        assert [row["key"] for _, row in store.fetch(last)] == ["k2"]


def test_a_fetch_pages_through_more_lines_than_one_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loki_module, "PAGE", 2)
    loki = FakeLoki()
    with served(loki) as url:
        store = LokiSignals(url)
        store.push({"key": f"k{n}"} for n in range(5))

        assert [row["key"] for _, row in store.fetch(0)] == [f"k{n}" for n in range(5)]


def test_an_unreachable_loki_raises_on_fetch_and_on_push() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        store = LokiSignals(url)
        loki.down = True

        with pytest.raises(OSError):
            push(store, [signal(1, 100.0)])
        with pytest.raises(OSError):
            store.fetch(0)
