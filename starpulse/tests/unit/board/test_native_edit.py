"""Editing, archiving and restoring a task on the native board: the board's `edit`, `archive` and `restore`, `POST /api/edit`, `POST /api/archive` and `POST /api/restore` over them."""

import json
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.board.seam import Board
from starpulse._internal.cli import agent_cli as cli
from starpulse._internal.kit.adapter_kit import serve
from starpulse._internal.board.upstream_backlog import UpstreamBacklog, _split
from starpulse._internal.server.server import assemble
from starpulse._internal.server import writes
from starpulse._internal.server.writes import archive_task, edit_task, task_record
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog

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
- [x] #2 It scrolls
- [ ] #3 It zooms
<!-- AC:END -->

## Definition of Done
<!-- DOD:BEGIN -->
- [ ] #1 Docs updated
- [x] #2 Tests pass
- [ ] #3 Lint clean
<!-- DOD:END -->

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


def _archived(base: Path) -> Path:
    return base / ".starpulse" / "board" / "archive" / "tasks" / "task-5 - Draw.md"


def test_a_restore_returns_the_archived_file_to_tasks_unchanged(served: tuple[Board, BoardFeed, Path]) -> None:
    built, _, base = served
    assert built.archive is not None
    assert built.restore is not None
    assert built.archive("task-5", "Superseded by task-9.").ok
    archived = _archived(base).read_bytes()

    restored = built.restore("task-5")

    assert restored.ok
    assert _file(base).read_bytes() == archived
    assert not _archived(base).exists()


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("task-5 - Redrawn.md", FILE),  # the number is open under another name
        ("task-5 - Draw.md", FILE.replace("id: task-5", "id: task-6")),  # the name is taken by another task
    ],
    ids=["number-open-under-another-name", "name-taken-by-another-task"],
)
def test_a_restore_is_refused_when_the_task_is_open_or_its_file_name_is_taken(
    served: tuple[Board, BoardFeed, Path], name: str, text: str
) -> None:
    built, _, base = served
    assert built.archive is not None
    assert built.restore is not None
    assert built.archive("task-5", "").ok
    (_tasks(base) / name).write_text(text)

    assert not built.restore("task-5").ok

    assert _archived(base).read_text() == FILE
    assert (_tasks(base) / name).read_text() == text


def test_a_restore_of_a_task_that_is_not_archived_is_refused(served: tuple[Board, BoardFeed, Path]) -> None:
    built, _, base = served
    assert built.restore is not None

    assert not built.restore("task-404").ok
    assert not built.restore("task-5").ok  # open, not archived

    assert _file(base).read_text() == FILE


def test_the_restore_route_answers_the_task_and_the_writers_refusal(served: tuple[Board, BoardFeed, Path]) -> None:
    built, feed, base = served
    assert archive_task(LAN, _raw(task="task-5"), feed, built.archive)[0] == 200

    restored = writes.restore_task(LAN, _raw(task="task-5"), built.restore)
    again = writes.restore_task(LAN, _raw(task="task-5"), built.restore)

    assert restored == (200, {"task": "task-5"})
    assert again[0] == 409
    assert "task-5" in again[1]["error"]
    assert _file(base).read_text() == FILE


@pytest.mark.parametrize(
    ("source", "raw", "status"),
    [("8.8.8.8", _raw(task="task-5"), 403), (LAN, b"{}", 400), (LAN, _raw(task=5), 400), (LAN, b"nope", 400)],
    ids=["outside-the-lan", "no-task", "task-not-text", "not-json"],
)
def test_the_restore_route_refuses_a_non_lan_caller_and_a_malformed_body(
    served: tuple[Board, BoardFeed, Path], source: str, raw: bytes, status: int
) -> None:
    built, feed, base = served
    assert archive_task(LAN, _raw(task="task-5"), feed, built.archive)[0] == 200

    assert writes.restore_task(source, raw, built.restore)[0] == status

    assert _archived(base).read_text() == FILE


def test_the_restore_route_on_a_board_that_does_not_restore_is_404() -> None:
    assert writes.restore_task(LAN, _raw(task="task-5"), None)[0] == 404


def _edit_verb(
    capsys: pytest.CaptureFixture[str], server: ThreadingHTTPServer, *flags: str
) -> tuple[int, dict[str, Any]]:
    code = cli.main(["task", "edit", "task-5", *flags, "--server", f"http://127.0.0.1:{server.server_port}"], {})
    out = capsys.readouterr()
    assert out.err == ""
    return code, json.loads(out.out)


def test_task_edit_flags_add_reword_remove_check_and_uncheck_items_of_both_checklists_and_renumber(
    served: tuple[Board, BoardFeed, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, feed, base = served

    with serve(tmp_path, feed, read=built.read, edit=built.edit) as server:
        code, doc = _edit_verb(
            capsys,
            server,
            *("--remove-ac", "1", "--uncheck-ac", "2", "--reword-ac", "3:It zooms smoothly: fast", "--check-ac", "3"),
            *("--ac", "It pans"),
            *("--remove-dod", "1", "--uncheck-dod", "2", "--reword-dod", "3:Lint passes", "--check-dod", "3"),
            *("--dod", "Changelog written"),
        )

    assert (code, doc["task"], sorted(doc["changed"])) == (0, "task-5", ["acceptanceCriteria", "definitionOfDone"])
    assert _split(_file(base).read_text())[1] == _split(FILE)[1].replace(
        "- [x] #1 It draws\n- [x] #2 It scrolls\n- [ ] #3 It zooms\n",
        "- [ ] #1 It scrolls\n- [x] #2 It zooms smoothly: fast\n- [ ] #3 It pans\n",
    ).replace(
        "- [ ] #1 Docs updated\n- [x] #2 Tests pass\n- [ ] #3 Lint clean\n",
        "- [ ] #1 Tests pass\n- [x] #2 Lint passes\n- [ ] #3 Changelog written\n",
    )


def test_task_edit_append_notes_adds_lines_after_the_notes_and_rewrites_nothing_before_them(
    served: tuple[Board, BoardFeed, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, feed, base = served

    with serve(tmp_path, feed, read=built.read, edit=built.edit) as server:
        code, doc = _edit_verb(capsys, server, "--append-notes", "Second note.", "--append-notes", "Third note.")

    assert (code, doc) == (0, {"task": "task-5", "changed": ["notes"]})
    assert _split(_file(base).read_text())[1] == _split(FILE)[1].replace(
        "kept in the file\n<!-- SECTION:NOTES:END -->",
        "kept in the file\nSecond note.\nThird note.\n<!-- SECTION:NOTES:END -->",
    )


def test_task_edit_naming_an_item_the_task_lacks_is_refused_and_writes_nothing(
    served: tuple[Board, BoardFeed, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, feed, base = served

    with serve(tmp_path, feed, read=built.read, edit=built.edit) as server:
        code, doc = _edit_verb(capsys, server, "--title", "Mine", "--check-dod", "9")

    assert (code, doc["code"]) == (1, "refused")
    assert "no Definition of Done item #9" in doc["error"]
    assert _file(base).read_text() == FILE


def test_task_edit_reword_without_a_number_and_colon_is_a_usage_error(
    served: tuple[Board, BoardFeed, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    built, feed, _ = served

    with serve(tmp_path, feed, read=built.read, edit=built.edit) as server:
        code, doc = _edit_verb(capsys, server, "--reword-ac", "It zooms")

    assert (code, doc["code"]) == (2, "usage")
    assert "N:TEXT" in doc["error"]
