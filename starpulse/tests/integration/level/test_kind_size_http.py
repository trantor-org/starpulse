"""GET /api/analytics/transitions and /api/analytics/cells against recorded exports published to the event log."""

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
NOW = datetime.fromisoformat("2026-10-09T22:30:00+00:00").timestamp()
ROUTES = pytest.mark.parametrize("route", ["transitions", "cells", "graph", "diff", "stages"])


def _get(server: ThreadingHTTPServer, route: str, query: str = "") -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/analytics/{route}{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    telemetry = TelemetryLog(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    for name in ("claude_code/otlp.ndjson", "codex/otlp.ndjson"):
        for line in (FIXTURES / name).read_text().splitlines():
            telemetry.publish(signals(json.loads(line)))
    with serve(tmp_path, BoardFeed(machines=MACHINES, keys=KEYS), telemetry=telemetry, clock=lambda: NOW) as server:
        yield server


@ROUTES
def test_a_report_with_no_labelled_task_is_empty_inside_the_history(server: ThreadingHTTPServer, route: str) -> None:
    hours = 0.5 if route == "stages" else 1.06  # stages also reads the window before
    status, body = _get(server, route, f"?hours={hours}")

    assert (status, body) == (200, {"now": NOW, "window_s": hours * 3600, route: []})


def test_the_stages_report_needs_the_history_to_hold_the_window_before_too(server: ThreadingHTTPServer) -> None:
    status, body = _get(server, "stages", "?hours=1.06")

    assert (status, "longer than the history" in body["error"]) == (400, True)


@ROUTES
def test_a_window_past_the_history_or_that_is_no_positive_number_is_refused(
    server: ThreadingHTTPServer, route: str
) -> None:
    past, longer = _get(server, route, "?hours=24")
    bad, _ = _get(server, route, "?hours=0")

    assert (past, bad, "longer than the history" in longer["error"]) == (400, 400, True)


@ROUTES
def test_an_instance_that_receives_no_telemetry_cannot_report(tmp_path: Path, route: str) -> None:
    with serve(tmp_path, BoardFeed(machines=MACHINES, keys=KEYS)) as server:
        status, body = _get(server, route)

    assert (status, "telemetry" in body["error"]) == (501, True)
