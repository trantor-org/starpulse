"""GET /api/history against StarPulse's own store: a task's whole path on the Board and on one machine."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from starpulse.api.adapter_kit import serve, url
from starpulse.projections.board_feed import BoardFeed
from starpulse.store.history import HistoryStore
from starpulse.tests.machines import MACHINES


def _get(server: ThreadingHTTPServer, query: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/history{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def server(tmp_path: Path) -> Iterator[ThreadingHTTPServer]:
    """A server whose history is a SQLite file beside its config."""
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    for i, event in enumerate(["WORKTREE_READY", "RED_PROVEN"]):
        store.record_machine(
            f"m{i}-0",
            {"event_id": f"m{i}", "machine": "in-progress", "event": event, "task": "PROJ-7", "time": 100.0 + i},
        )
    store.record_machine(
        "m9-0", {"event_id": "m9", "machine": "authoring-skills", "event": "START", "run": "run-1", "time": 1}
    )
    for i, status in enumerate(("Waiting", "Ready")):
        store.record_lane(f"l{i}", "PROJ-7", status, 200.0 + i)
    with serve(tmp_path, BoardFeed(machines=MACHINES), history=store) as server:
        yield server


def test_a_task_answers_its_lane_changes(server: ThreadingHTTPServer) -> None:
    assert _get(server, "?task=PROJ-7") == (
        200,
        {
            "task": "PROJ-7",
            "path": [{"at": 200.0, "from": None, "to": "Waiting"}, {"at": 201.0, "from": "Waiting", "to": "Ready"}],
        },
    )


def test_a_task_and_flow_answer_that_machines_path_with_its_step_total(server: ThreadingHTTPServer) -> None:
    assert _get(server, "?task=PROJ-7&flow=in-progress") == (
        200,
        {
            "task": "PROJ-7",
            "flow": "in-progress",
            "path": [
                {"at": 100.0, "event": "WORKTREE_READY", "state": "worktree_ready"},
                {"at": 101.0, "event": "RED_PROVEN", "state": "red_proven"},
            ],
            "steps": 2,
        },
    )


def test_an_unknown_task_answers_an_empty_path(server: ThreadingHTTPServer) -> None:
    assert _get(server, "?task=PROJ-404") == (200, {"task": "PROJ-404", "path": []})
    assert _get(server, "?task=PROJ-404&flow=in-progress") == (
        200,
        {"task": "PROJ-404", "flow": "in-progress", "path": [], "steps": 0},
    )


def test_a_request_without_a_task_is_refused(server: ThreadingHTTPServer) -> None:
    refused = (400, {"error": "history needs ?task=TASK-N"})

    assert [_get(server, query) for query in ("", "?flow=in-progress", "?task=")] == [refused] * 3


def test_an_unknown_flow_is_not_found(server: ThreadingHTTPServer) -> None:
    assert _get(server, "?task=PROJ-7&flow=nope") == (404, {"error": "unknown flow nope"})
