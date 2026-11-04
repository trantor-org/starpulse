"""Each adapter writes the signal table alone: a replayed export adds no row, and nothing reaches the stream."""

import threading
import urllib.request
from collections.abc import Callable
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import text

from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.adapters.inbound.claude_code import handler
from starpulse.harness_telemetry.adapters.inbound.telemetry import TelemetryLog, signals
from starpulse.harness_telemetry.adapters.outbound.cursor import ingest

from tests.integration.harness_telemetry.test_cursor_ingest import NOW, projects
from tests.unit.harness_telemetry.test_claude_code import adapter
from tests.unit.harness_telemetry.test_cursor import ANALYTICS, KEYS
from tests.unit.harness_telemetry.test_telemetry import FIXTURES


def counts(log: EventLog) -> tuple[int, int]:
    """The rows of `starpulse_signals` and of the private `telemetry:signals` stream."""
    with log.engine.connect() as db:
        table = db.execute(text("SELECT COUNT(*) FROM starpulse_signals")).scalar_one()
        stream = db.execute(
            text("SELECT COUNT(*) FROM starpulse_events WHERE stream = :stream"), {"stream": TelemetryLog.STREAM}
        ).scalar_one()
    return table, stream


def export_through_receiver(name: str, telemetry: TelemetryLog) -> None:
    """Post every line of the harness's recorded OTLP export to the receiver the adapter serves."""
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), handler(adapter(), lambda event: None, lambda payload: telemetry.publish(signals(payload)))
    )
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        for line in (FIXTURES / name / "otlp.ndjson").read_text().splitlines():
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/v1/logs",
                data=line.encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                assert response.status == 200
    finally:
        server.shutdown()
        server.server_close()


def claude_code_export(tmp_path: Path, telemetry: TelemetryLog) -> None:
    export_through_receiver("claude_code", telemetry)


def codex_export(tmp_path: Path, telemetry: TelemetryLog) -> None:
    export_through_receiver("codex", telemetry)


def cursor_export(tmp_path: Path, telemetry: TelemetryLog) -> None:
    root = tmp_path / "projects"
    if not root.exists():
        projects(tmp_path, age_hours=1)
    ingest(root, telemetry, keys=KEYS, analytics=ANALYTICS, now=NOW)


@pytest.mark.parametrize("export", [claude_code_export, codex_export, cursor_export])
def test_a_replayed_export_adds_no_row_and_nothing_reaches_the_stream(
    tmp_path: Path, export: Callable[[Path, TelemetryLog], None]
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    telemetry = TelemetryLog(log)

    export(tmp_path, telemetry)
    stored, stream = counts(log)
    export(tmp_path, telemetry)

    assert stored > 0
    assert stream == 0
    assert counts(log) == (stored, 0)


def test_a_table_that_cannot_be_written_drops_the_signals_and_the_export_is_still_answered(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    telemetry = TelemetryLog(log)
    with log.engine.begin() as db:
        db.execute(text("DROP TABLE starpulse_signals"))

    export_through_receiver("claude_code", telemetry)

    assert "signal table" in caplog.text
