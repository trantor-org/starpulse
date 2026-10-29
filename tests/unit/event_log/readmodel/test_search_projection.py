"""The projector keeps the search index's rows: an archived Task is found marked archived, and restore brings its row back."""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine
from starpulse.board.adapters.search import SearchIndex
from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.rows import load
from starpulse.event_log.store import EventStore, NewEvent

_STAMPS = ("version", "updated_at")


@contextmanager
def _board() -> Iterator[tuple[Engine, EventStore, SearchIndex]]:
    with tempfile.TemporaryDirectory() as directory:
        engine = EventLog(f"sqlite:///{Path(directory) / 'events.sqlite'}").engine
        index = SearchIndex.open(engine)
        assert index is not None
        yield engine, EventStore(engine), index
        engine.dispose()


def _new(type: str, **payload: object) -> NewEvent:
    return NewEvent(type=type, payload=payload, actor="adin", writer="operator")


def _append(store: EventStore, task: str, *events: NewEvent) -> None:
    for event in events:
        store.append("task", task, store.head("task", task), [event])


def _lanes(index: SearchIndex, query: str) -> dict[str, str]:
    return {hit["task"]: hit["lane"] for hit in index.search(query)}


def test_an_archived_task_is_found_marked_archived_and_restore_brings_its_row_back() -> None:
    with _board() as (engine, store, index):
        projector = Projector(engine, store, search=index)
        _append(store, "TASK-1", _new("TaskCreated", title="Retire the cron", state="Ready"))
        projector.catch_up()
        with engine.connect() as db:
            before = load(db, "TASK-1")

        _append(store, "TASK-1", _new("Archived"))
        projector.catch_up()
        assert _lanes(index, "cron") == {"TASK-1": "archived"}

        _append(store, "TASK-1", _new("Rehydrated"))
        projector.catch_up()
        with engine.connect() as db:
            after = load(db, "TASK-1")

        assert _lanes(index, "cron") == {"TASK-1": "Ready"}
        assert {k: v for k, v in after.items() if k not in _STAMPS} == {
            k: v for k, v in before.items() if k not in _STAMPS
        }


def test_a_move_another_projector_folded_is_found_in_its_new_lane() -> None:
    with _board() as (engine, store, index):
        indexing = Projector(engine, store, search=index)
        folding = Projector(engine, store)  # the board worker folds without the index and moves the shared checkpoint
        _append(store, "TASK-1", _new("TaskCreated", title="Retire the cron", state="Review"))
        indexing.catch_up()
        assert _lanes(index, "cron") == {"TASK-1": "Review"}

        _append(store, "TASK-1", _new("FieldsEdited", changes={"state": "Done"}))
        folding.catch_up()
        indexing.catch_up()

        assert _lanes(index, "cron") == {"TASK-1": "Done"}


def test_an_archived_done_task_is_found_in_the_done_lane() -> None:
    with _board() as (engine, store, index):
        projector = Projector(engine, store, search=index)
        _append(store, "TASK-1", _new("TaskCreated", title="Retire the cron", state="Done"))
        _append(store, "TASK-1", _new("Archived"))
        projector.catch_up()

        assert _lanes(index, "cron") == {"TASK-1": "Done"}


def test_a_row_indexed_archived_before_the_done_lane_is_reindexed_on_the_next_run() -> None:
    with _board() as (engine, store, index):
        _append(store, "TASK-1", _new("TaskCreated", title="Retire the cron", state="Done"))
        _append(store, "TASK-1", _new("Archived"))
        Projector(engine, store).catch_up()
        index.index_fields(
            "TASK-1", title="Retire the cron", description="", criteria=[], notes="", lane="archived", labels=[]
        )
        with engine.begin() as db:
            Checkpoints(engine).save("read-model:search", 1_000_000, conn=db)  # the checkpoint the old index left

        Projector(engine, store, search=index).catch_up()

        assert _lanes(index, "cron") == {"TASK-1": "Done"}
