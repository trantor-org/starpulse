"""The full task record, the guarded edit and the archive the page asks the board adapter for."""

import json
from pathlib import Path
from typing import Any

import pytest

from starpulse.adapter_kit import task
from starpulse.board import Board, Written
from starpulse.board_feed import BoardFeed
from starpulse.config import load
from starpulse.contracts import Move
from starpulse.server import archive_task, assemble, edit_task, task_record
from starpulse.tests import fake_board
from starpulse.tests.machines import MACHINES

LAN = "192.168.0.42"
RECORD = {
    "title": "Draw the board",
    "plan": "1. read\n2. draw",
    "notes": "kept in the file only",
    "labels": ["ui"],
    "acceptanceCriteria": [{"n": 1, "text": "It draws", "checked": True}],
}


class _File:
    """A task record held in a JSON file, as a board adapter holds one in the task's file."""

    def __init__(self, path: Path, refusal: Written | None = None) -> None:
        self.path = path
        self.refusal = refusal
        self.path.write_text(json.dumps(RECORD))
        self.sent: list[tuple[str, dict, str]] = []

    def read(self, task: str, /) -> dict[str, Any] | None:
        return json.loads(self.path.read_text()) if task == "PROJ-3" else None

    def edit(self, task: str, changes: dict[str, Any], comment: str, /) -> Written:
        self.sent.append((task, dict(changes), comment))
        if self.refusal is not None:
            return self.refusal
        self.path.write_text(json.dumps({**json.loads(self.path.read_text()), **changes}))
        return Written(True, "updated")

    def other_writer_sets(self, **fields: Any) -> None:
        self.path.write_text(json.dumps({**json.loads(self.path.read_text()), **fields}))


@pytest.fixture
def file(tmp_path: Path) -> _File:
    return _File(tmp_path / "task.json")


def _feed() -> BoardFeed:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-3", "Ready", moves={"in_progress": Move(allowed=True)}))
    return feed


def _edit(file: _File, body: Any, source: str = LAN, feed: BoardFeed | None = None):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return edit_task(source, raw, feed or _feed(), file.read, file.edit)


def test_the_record_carries_the_plan_notes_and_checks_the_snapshot_entry_lacks(file: _File) -> None:
    feed = _feed()
    entry = feed.task("PROJ-3")

    status, body = task_record(feed, file.read, "PROJ-3")

    assert entry is not None and not {"plan", "notes", "acceptanceCriteria"} & entry.keys()
    assert "kept in the file only" not in json.dumps(feed.snapshot())
    assert (status, body) == (200, {"task": "PROJ-3", "record": RECORD})


def test_a_task_the_board_does_not_hold_has_no_record(file: _File) -> None:
    assert task_record(_feed(), file.read, "PROJ-99") == (404, {"error": "PROJ-99 is not on the board"})


def test_a_task_the_reader_cannot_find_has_no_record() -> None:
    feed = _feed()

    assert task_record(feed, lambda task: None, "PROJ-3") == (404, {"error": "PROJ-3 has no record to read"})


def test_a_board_without_a_reader_serves_no_record() -> None:
    assert task_record(_feed(), None, "PROJ-3") == (404, {"error": "this board cannot read a task's full record"})


def test_every_change_is_one_write_when_the_base_is_current(file: _File) -> None:
    body = {
        "task": "PROJ-3",
        "base": {"title": RECORD["title"], "plan": RECORD["plan"]},
        "changes": {"title": "Draw it", "plan": "1. draw"},
        "comment": "why",
    }

    assert _edit(file, body) == (200, {"task": "PROJ-3", "changed": ["title", "plan"]})
    assert file.sent == [("PROJ-3", {"title": "Draw it", "plan": "1. draw"}, "why")]


def test_a_save_after_another_writer_changed_the_same_field_is_refused_and_the_file_keeps_their_value(
    file: _File,
) -> None:
    opened = file.read("PROJ-3")
    assert opened is not None
    file.other_writer_sets(title="Their title")

    status, body = _edit(file, {"task": "PROJ-3", "base": {"title": opened["title"]}, "changes": {"title": "Mine"}})

    assert status == 409
    assert body["stale"] == ["title"] and body["current"] == {"title": "Their title"}
    assert "changed since it was opened" in body["error"]
    assert file.sent == []
    assert json.loads(file.path.read_text())["title"] == "Their title"


