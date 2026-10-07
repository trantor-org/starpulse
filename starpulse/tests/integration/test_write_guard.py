"""A web page the operator opens must not write to the server through the operator's own browser."""

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from starpulse import server as server_module
from starpulse.adapter_kit import serve as _serve
from starpulse.adapter_kit import task
from starpulse.adapter_kit import url as _url
from starpulse.board import Written
from starpulse.board_feed import BoardFeed
from starpulse.contracts.adapters import Move
from starpulse.settings.history_window import HistoryWindow

_FOREIGN = "https://evil.example"
#: Every route that writes, as (method, path, body): a refused request must reach none of their writers.
_WRITES = [
    ("POST", "/api/run/dagu/nightly", {}),
    ("POST", "/api/move", {"task": "PROJ-3", "to": "in_progress"}),
    ("POST", "/api/start", {"task": "PROJ-3", "assignee": "@agent-deep-high"}),
    ("POST", "/api/edit", {"task": "PROJ-3", "base": {}, "changes": {"title": "x"}}),
    ("POST", "/api/archive", {"task": "PROJ-3", "reason": "obsolete"}),
    ("POST", "/api/tasks", {"title": "from a stranger"}),
    ("PUT", "/api/history-window", {"hours": 24}),
    ("DELETE", "/api/history-window", {}),
]


def _send(
    server: ThreadingHTTPServer, method: str, path: str, body: dict, headers: dict[str, str]
) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(_url(server, path), data=json.dumps(body).encode(), method=method)
    for name, value in headers.items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=5) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


@contextmanager
def _recording(tmp_path: Path) -> Iterator[tuple[ThreadingHTTPServer, list[str], HistoryWindow]]:
    """A server whose every writer notes its name in the list, over one task a move may touch."""
    calls: list[str] = []

    def noting(name: str, result: Any) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return result

        return call

    feed = BoardFeed()
    feed.put(task("PROJ-3", "Ready", moves={"in_progress": Move(allowed=True)}))
    window = HistoryWindow(feed, 6, tmp_path / "starpulse-settings.json")
    with _serve(
        tmp_path,
        feed,
        starts={"dagu": noting("run", "run-1")},
        run_safe=frozenset({"dagu/nightly"}),
        writer=noting("move", Written(True, "ok")),
        assign=noting("assign", Written(True, "ok")),
        start_session=noting("session", "s-1"),
        window=window,
        read=noting("read", {"id": "PROJ-3"}),
        edit=noting("edit", Written(True, "ok")),
        archive=noting("archive", Written(True, "ok")),
        create=noting("create", Written(True, "ok")),
    ) as server:
        yield server, calls, window


@pytest.mark.parametrize(("method", "path", "body"), _WRITES)
def test_a_cross_site_form_post_reaches_no_writer(tmp_path: Path, method: str, path: str, body: dict) -> None:
    headers = {"Content-Type": "text/plain", "Origin": _FOREIGN}
    with _recording(tmp_path) as (server, calls, window):
        status, _ = _send(server, method, path, body, headers)

    assert status in {403, 415}
    assert calls == []
    assert window.state()["overridden"] is False


@pytest.mark.parametrize(("method", "path", "body"), _WRITES)
def test_a_foreign_origin_is_refused_even_with_a_json_content_type(
    tmp_path: Path, method: str, path: str, body: dict
) -> None:
    with _recording(tmp_path) as (server, calls, _):
        status, answer = _send(server, method, path, body, {"Content-Type": "application/json", "Origin": _FOREIGN})

    assert (status, calls) == (403, [])
    assert "origin" in answer["error"].lower()


@pytest.mark.parametrize(("method", "path", "body"), _WRITES)
def test_a_write_that_is_not_json_is_refused_even_with_no_origin(
    tmp_path: Path, method: str, path: str, body: dict
) -> None:
    with _recording(tmp_path) as (server, calls, _):
        status, _answer = _send(server, method, path, body, {"Content-Type": "text/plain"})

    assert (status, calls) == (415, [])


def test_a_same_origin_json_post_is_written(tmp_path: Path) -> None:
    with _recording(tmp_path) as (server, calls, _):
        own = f"http://127.0.0.1:{server.server_port}"
        status, answer = _send(
            server, "POST", "/api/move", _WRITES[1][2], {"Content-Type": "application/json", "Origin": own}
        )

    assert (status, answer, calls) == (200, {"task": "PROJ-3", "to": "in_progress"}, ["move"])


def test_a_json_post_with_no_origin_header_is_written_as_the_cli_sends_it(tmp_path: Path) -> None:
    with _recording(tmp_path) as (server, calls, _):
        status, answer = _send(server, "POST", "/api/move", _WRITES[1][2], {"Content-Type": "application/json"})

    assert (status, answer, calls) == (200, {"task": "PROJ-3", "to": "in_progress"}, ["move"])


def test_a_json_content_type_with_a_charset_is_json(tmp_path: Path) -> None:
    headers = {"Content-Type": "application/json; charset=utf-8"}
    with _recording(tmp_path) as (server, calls, _):
        status, _answer = _send(server, "POST", "/api/move", _WRITES[1][2], headers)

    assert (status, calls) == (200, ["move"])


def test_serve_listens_on_loopback_unless_a_host_is_given() -> None:
    parser = server_module.serve_parser()

    assert parser.parse_args([]).host == "127.0.0.1"
    assert parser.parse_args(["--host", "0.0.0.0"]).host == "0.0.0.0"
