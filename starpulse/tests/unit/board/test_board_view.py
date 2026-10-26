"""The Board's columns view reads the board a fixed number of times, however many tasks it holds."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from starpulse.board.model.view import board_columns, board_flow, cold_agent, done_ids, task_view
from starpulse.cli.agent_keys import TASK_KEYS
from starpulse.tests.machines import ROLES


class _CountedAgents(list):
    """A board's agents that count each full pass over them."""

    passes = 0

    def __iter__(self) -> Iterator[Any]:
        type(self).passes += 1
        return super().__iter__()


def _snapshot(tasks: int) -> dict[str, Any]:
    agents = _CountedAgents(
        {
            "id": f"T-{n}",
            "title": f"task {n}",
            "state": "done" if n % 2 else "ready",
            "model": "",
            "milestone": "",
            "labels": [],
            "dependencies": [f"T-{n - 1}"] if n else [],
            "prs": [],
            "moves": {},
        }
        for n in range(tasks)
    )
    states = [{"id": "ready", "name": "Ready"}, {"id": "done", "name": "Done"}]
    return {"flows": [{"name": "board", "agents": agents, "machine": {"states": states}}], "pulls": {}, "settled": {}, "roles": ROLES.wire()}


def _passes(tasks: int) -> int:
    _CountedAgents.passes = 0
    board_columns(_snapshot(tasks), lambda agent: True)
    return _CountedAgents.passes


def test_board_columns_passes_over_the_board_as_often_for_many_tasks_as_for_few() -> None:
    assert _passes(200) == _passes(2)


def test_board_columns_still_reports_each_undone_dependency_as_waiting() -> None:
    columns = board_columns(_snapshot(3), lambda agent: True)["columns"]
    waiting = {task["id"]: task["waiting_on"] for column in columns for task in column["tasks"]}
    assert waiting == {"T-0": [], "T-1": ["T-0"], "T-2": []}


def test_a_cold_done_task_is_done_to_a_dependent_and_a_verb_view_loads_its_full_fields_from_the_record() -> None:
    waiting = {**_snapshot(1)["flows"][0]["agents"][0], "id": "T-9", "state": "ready", "dependencies": ["T-cold"]}
    snapshot = {"flows": [{"name": "board", "agents": [waiting]}], "pulls": {}, "settled": {}, "roles": ROLES.wire(), "cold_done": ["T-cold"]}
    record = {
        "title": "Old work",
        "type": "story",
        "profile": "@agent-a",
        "labels": ["x"],
        "milestone": "m-1",
        "dependencies": [],
        "description": "Long ago.",
        "acceptanceCriteria": [{"n": 1, "text": "ships", "checked": True}],
    }

    cold = cold_agent("T-cold", record, "done")

    assert done_ids(snapshot) == {"T-cold"}
    assert task_view(waiting, snapshot)["waiting_on"] == []
    assert task_view(cold, snapshot) == {
        "id": "T-cold",
        "title": "Old work",
        "lane": "done",
        "phase": None,
        "substate": None,
        "skill": None,
        "interactive": False,
        "done_at": None,
        "profile": "@agent-a",
        "assignee": "",
        "milestone": "m-1",
        "type": "story",
        "labels": ["x"],
        "dependencies": [],
        "waiting_on": [],
        "criteria": [{"text": "ships", "checked": True}],
        "pause_reason": "",
        "prs": [],
        "moves": {},
        "rating": None,
        "released": None,
    }
    assert cold["description"] == "Long ago."


def test_a_task_whose_claim_was_released_serves_the_release_and_the_cli_lists_it() -> None:
    snapshot = _working_board()
    release = {"at": "2026-10-24T13:00:00Z", "session": "s-1", "last_renewal": "2026-10-24T12:00:00Z", "ttl": 3600}
    released = {**board_flow(snapshot)["agents"][0], "state": ROLES.wire()["waiting"], "released": release}
    assert task_view(released, snapshot)["released"] == release
    assert "released" in TASK_KEYS


def _working_board(*, next_edge: dict[str, str] | None = None, interactive: bool = False) -> dict[str, Any]:
    """A board with one In Progress task, T-1, in the `deliver` phase of `in-progress`, at `pushed` in the `deliver` skill."""
    roles = ROLES.wire()
    task = {"id": "T-1", "title": "task 1", "state": roles["working"], "model": "", "milestone": "", "labels": [], "dependencies": [], "prs": [], "moves": {}}
    board = {"name": "board", "machine": {"states": [], "submachines": [{"state": roles["working"], "machine": "in-progress"}]}, "agents": [task]}
    in_progress = {"name": "in-progress", "machine": {"states": [], "submachines": [{"state": "deliver", "machine": "deliver"}]}, "agents": [{"task": "T-1", "state": "deliver"}]}
    states = [{"id": state} for state in ("committed", "pushed", "pr_opened")]
    deliver = {"name": "deliver", "machine": {"states": states, "transitions": [], "next": next_edge}, "agents": [{"task": "T-1", "state": "pushed"}]}
    return {"flows": [board, in_progress, deliver], "pulls": {}, "settled": {}, "roles": roles, "interactive": {"T-1": interactive}}


def test_a_held_in_progress_task_serves_its_skill_and_its_interactive_flag() -> None:
    snapshot = _working_board(next_edge={"kind": "skill", "name": "review-fix"}, interactive=True)
    held = task_view(board_flow(snapshot)["agents"][0], snapshot)
    assert held["skill"] == {
        "name": "deliver",
        "states": ["committed", "pushed", "pr_opened"],
        "current": "pushed",
        "next": {"kind": "skill", "name": "review-fix"},
    }
    assert held["interactive"] is True


def test_a_task_outside_a_skill_serves_no_skill_and_is_not_interactive() -> None:
    snapshot = _working_board()
    ready = {**board_flow(snapshot)["agents"][0], "state": ROLES.wire()["waiting"]}
    held = task_view(ready, snapshot)
    assert (held["skill"], held["interactive"]) == (None, False)
