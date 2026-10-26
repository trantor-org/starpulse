"""Every write to a native Task is a command that appends intent-level Events to its History, and replaying the History
gives the Task the read model holds (D2)."""

import json
from pathlib import Path

import pytest

from starpulse.runtime.config import load
from starpulse.board.adapters.task_history import WRITER, _events
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.event_log.tables import retired_tasks
from starpulse.runtime.assembly import assemble
from starpulse.views.writes import edit_task

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


def test_rewriting_a_status_whose_append_was_lost_transitions_from_the_historys_state(
    served, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, _, store, _ = served
    assert built.edit("task-5", {"title": "Draw it"}, [], actor="adin").ok
    append = EventStore.append

    def lost(self, *args, **kwargs):
        monkeypatch.setattr(EventStore, "append", append)
        raise OSError("unable to open database file")

    monkeypatch.setattr(EventStore, "append", lost)
    with pytest.raises(OSError):
        built.writer("task-5", "In Progress", "actor")

    assert built.writer("task-5", "In Progress", "actor").ok

    moved = store.read("task", "task-5")[-1]
    assert (moved.type, moved.payload["from"], moved.payload["to"]) == ("Transitioned", "To Do", "In Progress")
    assert replay(store.read("task", "task-5"))["state"] == "In Progress"


def test_rewriting_a_status_the_history_already_holds_appends_no_transition(served) -> None:
    built, _, store, _ = served
    assert built.writer("task-5", "In Progress", "adin").ok

    assert built.edit("task-5", {"status": "In Progress"}, "again", actor="adin").ok

    assert _types(store, "task-5")[-2:] == ["Transitioned", "CommentAdded"]


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

    assert _types(store, "task-5")[-3:] == ["Archived", "Rehydrated", "FieldsEdited"]


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


def test_a_retire_and_a_restore_of_a_retired_task_keep_its_history_archived_then_rehydrated(served) -> None:
    built, _, store, _ = served

    assert built.archive("task-5", "", actor="adin").ok
    assert built.retire("task-5").ok
    assert built.restore("task-5").ok

    assert _types(store, "task-5")[-3:] == ["Archived", "Rehydrated", "FieldsEdited"]
    assert _types(store, "task-5").count("Archived") == 1


RETURNED = {
    "title": "Draw it again",
    "status": "To Do",
    "priority": "high",
    "description": "Draw it again.",
    "labels": ["ui", "page"],
    "acceptanceCriteria": [
        {"n": 1, "text": "It draws", "checked": False},
        {"n": 2, "text": "It scrolls", "checked": False},
        {"n": 3, "text": "It zooms", "checked": False},
    ],
}


def _appended(store: EventStore, task: str, events: list[tuple[str, dict]]) -> None:
    store.append(
        "task", task, store.head("task", task), [NewEvent(kind, payload, "adin", WRITER) for kind, payload in events]
    )


def test_a_returning_task_folds_to_the_fields_its_file_carries(served) -> None:
    built, _, store, _ = served
    assert built.archive("task-5", "", actor="adin").ok

    _appended(store, "task-5", _events({}, RETURNED, ""))

    row = replay(store.read("task", "task-5"))
    assert (row["title"], row["labels"], row["archived"]) == ("Draw it again", ["ui", "page"], False)
    assert [(item["n"], item["text"]) for item in row["criteria"]] == [
        (1, "It draws"),
        (2, "It scrolls"),
        (3, "It zooms"),
    ]


def test_a_criterion_the_returning_file_added_folds_checked_when_its_check_is_recorded(served) -> None:
    built, _, store, _ = served
    assert built.archive("task-5", "", actor="adin").ok

    _appended(
        store, "task-5", _events({}, RETURNED, "") + [("CriterionChecked", {"kind": "ac", "n": 3, "checked": True})]
    )

    assert replay(store.read("task", "task-5"))["criteria"][2]["checked"] is True


def test_starting_the_board_gives_a_retired_row_without_history_its_imported_and_archived_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    built, feed = assemble(load(None), tmp_path, None, ())
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    with log.engine.begin() as db:
        db.execute(
            retired_tasks.insert().values(
                task="TASK-9", name="task-9 - Old.md", text=FILE.replace("task-5", "TASK-9"), retired_at=0.0
            )
        )

    built.start(feed, "test", log)

    assert _types(EventStore(log.engine), "TASK-9") == ["TaskImported", "Archived"]
