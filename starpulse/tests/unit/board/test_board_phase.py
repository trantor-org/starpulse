"""A Board task reports the phase its In Progress machine is in, that phase's submachine state and when it reached Done."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from starpulse._internal.board.view import task_view
from starpulse.tests.machines import ROLES

DONE_AT = 1792481914.0


def _agent(task: str, state: str, **extra: Any) -> dict[str, Any]:
    return {"id": task, "task": task, "state": state, "title": task, "model": "", "milestone": "", "labels": [],
            "dependencies": [], "prs": [], "moves": {}, **extra}


def _snapshot() -> dict[str, Any]:
    links = [
        {"state": "build", "machine": "build"},
        {"state": "deliver", "machine": "deliver"},
        {"state": "deliver", "machine": "triaging-cr-reviews"},
    ]
    board = [_agent("T-1", "in_progress"), _agent("T-2", "in_progress"), _agent("T-3", "done", entered=DONE_AT),
             _agent("T-4", "in_progress")]
    return {
        "flows": [
            {"name": "board", "agents": board, "machine": {"states": [], "submachines": [{"state": "in_progress", "machine": "in-progress"}]}},
            {"name": "in-progress", "agents": [_agent("T-1", "deliver"), _agent("T-2", "worktree_ready"),
                                               _agent("T-3", "finalized")], "machine": {"submachines": links}},
            {"name": "build", "agents": [_agent("T-1", "docs_reconciled")], "machine": {}},
            {"name": "deliver", "agents": [_agent("T-1", "pr_opened"), _agent("T-4", "pr_opened")], "machine": {}},
            {"name": "triaging-cr-reviews", "agents": [], "machine": {}},
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
