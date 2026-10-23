"""Every write to a native Task is a command that appends intent-level Events to its History, and replaying the History
gives the Task the read model holds (D2)."""

import json
from pathlib import Path

import pytest

from starpulse._internal.board.seam import Board
from starpulse._internal.board.upstream_backlog import UpstreamBacklog
from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.readmodel.fold import replay
from starpulse._internal.readmodel.projector import Projector
from starpulse._internal.readmodel.read_model import ReadModel
from starpulse._internal.server.assembly import assemble
from starpulse._internal.server.writes import edit_task
from starpulse._internal.store import EventStore

FILE = """---
id: task-5
title: Draw the board
status: To Do
labels:
  - ui
priority: high
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Draw it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 It draws
- [ ] #2 It scrolls
<!-- AC:END -->
"""


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Board, BoardFeed, EventStore, EventLog]:
    """The default native board holding `task-5` written before any History, started over an event log."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    built, feed = assemble(load(None), tmp_path, None, ())
    (tmp_path / ".starpulse" / "board" / "tasks" / "task-5 - Draw.md").write_text(FILE)
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    built.start(feed, "test", log)
    return built, feed, EventStore(log.engine), log


def _types(store: EventStore, task: str) -> list[str]:
    return [event.type for event in store.read("task", task)]


def test_an_edit_appends_the_fields_it_changed_and_each_comment(served) -> None:
    built, _, store, _ = served

    written = built.edit("task-5", {"title": "Draw it", "labels": ["ui", "page"]}, "looks fine", actor="adin")

    assert written.ok
    events = store.read("task", "task-5")
    assert [event.type for event in events] == ["TaskImported", "FieldsEdited", "CommentAdded"]
    assert events[1].payload["changes"] == {"title": "Draw it", "labels": ["ui", "page"]}
    assert (events[1].actor, events[2].payload["text"]) == ("adin", "looks fine")


def test_a_move_appends_a_transition_naming_both_states(served) -> None:
    built, _, store, _ = served

    assert built.writer("task-5", "In Progress", "adin").ok

    moved = store.read("task", "task-5")[-1]
    assert (moved.type, moved.payload["from"], moved.payload["to"]) == ("Transitioned", "To Do", "In Progress")


def test_a_checked_criterion_is_a_criterion_event_not_a_field_edit(served) -> None:
    built, _, store, _ = served
    record = built.read("task-5")
    criteria = [{**item, "checked": item["n"] == 1} for item in record["acceptanceCriteria"]]

    assert built.edit("task-5", {"acceptanceCriteria": criteria}, [], actor="adin").ok

    event = store.read("task", "task-5")[-1]
    assert (event.type, event.payload["n"], event.payload["checked"]) == ("CriterionChecked", 1, True)


def test_an_archive_and_a_restore_append_archived_and_rehydrated(served) -> None:
    built, _, store, _ = served

    assert built.archive("task-5", "", actor="adin").ok
    assert built.restore("task-5").ok

    assert _types(store, "task-5")[-2:] == ["Archived", "Rehydrated"]


def test_a_create_appends_task_created_with_the_files_fields(served) -> None:
    built, _, store, _ = served

    written = built.create("Fresh task", {"status": "To Do", "labels": ["new"]}, actor="adin")

    assert written.ok
    created = store.read("task", written.output)
    assert [event.type for event in created] == ["TaskCreated"]
    assert (created[0].payload["title"], created[0].payload["labels"]) == ("Fresh task", ["new"])


def test_a_refused_write_appends_nothing(served) -> None:
    built, _, store, _ = served

    assert not built.writer("task-404", "Done", "adin").ok

    assert store.read("task", "task-404") == []


def test_the_api_edit_path_appends_to_history(served) -> None:
    built, feed, store, _ = served
    record = built.read("task-5")

    body = json.dumps({"task": "task-5", "base": record, "changes": {"title": "Via the page"}, "comment": ""})

    status, _ = edit_task("127.0.0.1", body.encode(), feed, built.read, built.edit)

    assert status == 200
    assert _types(store, "task-5")[-1] == "FieldsEdited"


def test_replaying_every_task_equals_its_read_model_row_and_its_file(served) -> None:
    built, _, store, log = served
    made = built.create("Second", {"status": "To Do"}, actor="adin").output
    built.edit("task-5", {"title": "Draw it", "notes": "hand written"}, ["one", "two"], actor="adin")
    built.writer("task-5", "In Progress", "adin")
    built.edit(made, {"description": "later"}, [], actor="adin")
    kept = built.read(made)
    built.archive(made, "", actor="adin")
    Projector(log.engine, store).catch_up()
    model = ReadModel(log.engine)

    assert replay(store.read("task", made))["archived"]
    for task, record in (("task-5", built.read("task-5")), (made, kept)):
        replayed = replay(store.read("task", task))
        assert replayed == model.task(task)
        assert (replayed["title"], replayed["state"]) == (record["title"], record["status"])
        assert (replayed["description"], replayed["notes"], replayed["labels"]) == (
            record["description"],
            record["notes"],
            record["labels"],
        )
