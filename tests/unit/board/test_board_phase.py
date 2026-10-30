"""A Board task reports the phase its In Progress machine is in, that phase's submachine state and when it reached Done."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from starpulse.board.model.view import board_columns, task_view

from tests.machines import ROLES

DONE_AT = 1792481914.0


def _agent(task: str, state: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": task,
        "task": task,
        "state": state,
        "title": task,
        "model": "",
        "milestone": "",
        "labels": [],
        "dependencies": [],
        "prs": [],
        "moves": {},
        **extra,
    }


def _snapshot() -> dict[str, Any]:
    links = [
        {"state": "build", "machine": "build"},
        {"state": "deliver", "machine": "deliver"},
        {"state": "deliver", "machine": "triaging-cr-reviews"},
    ]
    board = [
        _agent("T-1", "in_progress"),
        _agent("T-2", "in_progress"),
        _agent("T-3", "done", entered=DONE_AT),
        _agent("T-4", "in_progress"),
    ]
    return {
        "flows": [
            {
                "name": "board",
                "agents": board,
                "machine": {"states": [], "submachines": [{"state": "in_progress", "machine": "in-progress"}]},
            },
            {
                "name": "in-progress",
                "agents": [_agent("T-1", "deliver"), _agent("T-2", "worktree_ready"), _agent("T-3", "finalized")],
                "machine": {"states": [], "submachines": links},
            },
            {"name": "build", "agents": [_agent("T-1", "docs_reconciled")], "machine": {"states": []}},
            {
                "name": "deliver",
                "agents": [_agent("T-1", "pr_opened"), _agent("T-4", "pr_opened")],
                "machine": {"states": []},
            },
            {"name": "triaging-cr-reviews", "agents": [], "machine": {"states": []}},
        ],
        "pulls": {},
        "settled": {},
        "roles": ROLES.wire(),
    }


def _view(task: str) -> dict[str, Any]:
    snapshot = _snapshot()
    agent = next(a for a in snapshot["flows"][0]["agents"] if a["id"] == task)
    return task_view(agent, snapshot, set())


def test_phase_and_substate_follow_the_current_phase_subflow_only() -> None:
    view = _view("T-1")
    assert (view["phase"], view["substate"]) == ("deliver", "pr_opened")


def test_phase_without_a_subflow_has_no_substate() -> None:
    view = _view("T-2")
    assert (view["phase"], view["substate"]) == ("worktree_ready", None)


def test_done_task_reports_done_at_and_no_phase() -> None:
    view = _view("T-3")
    assert view["done_at"] == datetime.fromtimestamp(DONE_AT, UTC).isoformat()
    assert (view["phase"], view["substate"]) == (None, None)
    assert _view("T-1")["done_at"] is None


def test_task_held_only_by_a_subflow_reports_that_subflows_phase_and_state() -> None:
    view = _view("T-4")
    assert (view["phase"], view["substate"]) == ("deliver", "pr_opened")


def _view_of(snapshot: dict[str, Any], task: str) -> dict[str, Any]:
    agent = next(a for a in snapshot["flows"][0]["agents"] if a["id"] == task)
    return task_view(agent, snapshot, set())


def test_a_task_whose_phase_is_parked_reads_in_the_waiting_lane_and_not_the_in_progress_column() -> None:
    snapshot = _snapshot()
    snapshot["flows"][0]["agents"].append(_agent("T-5", "in_progress"))
    snapshot["flows"][0]["machine"]["states"] = [
        {"id": "in_progress", "name": "In Progress"},
        {"id": "waiting", "name": "Waiting"},
    ]
    snapshot["flows"][1]["agents"].append(_agent("T-5", "parked"))

    columns = {c["state"]: [t["id"] for t in c["tasks"]] for c in board_columns(snapshot, lambda agent: True)["columns"]}

    assert _view_of(snapshot, "T-5")["lane"] == "waiting"
    assert "T-5" not in columns["in_progress"]
    assert columns["waiting"] == ["T-5"]
    assert _view("T-1")["lane"] == "in_progress"
