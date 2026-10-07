"""Editing and archiving a task on the native board: the board's `edit` and `archive`, `POST /api/edit` and `POST /api/archive` over them."""

import json
from pathlib import Path

import pytest

from starpulse.adapters.boards.seam import Board
from starpulse.adapters.boards.upstream_backlog import UpstreamBacklog, _split
from starpulse.board_feed import BoardFeed
from starpulse.server import archive_task, assemble, edit_task, task_record
from starpulse.settings.config import load
from starpulse.store.event_log import EventLog

LAN = "192.168.0.42"
FILE = """---
id: task-5
title: Draw the board
status: In Progress
assignee:
  - '@agent-standard-high'
labels:
  - ui
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

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
kept in the file
<!-- SECTION:NOTES:END -->
"""


def _raw(**body: object) -> bytes:
    return json.dumps(body).encode()


def _tasks(base: Path) -> Path:
    return base / ".starpulse" / "board" / "tasks"


def _file(base: Path) -> Path:
    return _tasks(base) / "task-5 - Draw.md"


def _scan(base: Path, feed: BoardFeed) -> None:
    UpstreamBacklog(base / ".starpulse" / "board", feed.put).scan()


def _board_agents(feed: BoardFeed) -> list[dict]:
    """The tasks the board's lanes draw, as the snapshot carries them."""
    return next(flow["agents"] for flow in feed.snapshot()["flows"] if flow["name"] == "board")


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Board, BoardFeed, Path]:
    """The default native board holding `task-5`, scanned once on start."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval: self.scan())
    built, feed = assemble(load(None), tmp_path, None, ())
    _file(tmp_path).write_text(FILE)
    built.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}"))
    return built, feed, tmp_path


def _opened(built: Board, feed: BoardFeed) -> dict:
    """The record the page reads when it opens the task, which it sends back as an edit's `base`."""
    status, body = task_record(feed, built.read, "task-5")
    assert status == 200
    return body["record"]


def test_the_native_snapshot_reports_edit_and_archive_capability(served: tuple[Board, BoardFeed, Path]) -> None:
    _, feed, _ = served

    assert feed.snapshot()["capabilities"] == {"edit": True, "archive": True, "create": True}


def test_an_edit_changes_the_front_matter_and_sections_of_the_task_file_in_one_write(
    served: tuple[Board, BoardFeed, Path],
) -> None:
    built, feed, base = served
    record = _opened(built, feed)
    changes = {
        "title": "Draw the whole board",
        "priority": "low",
        "profile": "@agent-deep-medium",
        "labels": ["ui", "needs-human"],
        "milestone": "",
        "dependencies": [],
        "description": "Draw all of it.",
        "plan": "1. read\n2. draw",
        "notes": "changed notes",
    }

    status, body = edit_task(
        LAN, _raw(task="task-5", base=record, changes=changes, comment="Reworked."), feed, built.read, built.edit
    )

    assert (status, sorted(body["changed"])) == (200, sorted(changes))
    after = _opened(built, feed)
    assert {field: after[field] for field in changes} == changes
    frontmatter, text = _split(_file(base).read_text())
    assert frontmatter["status"] == "In Progress" and "milestone" not in frontmatter
    assert "Reworked." in text


def test_an_edit_rewords_adds_removes_and_checks_criteria(served: tuple[Board, BoardFeed, Path]) -> None:
    built, feed, _ = served
    record = _opened(built, feed)
    criteria = [
        {"n": 2, "text": "It scrolls smoothly", "checked": True},
        {"text": "It resizes", "checked": False},
    ]

    status, _ = edit_task(
        LAN, _raw(task="task-5", base=record, changes={"acceptanceCriteria": criteria}), feed, built.read, built.edit
    )

    assert status == 200
    assert [(item["text"], item["checked"]) for item in _opened(built, feed)["acceptanceCriteria"]] == [
        ("It scrolls smoothly", True),
        ("It resizes", False),
    ]


def test_a_save_after_another_writer_changed_the_field_is_refused_and_the_file_keeps_their_value(
    served: tuple[Board, BoardFeed, Path],
) -> None:
    built, feed, base = served
    record = _opened(built, feed)
    _file(base).write_text(FILE.replace("title: Draw the board", "title: Theirs"))

    status, body = edit_task(
        LAN, _raw(task="task-5", base=record, changes={"title": "Mine"}), feed, built.read, built.edit
    )

    assert (status, body["stale"]) == (409, ["title"])
    assert "title: Theirs" in _file(base).read_text()


def test_an_edit_naming_a_field_the_record_lacks_writes_nothing(served: tuple[Board, BoardFeed, Path]) -> None:
    built, _, base = served
    assert built.edit is not None

    written = built.edit("task-5", {"title": "Mine", "bogus": "x"}, "")

    assert not written.ok
    assert _file(base).read_text() == FILE


def test_an_edit_of_a_task_with_no_file_is_refused(served: tuple[Board, BoardFeed, Path]) -> None:
    built, _, _ = served
    assert built.edit is not None

    assert not built.edit("task-404", {"title": "Mine"}, "").ok


def test_an_archive_records_the_reason_and_the_task_leaves_the_projection(
    served: tuple[Board, BoardFeed, Path],
) -> None:
    built, feed, base = served
    assert [agent["id"] for agent in _board_agents(feed)] == ["task-5"]

    status, body = archive_task(LAN, _raw(task="task-5", reason="Superseded by task-9."), feed, built.archive)

    assert (status, body) == (200, {"task": "task-5"})
    assert not _file(base).exists()
    archived = base / ".starpulse" / "board" / "archive" / "tasks" / "task-5 - Draw.md"
    assert "Superseded by task-9." in archived.read_text()
    _scan(base, feed)
    assert feed.task("task-5") is None
    assert _board_agents(feed) == []


def test_an_archive_without_a_reason_writes_no_comment(served: tuple[Board, BoardFeed, Path]) -> None:
    built, feed, base = served

    status, _ = archive_task(LAN, _raw(task="task-5"), feed, built.archive)

    assert status == 200
    archived = base / ".starpulse" / "board" / "archive" / "tasks" / "task-5 - Draw.md"
    assert archived.read_text() == FILE


def test_an_archive_of_a_task_with_no_file_is_refused(served: tuple[Board, BoardFeed, Path]) -> None:
    built, _, _ = served
    assert built.archive is not None

    assert not built.archive("task-404", "gone").ok
