"""The write routes are Starlette endpoints over the app's seams: a request reaches them through the app, and they answer
with the status, headers and body the page reads."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from starlette.testclient import TestClient
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.board_feed import BoardFeed
from starpulse.contracts.api.registry import REQUESTS
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.adapters.inbound.api import metrics
from starpulse.views.adapters.inbound.api.routing import Api, api_routes
from starpulse.views.adapters.inbound.asgi_app import PageApp
from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache
from starpulse.views.application.commands import guard as server_writes
from starpulse.views.ports.services import Services

from tests.fake_board import bare_board
from tests.unit.views.routing import handler_for, writes

_JSON = {"Content-Type": "application/json"}


def _unauthorised(auth: str | None, raw: bytes) -> tuple[int, dict]:
    return 401, {"error": f"auth={auth} body={raw.decode()}"}


@pytest.fixture
def feed() -> BoardFeed:
    return BoardFeed()


def _routes(feed: BoardFeed, tmp_path: Path, **pushes) -> Api:
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    window = HistoryWindow(feed, 6, log)
    unwritten = lambda *args, **kwargs: None  # noqa: E731 - a writer that answers nothing
    board = bare_board(writer=unwritten, assign=unwritten, read=unwritten, edit=unwritten)
    return Api(feed, HistoryStore("sqlite://", feed.machines), SnapshotCache(feed), window, board, Services(**pushes))


@pytest.fixture
def routes(feed: BoardFeed, tmp_path: Path) -> Api:
    return _routes(feed, tmp_path, scheduler=SimpleNamespace())


def _write(
    routes: Api,
    method: str,
    path: str,
    body: bytes = b"{}",
    headers: dict[str, str] | None = None,
    client: str = "127.0.0.1",
) -> httpx.Response:
    app = PageApp(api_routes(routes), metrics.routes, routes.snapshots, Path(__file__).parent, (), seams=routes)
    sent = {"Content-Length": str(len(body)), **(headers if headers is not None else _JSON)}
    return TestClient(app, client=(client, 50000)).request(method, path, content=body, headers=sent)


def test_a_write_from_another_page_is_refused_as_an_error_body(routes: Api) -> None:
    headers = {**_JSON, "Origin": "http://evil.example", "Host": "starpulse.lan"}

    response = _write(routes, "POST", "/api/move", headers=headers)

    assert response.status_code == 403
    assert "error" in response.json()


def test_a_write_that_is_not_json_is_a_415(routes: Api) -> None:
    response = _write(routes, "POST", "/api/move", headers={"Content-Type": "text/plain"})

    assert response.status_code == 415


def test_a_write_from_outside_the_lan_is_a_403(routes: Api) -> None:
    response = _write(routes, "POST", "/api/move", client="8.8.8.8")

    assert response.status_code == 403


_PUT_ROUTES = {"/api/scheduler", "/api/history-window"}


@pytest.mark.parametrize("path", [path for path in REQUESTS if path != "/api/insights"])
def test_a_body_its_request_model_rejects_is_a_400_naming_the_field(routes: Api, path: str) -> None:
    response = _write(routes, "PUT" if path in _PUT_ROUTES else "POST", path, body=b'{"unexpected": 1}')

    assert response.status_code == 400
    assert response.json() == {"error": "invalid request: unexpected: Extra inputs are not permitted"}


def test_a_task_write_answers_its_status(routes: Api) -> None:
    response = _write(routes, "POST", "/api/move", body=b"not json")

    assert response.status_code == 400


def test_a_put_of_the_history_window_is_guarded_like_a_post(routes: Api) -> None:
    headers = {**_JSON, "Origin": "http://evil.example", "Host": "starpulse.lan"}

    response = _write(routes, "PUT", "/api/history-window", headers=headers)

    assert response.status_code == 403


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/nothing"),
        ("GET", "/api/move"),
        ("PUT", "/api/move"),
        ("DELETE", "/api/move"),
        ("POST", "/api/runs/events"),  # the 0.4 shim, removed in 0.5
        ("POST", "/api/insights"),  # the engine push, removed
        ("DELETE", "/api/insights/abc"),  # removed with it: the window's DELETE, which is no such path
    ],
)
def test_a_method_and_path_that_are_no_write_route_are_left_to_the_server(routes: Api, method: str, path: str) -> None:
    assert _write(routes, method, path).status_code in {404, 405}


def test_a_push_reaches_its_ingest_with_the_token_and_the_whole_body(feed: BoardFeed, tmp_path: Path) -> None:
    routes = _routes(feed, tmp_path, pull_refresh=_unauthorised)

    response = _write(routes, "POST", "/api/pulls/refresh", body=b"payload", headers={"Authorization": "Bearer t"})

    assert response.status_code == 401
    assert "connection" not in response.headers
    assert response.json() == {"error": "auth=Bearer t body=payload"}


def test_a_push_over_its_limit_is_refused_unread_and_closes_the_connection(feed: BoardFeed, tmp_path: Path) -> None:
    routes = _routes(feed, tmp_path, pull_refresh=_unauthorised)

    response = _write(routes, "POST", "/api/pulls/refresh", body=b"x", headers={"Content-Length": str(10**9)})

    assert response.status_code == 413
    assert response.headers["connection"] == "close"


def test_an_unreadable_length_on_a_push_is_read_as_empty(feed: BoardFeed, tmp_path: Path) -> None:
    routes = _routes(feed, tmp_path, pull_refresh=_unauthorised)

    response = _write(routes, "POST", "/api/pulls/refresh", body=b"x", headers={"Content-Length": "many"})

    assert response.json() == {"error": "auth=None body="}


@pytest.mark.parametrize(
    ("path", "post_only"),
    [
        ("/api/move", True),
        ("/api/pulls/refresh", True),
        ("/api/insights", False),
        ("/api/runs/events", False),
        ("/api/run/instance/workflow", True),
        ("/api/runs/instance/workflow/rerun", True),
        ("/api/doctor", False),
        ("/", False),
    ],
)
def test_a_get_reaches_no_write_route(routes: Api, path: str, post_only: bool) -> None:
    table = writes(routes)

    assert handler_for(table, path, "GET") is None
    assert (handler_for(table, path, "POST") is not None) is post_only


def test_a_take_over_post_sends_the_update_to_the_tasks_workflow(feed: BoardFeed, tmp_path: Path) -> None:
    sent: list[str] = []

    def take_over(task: str) -> bool:
        sent.append(task)
        return True

    response = _write(_routes(feed, tmp_path, take_over=take_over), "POST", "/api/take-over", b'{"task": "TASK-7"}')

    assert (response.status_code, response.json(), sent) == (200, {"task": "TASK-7"}, ["TASK-7"])


def test_a_take_over_for_a_task_with_no_workflow_is_a_409(feed: BoardFeed, tmp_path: Path) -> None:
    routes = _routes(feed, tmp_path, take_over=lambda task: False)

    response = _write(routes, "POST", "/api/take-over", b'{"task": "TASK-7"}')

    assert response.status_code == 409
    assert "TASK-7" in response.json()["error"]


def test_a_take_over_on_a_board_without_workflows_is_a_404(feed: BoardFeed, tmp_path: Path) -> None:
    response = _write(_routes(feed, tmp_path), "POST", "/api/take-over", b'{"task": "TASK-7"}')

    assert response.status_code == 404


def test_a_write_the_replay_has_not_reached_is_a_503_asking_the_client_to_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(server_writes, "REPLAY_WAIT_S", 0.01)
    replaying = BoardFeed()
    replaying.await_stream()
    routes = _routes(replaying, tmp_path)
    body = json.dumps({"task": "PROJ-3", "base": {"title": "x"}, "changes": {"title": "y"}}).encode()

    response = _write(routes, "POST", "/api/edit", body=body)

    assert response.status_code == 503
    assert response.headers["retry-after"] == str(server_writes.RETRY_AFTER_S)


def test_a_write_the_server_refuses_for_another_reason_asks_for_no_retry(routes: Api) -> None:
    response = _write(routes, "POST", "/api/move", body=b"not json")

    assert "retry-after" not in response.headers