def test_a_field_another_writer_changed_that_the_save_does_not_touch_does_not_block_it(file: _File) -> None:
    file.other_writer_sets(notes="Their notes")

    status, _ = _edit(file, {"task": "PROJ-3", "base": {"title": RECORD["title"]}, "changes": {"title": "Mine"}})

    assert status == 200
    assert json.loads(file.path.read_text()) == {**RECORD, "notes": "Their notes", "title": "Mine"}


def test_a_change_the_task_already_holds_writes_nothing(file: _File) -> None:
    body = {"task": "PROJ-3", "base": {"labels": ["ui"]}, "changes": {"labels": ["ui"]}}

    assert _edit(file, body) == (200, {"task": "PROJ-3", "changed": []})
    assert file.sent == []


def test_a_writer_refusal_writes_nothing_and_answers_with_its_reason_and_skill(file: _File) -> None:
    file.refusal = Written(False, "refusing to edit PROJ-3: ... Run the `authoring-tests` skill", "authoring-tests")

    status, body = _edit(file, {"task": "PROJ-3", "base": {"title": RECORD["title"]}, "changes": {"title": "Mine"}})

    assert status == 409
    assert body == {"error": "refusing to edit PROJ-3: ... Run the `authoring-tests` skill", "skill": "authoring-tests"}
    assert json.loads(file.path.read_text()) == RECORD


@pytest.mark.parametrize("source", ["203.0.113.5", "172.32.0.1", "100.64.0.1"])
def test_a_source_outside_loopback_and_rfc_1918_cannot_edit(file: _File, source: str) -> None:
    status, body = _edit(
        file, {"task": "PROJ-3", "base": {"title": RECORD["title"]}, "changes": {"title": "Mine"}}, source
    )

    assert (status, file.sent) == (403, [])
    assert body == {"error": "Editing a task answers only loopback and private network (RFC 1918) browsers"}


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b'{"task": "PROJ-3", "base": {}, "changes": {}}',
        b'{"base": {"title": "x"}, "changes": {"title": "y"}}',
        b'{"task": "PROJ-3", "base": [], "changes": {"title": "y"}}',
        b'{"task": "PROJ-3", "base": {"title": "x"}, "changes": []}',
        b'{"task": "PROJ-3", "base": {"title": "x"}, "changes": {"title": "y"}, "comment": 3}',
    ],
)
def test_a_body_that_is_not_a_task_a_base_and_changes_is_a_bad_request(file: _File, raw: bytes) -> None:
    status, body = _edit(file, raw)

    assert (status, file.sent) == (400, [])
    assert body == {"error": 'an edit needs {"task": "TASK-N", "base": {...}, "changes": {...}, "comment": "<optional>"}'}


def test_a_change_without_the_base_it_was_made_from_is_a_bad_request(file: _File) -> None:
    status, body = _edit(file, {"task": "PROJ-3", "base": {}, "changes": {"title": "y"}})

    assert (status, body, file.sent) == (400, {"error": "the edit has no base for title"}, [])


def test_a_field_the_record_does_not_hold_is_not_editable(file: _File) -> None:
    status, body = _edit(file, {"task": "PROJ-3", "base": {"color": "red"}, "changes": {"color": "blue"}})

    assert (status, file.sent) == (400, [])
    assert body == {"error": "color is not an editable field of PROJ-3"}


def test_a_task_the_board_does_not_hold_is_not_edited(file: _File) -> None:
    status, body = _edit(file, {"task": "PROJ-99", "base": {"title": "x"}, "changes": {"title": "y"}})

    assert (status, body, file.sent) == (404, {"error": "PROJ-99 is not on the board"}, [])


def test_a_board_that_cannot_edit_refuses_an_edit(file: _File) -> None:
    raw = json.dumps({"task": "PROJ-3", "base": {"title": "x"}, "changes": {"title": "y"}}).encode()

    assert edit_task(LAN, raw, _feed(), file.read, None) == (404, {"error": "this board does not edit tasks"})


