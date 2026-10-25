"""A worker beside `serve` reads the Board the way the Board child serves it: from the read model when the config
turns it on, since no replica of the task files is published then."""

import threading
from dataclasses import replace
from pathlib import Path

from starpulse._internal.board.native import board
from starpulse._internal.board.task_history import KIND
from starpulse._internal.config.config import load
from starpulse.pulls.task_actor import ACTOR
from starpulse._internal.server.assembly import worker_board
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.tests.unit.board.test_native import write_task

PULL = "https://github.com/acme/trantor/pull/7"


def test_a_worker_reads_the_tasks_and_their_prs_from_the_read_model(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'events.sqlite'}"
    log = EventLog(url)
    events = EventStore(log.engine)
    created = NewEvent(type="TaskCreated", payload={"title": "Task", "state": "Review"}, actor="adin", writer="operator")
    cited = NewEvent(type="FieldsEdited", payload={"changes": {"references": [PULL]}}, actor="adin", writer="operator")
    events.append("task", "TASK-1", 0, [created, cited])
    Projector(log.engine, events).catch_up()
    stop = threading.Event()

    _, feed = worker_board(replace(load(None), read_model=True, database_url=url), tmp_path, log, "test", stop)
    stop.set()

    assert feed.wait_replayed(1)
    assert [(agent["id"], agent["prs"]) for agent in feed.open_tasks()] == [("TASK-1", [PULL])]


def test_a_read_model_workers_board_write_lands_in_the_task_history_the_read_model_folds(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'events.sqlite'}"
    log = EventLog(url)
    board({}, tmp_path)  # makes the default lanes
    write_task(tmp_path, "task-1", "Review")
    stop = threading.Event()

    built, _ = worker_board(replace(load(None), read_model=True, database_url=url), tmp_path, log, "test", stop)
    stop.set()
    assert built.edit is not None
    assert built.edit("task-1", {"status": "Done"}, "merged", actor=ACTOR).ok

    assert any(event.type == "Transitioned" for event in EventStore(log.engine).read(KIND, "task-1"))
