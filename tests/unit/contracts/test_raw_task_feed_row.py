"""A Board task's feed row, Definition of Done items included, validates as the `RawTask` every snapshot carries."""

from __future__ import annotations

from starpulse.board.feed.shared import read_model_detail, summary_agent
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


def test_a_feed_row_with_definition_of_done_items_validates_as_a_raw_task() -> None:
    task = RawTask.model_validate(summary_agent(ROW) | read_model_detail(ROW))
    assert [item.checked for item in task.definition_of_done] == [False]
