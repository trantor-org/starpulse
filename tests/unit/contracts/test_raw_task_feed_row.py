"""Every feed row shape a snapshot or event carries validates as the `RawTask` the page reads, and names no key it lacks.

`RawTask` ignores unknown fields, so a client pinned to an older StarPulse survives a field the server adds; the
key check here is what makes a feed builder name each new key in the DTO. No other test names both sides.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from starpulse.board.feed.shared import read_model_detail, summary_agent, task_agent
from starpulse.contracts.adapters import BoardTask, Move
from starpulse.contracts.api.dto.requests import WindowRequest
from starpulse.contracts.api.dto.task import RawTask

ROW = {
    "id": "TASK-1",
    "title": "A task",
    "state": "Review",
    "assignee": "",
    "released": None,
    "labels": [],
    "milestone": "",
    "type": "bug",
    "updated_at": 0.0,
    "meta": {},
    "references": [],
    "description": "",
    "criteria": [
        {"kind": "ac", "text": "it works", "checked": True},
        {"kind": "dod", "text": "it ships", "checked": False},
    ],
}

PROFILED = ROW | {"meta": {"profile": "@agent-standard-high"}, "dependencies": ["TASK-2"], "assignee": "me"}
BARE = ROW | {"criteria": [], "references": ["https://github.com/trantor-org/starpulse/pull/1"]}
MOVES = {"Done": Move(allowed=False, reason="needs review", skill="review", writers=("operator",)).model_dump()}

BOARD_TASK = BoardTask(
    id="TASK-1",
    team="demo",
    title="A task",
    lane="Review",
    acceptance_criteria=("it works",),
    acceptance_checked=(True,),
    moves={"Done": Move(allowed=False, reason="needs review", skill="review", writers=("operator",))},
)


def _summary(row: dict, workable: bool, moves: dict) -> dict:
    return summary_agent(row, workable, moves)


def _detail(row: dict, workable: bool, moves: dict) -> dict:
    return summary_agent(row, workable, moves) | read_model_detail(row)


@pytest.mark.parametrize("row", [ROW, PROFILED, BARE], ids=["plain", "profiled", "bare"])
@pytest.mark.parametrize("workable", [False, True])
@pytest.mark.parametrize("moves", [{}, MOVES], ids=["no-moves", "moves"])
@pytest.mark.parametrize("build", [_summary, _detail], ids=["summary", "summary-and-detail"])
def test_a_read_model_feed_row_validates_as_a_raw_task(build, row, workable, moves) -> None:
    agent = build(row, workable, moves)
    assert RawTask.model_validate(agent).id == row["id"]
    assert agent.keys() <= RawTask.model_fields.keys(), "a feed key RawTask does not name"


def test_a_feed_row_with_definition_of_done_items_validates_as_a_raw_task() -> None:
    task = RawTask.model_validate(summary_agent(ROW) | read_model_detail(ROW))
    assert [item.checked for item in task.definition_of_done] == [False]


def test_a_task_record_agent_validates_as_a_raw_task() -> None:
    task = RawTask.model_validate(task_agent(BOARD_TASK))
    assert task.id == "TASK-1"


def test_a_raw_task_row_carrying_an_unknown_field_validates() -> None:
    task = RawTask.model_validate(summary_agent(ROW) | {"field_a_newer_server_adds": 1})
    assert task.id == "TASK-1"


def test_a_request_body_carrying_an_unknown_field_is_refused() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        WindowRequest.model_validate({"hours": 1.0, "hour": 2.0})
