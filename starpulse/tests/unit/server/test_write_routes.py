"""The write routes answer a `WriteRequest` with a `Response` and no socket, so any server can call them."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.history_window import HistoryWindow
from starpulse._internal.server.reads import Response
from starpulse._internal.server.services import Services
from starpulse._internal.server.write_routes import WriteRequest, WriteRoutes
from starpulse.contracts.api.registry import REQUESTS
from starpulse.event_log.event_log import EventLog
from starpulse.tests.fake_board import bare_board

_JSON = {"Content-Type": "application/json"}


def _unauthorised(auth: str | None, raw: bytes) -> tuple[int, dict]:
    return 401, {"error": f"auth={auth} body={raw.decode()}"}


@pytest.fixture
def feed() -> BoardFeed:
    return BoardFeed()


def _routes(feed: BoardFeed, tmp_path: Path, **pushes) -> WriteRoutes:
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    window = HistoryWindow(feed, 6, log, tmp_path / "starpulse-settings.json")
    unwritten = lambda *args, **kwargs: None  # noqa: E731 - a writer that answers nothing
    return WriteRoutes(feed, window, bare_board(writer=unwritten, assign=unwritten), Services(**pushes))


@pytest.fixture
def routes(feed: BoardFeed, tmp_path: Path) -> WriteRoutes:
    return _routes(feed, tmp_path, scheduler=SimpleNamespace())


def _write(
    routes: WriteRoutes,
    method: str,
    path: str,
    body: bytes = b"{}",
    headers: dict[str, str] | None = None,
    client: str = "127.0.0.1",
) -> Response | None:
    sent = {"Content-Length": str(len(body)), **(headers if headers is not None else _JSON)}
    return routes(WriteRequest(method, path, client, sent, lambda size: body[:size]))


def _json(response: Response) -> dict:
    return json.loads(response.body)


def test_a_write_from_another_page_is_refused_as_an_error_body(routes: WriteRoutes) -> None:
    headers = {**_JSON, "Origin": "http://evil.example", "Host": "starpulse.lan"}

    response = _write(routes, "POST", "/api/move", headers=headers)

    assert response is not None
    assert response.status == 403
    assert "error" in _json(response)


def test_a_write_that_is_not_json_is_a_415(routes: WriteRoutes) -> None:
    response = _write(routes, "POST", "/api/move", headers={"Content-Type": "text/plain"})

    assert response is not None
    assert response.status == 415


def test_a_write_from_outside_the_lan_is_a_403(routes: WriteRoutes) -> None:
    response = _write(routes, "POST", "/api/move", client="8.8.8.8")

    assert response is not None
    assert response.status == 403


_PUT_ROUTES = {"/api/scheduler", "/api/history-window"}


@pytest.mark.parametrize("path", [path for path in REQUESTS if path != "/api/insights"])
def test_a_body_its_request_model_rejects_is_a_400_naming_the_field(routes: WriteRoutes, path: str) -> None:
    response = _write(routes, "PUT" if path in _PUT_ROUTES else "POST", path, body=b'{"unexpected": 1}')

    assert response is not None
    assert response.status == 400
    assert _json(response) == {"error": "invalid request: unexpected: Extra inputs are not permitted"}


def test_a_task_write_answers_its_status(routes: WriteRoutes) -> None:
    response = _write(routes, "POST", "/api/move", body=b"not json")

    assert response is not None
    assert response.status == 400


def test_a_put_of_the_history_window_is_guarded_like_a_post(routes: WriteRoutes) -> None:
    headers = {**_JSON, "Origin": "http://evil.example", "Host": "starpulse.lan"}

    response = _write(routes, "PUT", "/api/history-window", headers=headers)

    assert response is not None
    assert response.status == 403


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
def test_a_method_and_path_that_are_no_write_route_are_left_to_the_server(
    routes: WriteRoutes, method: str, path: str
) -> None:
    assert _write(routes, method, path) is None


def test_a_push_reaches_its_ingest_with_the_token_and_the_whole_body(feed: BoardFeed, tmp_path: Path) -> None:
    routes = _routes(feed, tmp_path, pull_refresh=_unauthorised)

    response = _write(routes, "POST", "/api/pulls/refresh", body=b"payload", headers={"Authorization": "Bearer t"})

    assert response is not None
    assert response.status == 401
    assert response.close is False
    assert _json(response) == {"error": "auth=Bearer t body=payload"}


def test_a_push_over_its_limit_is_refused_unread_and_closes_the_connection(feed: BoardFeed, tmp_path: Path) -> None:
    routes = _routes(feed, tmp_path, pull_refresh=_unauthorised)

    def unread(size: int) -> bytes:
        raise AssertionError("an oversized body is not read")

    request = WriteRequest("POST", "/api/pulls/refresh", "127.0.0.1", {"Content-Length": str(10**9)}, unread)
    response = routes(request)

    assert response is not None
    assert response.status == 413
    assert response.close is True


def test_an_unreadable_length_on_a_push_is_read_as_empty(feed: BoardFeed, tmp_path: Path) -> None:
    routes = _routes(feed, tmp_path, pull_refresh=_unauthorised)
    request = WriteRequest(
        "POST", "/api/pulls/refresh", "127.0.0.1", {"Content-Length": "many"}, lambda size: b"x" * size
    )

    response = routes(request)

    assert response is not None
    assert _json(response) == {"error": "auth=None body="}


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
def test_post_only_names_the_paths_a_get_is_refused(routes: WriteRoutes, path: str, post_only: bool) -> None:
    assert routes.post_only(path) is post_only


def test_a_take_over_post_sends_the_update_to_the_tasks_workflow(feed: BoardFeed, tmp_path: Path) -> None:
    sent: list[str] = []

    def take_over(task: str) -> bool:
        sent.append(task)
        return True

    response = _write(_routes(feed, tmp_path, take_over=take_over), "POST", "/api/take-over", b'{"task": "TASK-7"}')

    assert response is not None
    assert (response.status, _json(response), sent) == (200, {"task": "TASK-7"}, ["TASK-7"])


def test_a_take_over_for_a_task_with_no_workflow_is_a_409(feed: BoardFeed, tmp_path: Path) -> None:
    routes = _routes(feed, tmp_path, take_over=lambda task: False)

    response = _write(routes, "POST", "/api/take-over", b'{"task": "TASK-7"}')

    assert response is not None
    assert response.status == 409
    assert "TASK-7" in _json(response)["error"]


def test_a_take_over_on_a_board_without_workflows_is_a_404(feed: BoardFeed, tmp_path: Path) -> None:
    response = _write(_routes(feed, tmp_path), "POST", "/api/take-over", b'{"task": "TASK-7"}')

    assert response is not None
    assert response.status == 404
