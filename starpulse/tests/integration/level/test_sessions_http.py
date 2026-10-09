"""GET /api/analytics/sessions against recorded exports of both harnesses published to the event log."""

import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.telemetry import TelemetryLog, signals
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse.contracts.adapters import TaskKeys
from starpulse.tests.machines import MACHINES
from starpulse.tests.unit.harnesses.test_telemetry import FIXTURES

KEYS = TaskKeys(
    key=re.compile(r"TASK-\d+"),
    branch=re.compile(r"(?:refs/heads/)?(?:[\w.-]+/)*task-(\d+)", re.IGNORECASE),
    key_format="TASK-{}",
)
#: An hour after the recorded exports.
NOW = datetime.fromisoformat("2026-10-09T22:30:00+00:00").timestamp()


def _get(server: ThreadingHTTPServer, query: str = "") -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/analytics/sessions{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def publish_recorded(telemetry: TelemetryLog) -> None:
    for name in ("claude_code/otlp.ndjson", "codex/otlp.ndjson"):
        for line in (FIXTURES / name).read_text().splitlines():
            telemetry.publish(signals(json.loads(line)))


@pytest.fixture
def telemetry(tmp_path: Path) -> TelemetryLog:
    return TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))


@pytest.fixture
def server(tmp_path: Path, telemetry: TelemetryLog) -> Iterator[ThreadingHTTPServer]:
    publish_recorded(telemetry)
    with serve(tmp_path, BoardFeed(machines=MACHINES, keys=KEYS), telemetry=telemetry, clock=lambda: NOW) as server:
        yield server


def test_both_harnesses_sessions_are_served_with_the_slice_their_branch_names(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "?hours=24")

    assert status == 200
    assert {(s["harness"], s["task"], s["kind"]) for s in body["sessions"]} == {
        ("claude-code", "TASK-1", "headless"),
        ("codex", None, "headless"),
    }
    (slice_,) = body["slices"]
    assert (slice_["task"], slice_["sessions"], slice_["steps"], slice_["clean"]) == ("TASK-1", 1, 3, True)
    assert (body["now"], body["window_s"]) == (NOW, 24 * 3600)


def test_the_window_defaults_to_a_week_and_leaves_out_what_happened_before_it(server: ThreadingHTTPServer) -> None:
    _, week = _get(server)
    _, minutes = _get(server, "?hours=0.01")

    assert week["window_s"] == 168 * 3600
    assert (len(week["sessions"]), minutes["sessions"], minutes["slices"]) == (2, [], [])


def test_a_signal_published_after_the_view_was_first_read_shows_in_the_next_read(
    server: ThreadingHTTPServer, telemetry: TelemetryLog
) -> None:
    before = len(_get(server)[1]["sessions"])
    payload = {
        "resourceLogs": [
            {
                "resource": {"attributes": []},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "attributes": [
                                    {"key": "event.name", "value": {"stringValue": "user_prompt"}},
                                    {"key": "session.id", "value": {"stringValue": "late"}},
                                    {"key": "event.sequence", "value": {"intValue": "0"}},
                                    {"key": "event.timestamp", "value": {"stringValue": "2026-10-09T22:00:00Z"}},
                                ]
                            }
                        ]
                    }
                ],
            }
        ]
    }

    telemetry.publish(signals(payload))

    assert len(_get(server)[1]["sessions"]) == before + 1


def test_republishing_an_export_does_not_count_it_twice(server: ThreadingHTTPServer, telemetry: TelemetryLog) -> None:
    before = _get(server)[1]
    publish_recorded(telemetry)

    assert _get(server)[1]["slices"] == before["slices"]


@pytest.mark.parametrize("query", ["?hours=0", "?hours=-1", "?hours=soon", "?hours=nan", "?hours=inf"])
def test_a_window_that_is_not_a_positive_number_is_refused(server: ThreadingHTTPServer, query: str) -> None:
    status, body = _get(server, query)

    assert (status, "positive number" in body["error"]) == (400, True)


def test_an_instance_that_receives_no_telemetry_cannot_report_session_health(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(machines=MACHINES, keys=KEYS)) as server:
        status, body = _get(server)

    assert (status, "telemetry" in body["error"]) == (501, True)
