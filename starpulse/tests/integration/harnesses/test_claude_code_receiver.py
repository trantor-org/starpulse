"""The Claude Code adapter's receiver: a session's OTLP/HTTP log exports in, harness machine events published."""

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.harnesses.claude_code import handler
from starpulse._internal.harnesses.telemetry import CLAUDE_CODE, CODEX, TelemetryLog, signals
from starpulse.tests.unit.harnesses.test_claude_code import adapter, exports, replay
from starpulse.tests.unit.harnesses.test_telemetry import FIXTURES


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


def _post(server: ThreadingHTTPServer, payload: dict) -> int:
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_port}/v1/logs",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status


def test_the_receiver_records_the_signals_of_both_harnesses_exports_in_the_telemetry_log(tmp_path: Path) -> None:
    telemetry = TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), handler(adapter(), lambda event: None, lambda payload: telemetry.publish(signals(payload)))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        for name in ("claude_code", "codex"):
            for line in (FIXTURES / name / "otlp.ndjson").read_text().splitlines():
                assert _post(server, json.loads(line)) == 200
    finally:
        server.shutdown()
        server.server_close()

    assert {(s.harness, s.kind) for s in telemetry.read()} >= {
        (CLAUDE_CODE, "request"),
        (CLAUDE_CODE, "prompt"),
        (CODEX, "request"),
        (CODEX, "prompt"),
    }


def test_a_telemetry_consumer_that_raises_does_not_stop_the_export_being_ingested_and_answered() -> None:
    published: list[dict] = []

    def broken(payload: dict) -> None:
        raise RuntimeError("telemetry down")

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(adapter(), published.append, broken))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        statuses = [_post(server, payload) for payload in exports()]
    finally:
        server.shutdown()
        server.server_close()

    assert set(statuses) == {200}
    assert published == replay()
