"""The telemetry log over a Loki instance (a fake one speaking its push and query_range API): what a push, a replay,
an outage and a trim do to what is read."""

import json
import threading
import urllib.parse
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from starpulse.harness_telemetry import loki as loki_module
from starpulse.harness_telemetry.loki import LokiSignals
from starpulse.harness_telemetry.telemetry import CLAUDE_CODE, Signal, TelemetryLog, telemetry_log


def signal(n: int, at: float) -> Signal:
    return Signal(CLAUDE_CODE, "s", "request", at, f"k{n}", model="m", input=n)


class FakeLoki:
    """The lines pushed to it, served back by stamp the way `query_range` does."""

    def __init__(self) -> None:
        self.lines: list[tuple[int, str]] = []
        self.pushes: list[dict] = []
        self.queries: list[dict[str, str]] = []
        self.down = False


@contextmanager
def served(loki: FakeLoki) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if loki.down:
                return self.send_error(503)
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
        TelemetryLog(None, loki=LokiSignals(url)).publish([signal(1, 100.0), signal(2, 200.0)])

    assert loki.pushes[0]["streams"][0]["stream"] == {"job": "starpulse-signals"}
    assert [json.loads(text)["key"] for _, text in loki.lines] == ["k1", "k2"]


def test_what_is_published_reads_back_equal_and_in_order() -> None:
    loki = FakeLoki()
    found = [signal(1, 100.0), signal(2, 50.0), signal(3, 200.0)]
    with served(loki) as url:
        telemetry = TelemetryLog(None, loki=LokiSignals(url))
        telemetry.publish(found)

        assert telemetry.read() == found


def test_a_replayed_signal_is_read_once_and_a_later_publish_joins_it() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        telemetry = TelemetryLog(None, loki=LokiSignals(url))
        telemetry.publish([signal(1, 100.0)])
        telemetry.publish([signal(1, 100.0), signal(2, 101.0)])
        assert [s.key for s in telemetry.read()] == ["k1", "k2"]

        telemetry.publish([signal(3, 102.0), signal(2, 101.0)])
        assert [s.key for s in telemetry.read()] == ["k1", "k2", "k3"]


def test_a_second_reader_sees_what_the_first_published() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        TelemetryLog(None, loki=LokiSignals(url)).publish([signal(1, 100.0)])

        assert [s.key for s in TelemetryLog(None, loki=LokiSignals(url)).read()] == ["k1"]


def test_a_read_polls_after_the_last_stamp_it_saw() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        telemetry = TelemetryLog(None, loki=LokiSignals(url))
        telemetry.publish([signal(1, 100.0)])
        telemetry.read()
        telemetry.read()

    first, second = (int(query["start"]) for query in loki.queries)
    assert second == max(stamp for stamp, _ in loki.lines) + 1 > first


def test_a_read_returns_only_the_signals_from_the_window_on() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        telemetry = TelemetryLog(None, loki=LokiSignals(url))
        telemetry.publish([signal(1, 100.0), signal(2, 200.0)])

        assert [s.key for s in telemetry.read(150.0)] == ["k2"]


def test_a_read_drops_what_is_older_than_keep_before_the_newest_signal() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        telemetry = TelemetryLog(None, 100.0, loki=LokiSignals(url))
        telemetry.publish([signal(1, 100.0), signal(2, 250.0), signal(3, 300.0)])

        assert [s.key for s in telemetry.read()] == ["k2", "k3"]


def test_a_fetch_pages_through_more_lines_than_one_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(loki_module, "PAGE", 2)
    loki = FakeLoki()
    with served(loki) as url:
        store = LokiSignals(url)
        store.push({"key": f"k{n}"} for n in range(5))

        assert [row["key"] for _, row in store.fetch(0)] == [f"k{n}" for n in range(5)]


def test_an_unreachable_loki_raises_on_read_and_on_publish() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        telemetry = TelemetryLog(None, loki=LokiSignals(url))
        loki.down = True

        with pytest.raises(OSError):
            telemetry.publish([signal(1, 100.0)])
        with pytest.raises(OSError):
            telemetry.read()


def test_the_factory_chooses_loki_by_the_configured_url() -> None:
    loki = FakeLoki()
    with served(loki) as url:
        telemetry_log(url, None).publish([signal(1, 100.0)])

    assert len(loki.lines) == 1