class _Archive:
    def __init__(self, reply: Written = Written(True, "archived")) -> None:
        self.reply = reply
        self.sent: list[tuple[str, str]] = []

    def __call__(self, task: str, reason: str, /) -> Written:
        self.sent.append((task, reason))
        return self.reply


def _archive(body: Any, archive: _Archive | None, source: str = LAN, feed: BoardFeed | None = None):
    raw = body if isinstance(body, bytes) else json.dumps(body).encode()
    return archive_task(source, raw, feed or _feed(), archive)


@pytest.mark.parametrize("lane", ["Ready", "In Progress", "Waiting", "Needs attention", "Review"])
def test_a_task_is_archived_from_any_column_with_its_reason(lane: str) -> None:
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-4", lane))
    archive = _Archive()

    assert _archive({"task": "PROJ-4", "reason": "superseded"}, archive, feed=feed) == (200, {"task": "PROJ-4"})
    assert archive.sent == [("PROJ-4", "superseded")]


def test_an_archive_without_a_reason_passes_an_empty_one() -> None:
    archive = _Archive()

    assert _archive({"task": "PROJ-3"}, archive)[0] == 200
    assert archive.sent == [("PROJ-3", "")]


@pytest.mark.parametrize("source", ["203.0.113.5", "172.32.0.1"])
def test_a_source_outside_loopback_and_rfc_1918_cannot_archive(source: str) -> None:
    archive = _Archive()

    status, body = _archive({"task": "PROJ-3"}, archive, source)

    assert (status, archive.sent) == (403, [])
    assert body == {"error": "Archiving a task answers only loopback and private network (RFC 1918) browsers"}


@pytest.mark.parametrize("raw", [b"", b"[]", b"{}", b'{"task": 3}', b'{"task": "PROJ-3", "reason": 3}'])
def test_a_body_that_is_not_a_task_and_a_reason_is_a_bad_request(raw: bytes) -> None:
    archive = _Archive()

    status, body = _archive(raw, archive)

    assert (status, archive.sent) == (400, [])
    assert body == {"error": 'an archive needs {"task": "TASK-N", "reason": "<optional text>"}'}


def test_a_task_the_board_does_not_hold_is_not_archived() -> None:
    archive = _Archive()

    assert _archive({"task": "PROJ-99"}, archive) == (404, {"error": "PROJ-99 is not on the board"})
    assert archive.sent == []


def test_an_archive_the_writer_refuses_answers_with_its_reason_and_skill() -> None:
    archive = _Archive(Written(False, "archive failed: ... Run the `x` skill", "x"))

    assert _archive({"task": "PROJ-3", "reason": "r"}, archive) == (
        409,
        {"error": "archive failed: ... Run the `x` skill", "skill": "x"},
    )


def test_a_board_that_cannot_archive_refuses_an_archive() -> None:
    assert _archive({"task": "PROJ-3"}, None) == (404, {"error": "this board does not archive tasks"})


def _config(tmp_path: Path, writes: bool) -> Any:
    settings = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["open", "shut"]\n' + (
        "writes = true\n" if writes else ""
    )
    path = tmp_path / "starpulse.toml"
    path.write_text(settings)
    return load(path)


def test_a_board_with_the_writers_reports_the_capabilities_in_its_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])

    _, feed = assemble(_config(tmp_path, writes=True), tmp_path, None, ())

    assert feed.snapshot().get("capabilities") == {"edit": True, "archive": True}


def test_a_board_without_the_writers_reports_no_edit_or_archive_capability(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])

    _, feed = assemble(_config(tmp_path, writes=False), tmp_path, None, ())

    assert feed.snapshot().get("capabilities") == {"edit": False, "archive": False}


def test_a_board_that_edits_without_reading_is_refused() -> None:
    with pytest.raises(ValueError, match="must also read them"):
        Board(machines=lambda qualify, workflows: {}, start=lambda feed, group: None, edit=lambda *args: Written(True, ""))


def test_a_board_that_reads_alone_edits_nothing() -> None:
    board = Board(machines=lambda qualify, workflows: {}, start=lambda feed, group: None, read=lambda task: None)

    assert (board.edit, board.archive) == (None, None)

