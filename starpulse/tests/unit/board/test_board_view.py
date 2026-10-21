"""The Board's columns view reads the board a fixed number of times, however many tasks it holds."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from starpulse._internal.board.view import board_columns, cold_agent, done_ids, task_view


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
    return {"flows": [{"name": "board", "agents": agents, "machine": {"states": states}}], "pulls": {}, "settled": {}}


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
    snapshot = {"flows": [{"name": "board", "agents": [waiting]}], "pulls": {}, "settled": {}, "cold_done": ["T-cold"]}
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

    cold = cold_agent("T-cold", record)

    assert done_ids(snapshot) == {"T-cold"}
    assert task_view(waiting, snapshot)["waiting_on"] == []
    assert task_view(cold, snapshot) == {
        "id": "T-cold",
        "title": "Old work",
        "lane": "done",
        "phase": None,
        "substate": None,
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
    }
    assert cold["description"] == "Long ago."
