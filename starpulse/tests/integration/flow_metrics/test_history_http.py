"""GET /api/history against StarPulse's own store: a task's whole path on the Board and on one machine."""

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse._internal.server.page_server import PageServer
from starpulse.flow_metrics.history import HistoryStore
from starpulse.tests.machines import MACHINES, ROLES


def _get(server: PageServer, query: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url(server, f"/api/history{query}"), timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.fixture
def server(tmp_path: Path) -> Iterator[PageServer]:
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
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), history=store) as server:
        yield server


def test_a_task_answers_its_lane_changes(server: PageServer) -> None:
    assert _get(server, "?task=PROJ-7") == (
        200,
        {
            "task": "PROJ-7",
            "path": [{"at": 200.0, "from": None, "to": "waiting"}, {"at": 201.0, "from": "waiting", "to": "ready"}],
        },
    )


def test_a_task_and_flow_answer_that_machines_path_with_its_step_total(server: PageServer) -> None:
    assert _get(server, "?task=PROJ-7&machine=in-progress") == (
        200,
        {
            "task": "PROJ-7",
            "machine": "in-progress",
            "path": [
                {"at": 100.0, "event": "WORKTREE_READY", "state": "worktree_ready"},
                {"at": 101.0, "event": "RED_PROVEN", "state": "red_proven"},
            ],
            "steps": 2,
        },
    )


def test_an_unknown_task_answers_an_empty_path(server: PageServer) -> None:
    assert _get(server, "?task=PROJ-404") == (200, {"task": "PROJ-404", "path": []})
    assert _get(server, "?task=PROJ-404&machine=in-progress") == (
        200,
        {"task": "PROJ-404", "machine": "in-progress", "path": [], "steps": 0},
    )


def test_a_request_without_a_task_is_refused(server: PageServer) -> None:
    refused = (400, {"error": "history needs ?task=TASK-N"})

    assert [_get(server, query) for query in ("", "?flow=in-progress", "?task=")] == [refused] * 3


def test_an_unknown_flow_is_not_found(server: PageServer) -> None:
    assert _get(server, "?task=PROJ-7&machine=nope") == (404, {"error": "unknown machine nope"})


def test_a_lane_change_answers_the_actor_that_made_it(tmp_path: Path) -> None:
    store = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", MACHINES)
    store.record_lane("l0", "PROJ-8", "Ready", 300.0, actor="starpulse/task-actor")
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES), history=store) as server:
        assert _get(server, "?task=PROJ-8") == (
            200,
            {"task": "PROJ-8", "path": [{"at": 300.0, "from": None, "to": "ready", "by": "starpulse/task-actor"}]},
        )
