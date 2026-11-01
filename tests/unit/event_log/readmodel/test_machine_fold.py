"""The Board child's projector folds `machine:events` into `starpulse_machine_tasks`, and `starpulse migrate` folds a
backup of a live database the same way."""

import sqlite3
import time
from pathlib import Path

from sqlalchemy import Engine, select
from starpulse.event_log import events as machine_events
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.tables import machine_tasks
from starpulse.event_log.store import EventStore
from starpulse.runtime.store_migrate import maintain

from tests.machines import MACHINES


def _rows(engine: Engine) -> list[tuple]:
    statement = select(machine_tasks.c.machine, machine_tasks.c.task, machine_tasks.c.state).order_by(
        machine_tasks.c.machine, machine_tasks.c.task
    )
    with engine.connect() as db:
        return [tuple(row) for row in db.execute(statement)]


def _publish(log: EventLog, at: float) -> None:
    machine_events.publish("in-progress", "WORKTREE_READY", actor="agent", task="PROJ-1", now=at, log=log)
    machine_events.publish("in-progress", "AC_CHECKPOINTED", actor="agent", task="PROJ-2", now=at, log=log)


def test_the_projector_writes_a_row_per_machine_task(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    _publish(log, time.time())

    Projector(log.engine, EventStore(log.engine), log=log, drawn=MACHINES).catch_up()

    assert _rows(log.engine) == [("in-progress", "PROJ-1", "worktree_ready"), ("in-progress", "PROJ-2", "checkpointed")]


def test_the_projector_resumes_from_its_checkpoint_and_folds_only_new_entries(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    projector = Projector(log.engine, EventStore(log.engine), log=log, drawn=MACHINES)
    _publish(log, time.time())
    projector.catch_up()

    machine_events.publish("in-progress", "WORKTREE_READY", actor="agent", task="PROJ-3", log=log)
    projector.catch_up()

    assert [task for _, task, _ in _rows(log.engine)] == ["PROJ-1", "PROJ-2", "PROJ-3"]


def test_starpulse_migrate_folds_the_machine_events_a_backup_holds_into_the_table(tmp_path: Path) -> None:
    live = tmp_path / "live.sqlite"
    log = EventLog(f"sqlite:///{live}")
    _publish(log, time.time())
    backup = tmp_path / "live.backup.sqlite"
    source, copy = sqlite3.connect(live), sqlite3.connect(backup)
    source.backup(copy)  # the backup API, so WAL frames not yet checkpointed are copied too
    copy.close()
    source.close()

    maintain(f"sqlite:///{backup}", MACHINES, None, fold=True)

    assert _rows(EventLog(f"sqlite:///{backup}").engine) == [
        ("in-progress", "PROJ-1", "worktree_ready"),
        ("in-progress", "PROJ-2", "checkpointed"),
    ]
