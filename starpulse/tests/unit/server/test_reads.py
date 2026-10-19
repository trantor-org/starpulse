"""The read routes answer a `Request` with a `Response` and no socket, so any server can call them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.history_window import HistoryWindow
from starpulse._internal.server.compression import Encoded
from starpulse._internal.server.reads import Arrival, ReadRoutes, Request, Response
from starpulse._internal.server.snapshot_cache import SnapshotCache


@pytest.fixture
def routes(tmp_path: Path):
    feed = BoardFeed()
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    return ReadRoutes(
        feed=feed,
        history=HistoryStore("sqlite://", feed.machines),
        snapshots=SnapshotCache(feed),
        window=HistoryWindow(feed, 6, log, tmp_path / "starpulse-settings.json"),
        slow_read_s=0.0,
    )


def _get(routes, path: str, query: str = "") -> Response | None:
    return routes(Request(path, query, "127.0.0.1"))


def _json(response: Response) -> dict:
    body = response.body.body if isinstance(response.body, Encoded) else response.body
    return json.loads(body)


def test_a_read_route_answers_its_body_and_status(routes) -> None:
    response = _get(routes, "/api/doctor")

    assert response is not None
    assert response.status == 200
    assert response.content_type == "application/json"
    assert _json(response) == {"ok": True, "checks": []}


def test_a_missing_record_answers_its_status(routes) -> None:
    response = _get(routes, "/api/task/PROJ-404")

    assert response is not None
    assert response.status == 404


def test_metrics_answers_prometheus_text(routes) -> None:
    response = _get(routes, "/metrics")

    assert response is not None
    assert response.content_type == "text/plain; version=0.0.4; charset=utf-8"


def test_a_query_reaches_the_route(routes) -> None:
    held = _get(routes, "/api/snapshot")
    full = _get(routes, "/api/snapshot", "view=full")

    assert held is not None
    assert isinstance(held.body, Encoded)  # the snapshot as the cache holds it, gzipped
    assert full is not None
    assert isinstance(full.body, bytes)  # `view=full` encodes the whole snapshot afresh


def test_the_history_window_answers_a_lan_client(routes) -> None:
    response = routes(Request("/api/history-window", "", "127.0.0.1"))

    assert response is not None
    assert response.status == 200


@pytest.mark.parametrize(
    "path",
    [
        "/api/events",  # a stream, not a read
        "/api/held",
        "/api/lanes",
        "/api/ledger/anything/events",
        "/api/move",  # a write: a GET of it is the server's 405
        "/api/milestones/edit",
        "/",  # the page
        "/assets/app.js",  # a static file
        "/nothing",
    ],
)
def test_a_path_that_is_no_read_route_is_left_to_the_server(routes, path: str) -> None:
    assert _get(routes, path) is None


def test_the_pulls_read_is_timed_and_any_other_is_not(routes, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")
    with routes.watch(Request("/api/doctor", "", "127.0.0.1"), 0.0, Arrival(0.0)) as timing:
        timing.computed()
    assert "slow_read" not in caplog.text

    with routes.watch(Request("/api/pulls", "", "127.0.0.1"), 0.0, Arrival(0.0)) as timing:
        timing.computed()
    assert "slow_read route=/api/pulls" in caplog.text
