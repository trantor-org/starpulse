"""The read routes are Starlette endpoints over the app's seams: a request reaches them through the app, and they answer
with the status, headers and body the page reads."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.adapters.inbound.api import metrics
from starpulse.views.adapters.inbound.api.routing import Api, api_routes
from starpulse.views.adapters.inbound.asgi_app import PageApp
from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache
from starpulse.views.application.queries.responses import cited_pulls
from starpulse.views.ports.services import Services

from tests.fake_board import bare_board
from tests.unit.views.routing import handler_for, reads


@pytest.fixture
def routes(tmp_path: Path) -> Api:
    feed = BoardFeed()  # the history is a file: a worker thread reads it, and an in-memory store is per thread
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    return Api(
        feed=feed,
        history=HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", feed.machines),
        snapshots=SnapshotCache(feed),
        window=HistoryWindow(feed, 6, log),
        board=bare_board(),
        services=Services(slow_read_s=0.0),
    )


@pytest.fixture
def client(routes: Api, tmp_path: Path) -> TestClient:
    app = PageApp(api_routes(routes), metrics.routes, routes.snapshots, tmp_path, (), seams=routes)
    return TestClient(app, client=("127.0.0.1", 50000))  # a LAN client, as the window and the writes admit


def test_a_read_route_answers_its_body_and_status(client: TestClient) -> None:
    response = client.get("/api/doctor")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"ok": True, "checks": []}


def test_a_missing_record_answers_its_status(client: TestClient) -> None:
    assert client.get("/api/task/PROJ-404").status_code == 404


# What each read route answers over an empty board and no optional service, by its path template.
_NOT_FOUND = {
    "/api/docs/{id:path}",
    "/api/docs",
    "/api/done",
    "/api/events/body/{key:path}",
    "/api/ledger/{rest:path}",
    "/api/milestones/{id:path}",
    "/api/milestones",
    "/api/retired",
    "/api/scheduler",
    "/api/search",
    "/api/task/{id:path}",
}


def _expected(path: str) -> int:
    if path in _NOT_FOUND:
        return 404
    if path == "/api/history":
        return 400  # it needs a `since`
    return 501 if path.startswith("/api/analytics/") and path != "/api/analytics/health" else 200  # no telemetry


def test_every_read_route_answers_its_status_with_a_cache_header(routes: Api, client: TestClient) -> None:
    answered = {}
    for path, _ in reads(routes):
        response = client.get(re.sub(r"\{[^}]*\}", "x", path))
        answered[path] = (response.status_code, response.headers.get("cache-control"))

    assert answered == {path: (_expected(path), "no-store") for path, _ in reads(routes) if path != "/metrics"} | {
        "/metrics": (200, "no-store")
    }


class _Pulls:
    def __init__(self, records: list[dict]) -> None:
        self.records = records

    def find(self, repo: str, number: int, **_) -> list[dict]:
        return [record for record in self.records if (record["repo"], record["number"]) == (repo, number)]


def test_a_task_record_carries_each_cited_pull_request_without_its_body() -> None:
    store = _Pulls([{"repo": "trantor-org/starpulse", "number": 932, "state": "MERGED", "checks": "pass", "body": "x"}])

    cited = cited_pulls(
        store,
        [
            "https://github.com/trantor-org/starpulse/pull/932",
            "https://github.com/trantor-org/starpulse/pull/978",
            "TASK-8683",
        ],
    )

    assert cited == [{"repo": "trantor-org/starpulse", "number": 932, "state": "MERGED", "checks": "pass"}]


def test_no_pull_store_cites_no_pull_requests() -> None:
    assert cited_pulls(None, ["https://github.com/trantor-org/starpulse/pull/932"]) == []


def test_metrics_answers_prometheus_text(client: TestClient) -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"


def test_a_query_reaches_the_route(routes: Api, client: TestClient) -> None:
    identity = {"accept-encoding": "identity"}
    held = client.get("/api/snapshot", headers=identity)
    full = client.get("/api/snapshot", params={"view": "full"}, headers=identity)

    assert held.content == routes.snapshots.read().encoded.body  # the snapshot as the cache holds it
    assert full.content != held.content  # `view=full` encodes the whole snapshot afresh


def test_a_head_of_a_read_route_answers_its_headers_without_a_body(client: TestClient) -> None:
    response = client.head("/api/doctor", headers={"accept-encoding": "identity"})

    assert response.status_code == 200
    assert response.content == b""
    assert response.headers["content-length"] == str(len(client.get("/api/doctor").content))


def test_the_history_window_answers_a_lan_client(client: TestClient) -> None:
    assert client.get("/api/history-window").status_code == 200


@pytest.mark.parametrize(
    "path",
    [
        "/api/events",  # a stream, not a read
        "/api/held",
        "/api/lanes",
        "/api/move",  # a write: a GET of it is the server's 405
        "/",  # the page
        "/assets/app.js",  # a static file
        "/nothing",
    ],
)
def test_a_path_that_is_no_read_route_is_left_to_the_server(routes: Api, path: str) -> None:
    assert handler_for(reads(routes), path) is None


def test_a_get_of_a_write_path_is_the_servers_405(client: TestClient) -> None:
    assert client.get("/api/move").status_code == 405


def test_a_get_of_a_milestone_write_path_is_the_milestone_read_of_that_id(client: TestClient) -> None:
    assert client.get("/api/milestones/edit").status_code == 404


def test_the_pulls_read_is_timed_and_any_other_is_not(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("WARNING")

    assert client.get("/api/doctor").status_code == 200
    assert "slow_read" not in caplog.text

    assert client.get("/api/pulls").status_code == 200
    assert "slow_read route=/api/pulls" in caplog.text


def test_a_slow_task_read_logs_its_queue_and_compute_seconds(
    routes, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("WARNING")
    app = PageApp(api_routes(routes), [], routes.snapshots, tmp_path, ())

    assert asyncio.run(call(app, "/api/task/PROJ-404")).status == 404

    (line,) = [r.getMessage() for r in caplog.records if "slow_read" in r.getMessage()]
    assert line.startswith("slow_read route=/api/task query=PROJ-404 queue_s=")
    assert " compute_s=" in line
