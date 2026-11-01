"""Reading a task's full record from the native board: the board's `read` and `GET /api/task/<id>` over it."""

from pathlib import Path

import pytest
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.runtime.assembly import assemble
from starpulse.runtime.config import load
from starpulse.views.application.commands.tasks import create_task, task_record

LAN = "127.0.0.1"
FILE = """---
id: task-5
title: Draw the board
status: In Progress
profile:
  - '@agent-standard-high'
labels:
  - ui
  - adr-needed
milestone: m-1
dependencies:
  - task-2
priority: high
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Draw it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 It draws
- [ ] #2 It scrolls
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. read
2. draw
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
kept in the file
<!-- SECTION:NOTES:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [x] #1 Reviewed
<!-- DOD:END -->
"""


def _serving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Board, BoardFeed]:
    """The default native board of an empty directory, scanned once on start."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    built, feed = assemble(load(None), tmp_path, None, ())
    built.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    return built, feed


def _scan(tmp_path: Path, feed: BoardFeed) -> None:
    UpstreamBacklog(tmp_path / ".starpulse" / "board", feed.put).scan()


def test_a_task_made_by_the_create_writer_reads_back_its_priority_description_and_criteria(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, feed = _serving(tmp_path, monkeypatch)
    assert built.create is not None
    details = {"description": "Draw it.", "priority": "high", "acceptanceCriteria": ["It draws", "It scrolls"]}
    body = '{"title": "Draw the board", "description": "Draw it.", "priority": "high", '
    body += '"acceptanceCriteria": ["It draws", "It scrolls"]}'
    assert create_task(LAN, body.encode(), built.create) == (201, {"task": "task-1"})
    _scan(tmp_path, feed)

    assert built.read is not None
    record = built.read("task-1")

    assert record is not None
    assert record["priority"] == details["priority"]
    assert record["description"] == details["description"]
    assert record["acceptanceCriteria"] == [
        {"n": 1, "text": "It draws", "checked": False},
        {"n": 2, "text": "It scrolls", "checked": False},
    ]
    assert record["title"] == "Draw the board"


def test_a_task_file_reads_as_every_field_the_task_view_draws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    built, _ = _serving(tmp_path, monkeypatch)
    (tmp_path / ".starpulse" / "board" / "tasks" / "task-5 - Draw.md").write_text(FILE)
    assert built.read is not None

    assert built.read("task-5") == {
        "title": "Draw the board",
        "type": "",
        "status": "In Progress",
        "profile": "@agent-standard-high",
        "assignee": "",
        "priority": "high",
        "impact": "",
        "urgency": "",
        "labels": ["ui", "adr-needed"],
        "milestone": "m-1",
        "source": "",
        "dependencies": ["task-2"],
        "dependencyNeeds": [],
        "references": [],
        "documentation": [],
        "modifiedFiles": [],
        "verifyPlan": [],
        "description": "Draw it.",
        "start_criteria": [],
        "plan": "1. read\n2. draw",
        "notes": "kept in the file",
        "finalSummary": "",
        "comments": [],
        "session": "",
        "createdBy": "",
        "acceptanceCriteria": [
            {"n": 1, "text": "It draws", "checked": True},
            {"n": 2, "text": "It scrolls", "checked": False},
        ],
        "definitionOfDone": [{"n": 1, "text": "Reviewed", "checked": True}],
    }


def test_a_task_file_with_only_front_matter_reads_with_empty_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, _ = _serving(tmp_path, monkeypatch)
    (tmp_path / ".starpulse" / "board" / "tasks" / "task-6 - Bare.md").write_text(
        "---\nid: task-6\ntitle: Bare\nstatus: To Do\n---\n"
    )
    assert built.read is not None

    assert built.read("task-6") == {
        "title": "Bare",
        "type": "",
        "status": "To Do",
        "profile": "",
        "assignee": "",
        "priority": "",
        "impact": "",
        "urgency": "",
        "labels": [],
        "milestone": "",
        "source": "",
        "dependencies": [],
        "dependencyNeeds": [],
        "references": [],
        "documentation": [],
        "modifiedFiles": [],
        "verifyPlan": [],
        "description": "",
        "start_criteria": [],
        "plan": "",
        "notes": "",
        "finalSummary": "",
        "comments": [],
        "session": "",
        "createdBy": "",
        "acceptanceCriteria": [],
        "definitionOfDone": [],
    }


SESSION_NOTES = "kept\n\n**Session Link:** https://claude.ai/code/session_notes — local session `a`"
SESSION_COMMENTS = (
    "<!-- COMMENTS:BEGIN -->\n"
    "created: 2026-10-06 22:11\n---\n**Session Link:** https://claude.ai/code/session_old\n---\n\n"
    "created: 2026-10-06 22:18\n---\nVerified AC #1.\n---\n\n"
    "created: 2026-10-06 22:30\n---\n**Session Link:** https://claude.ai/code/session_new — resumed\n---\n"
    "<!-- COMMENTS:END -->\n"
)
LOCAL_COMMENTS = (
    "<!-- COMMENTS:BEGIN -->\n"
    "created: 2026-10-26 10:00\n---\n**Session Link:** https://claude.ai/code/session_old\n---\n\n"
    "created: 2026-10-26 10:30\n---\n**Session Link:** local Claude session `d4f1c2` — no web view, reopen with `claude --resume d4f1c2`\n---\n"
    "<!-- COMMENTS:END -->\n"
)


@pytest.mark.parametrize(
    ("notes", "comments", "session"),
    [
        (SESSION_NOTES, "", "https://claude.ai/code/session_notes"),
        ("kept", SESSION_COMMENTS, "https://claude.ai/code/session_new"),
        (SESSION_NOTES, SESSION_COMMENTS, "https://claude.ai/code/session_new"),
        ("kept", LOCAL_COMMENTS, "d4f1c2"),
        ("kept", "", ""),
    ],
    ids=["notes", "latest-comment", "comment-after-notes", "local-session-comment", "none"],
)
def test_a_task_reads_its_latest_session_link_from_its_notes_or_comments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, notes: str, comments: str, session: str
) -> None:
    built, _ = _serving(tmp_path, monkeypatch)
    text = FILE.replace("kept in the file", notes) + (f"\n## Comments\n\n{comments}" if comments else "")
    (tmp_path / ".starpulse" / "board" / "tasks" / "task-5 - Draw.md").write_text(text)
    assert built.read is not None

    record = built.read("task-5")

    assert record is not None
    assert record["session"] == session


def test_a_task_the_board_has_no_file_for_reads_as_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    built, _ = _serving(tmp_path, monkeypatch)
    assert built.read is not None

    assert built.read("task-404") is None


def test_the_task_endpoint_carries_the_session_link_the_kanban_modal_draws(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, feed = _serving(tmp_path, monkeypatch)
    text = FILE.replace("kept in the file", SESSION_NOTES)
    (tmp_path / ".starpulse" / "board" / "tasks" / "task-5 - Draw.md").write_text(text)
    _scan(tmp_path, feed)

    _, body = task_record(feed, built.read, "task-5")

    assert body["record"]["session"] == "https://claude.ai/code/session_notes"


def test_the_task_endpoint_answers_200_with_the_record_on_a_native_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, feed = _serving(tmp_path, monkeypatch)
    (tmp_path / ".starpulse" / "board" / "tasks" / "task-5 - Draw.md").write_text(FILE)
    _scan(tmp_path, feed)

    status, body = task_record(feed, built.read, "task-5")

    assert status == 200
    assert body["task"] == "task-5"
    assert body["record"]["priority"] == "high"
    assert [item["text"] for item in body["record"]["acceptanceCriteria"]] == ["It draws", "It scrolls"]


def test_a_proposed_task_names_the_session_that_filed_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    built, _ = _serving(tmp_path, monkeypatch)
    filed = FILE.replace("priority: high\n", "priority: high\ncreated_by: claude:c4d52088\n")
    (tmp_path / ".starpulse" / "board" / "tasks" / "task-5 - Draw.md").write_text(filed)
    assert built.read is not None

    assert (built.read("task-5") or {})["createdBy"] == "claude:c4d52088"
