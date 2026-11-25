"""The task_spend family: each task's sessions and its spend per phase, derived from the `spend` fold rows, so one
task's spend reads the folds of the sessions naming it and its peers' phase rows rather than every fold of the window.

`TaskSpend.catch_up` follows the spend folds rewritten past its cursor (`CURSOR`), as `SignalFolds.catch_up` follows the
cost folds. It links each such session to the tasks it names (`spend.named`) and recomputes, from all of a task's
sessions, the phase rows of every task the session named before or names now. The stamp covers the tables' definition
and the source that computes them, so an edit to either empties the tables and refolds every spend fold.
"""

import hashlib
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, bindparam, delete, insert, select
from sqlalchemy.dialects import sqlite

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.table_registry import definition, is_stamped, stamp_of, swap, write_stamp
from starpulse.event_log.tables import settings, signal_folds, task_phase_spend, task_sessions
from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.adapters.outbound.session_ledger import REVISION
from starpulse.flow_metrics.model import spend

__all__ = ["CURSOR", "FAMILY", "STAMP", "TaskSpend"]

#: The settings key holding the revision every spend fold at or below it is linked and summed at.
CURSOR = "task_spend_cursor"
FAMILY = "task_spend"
_TABLES = (task_sessions, task_phase_spend)
STAMP = stamp_of(
    definition(_TABLES), *(hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in (spend.__file__, __file__))
)
_FOLD = select(signal_folds.c.result).where(
    signal_folds.c.view == "spend",
    signal_folds.c.harness == bindparam("harness"),
    signal_folds.c.session == bindparam("session"),
)


def _sessions_of(db: Connection, task: str) -> set[tuple[str, str]]:
    found = db.execute(select(task_sessions.c.harness, task_sessions.c.session).where(task_sessions.c.task == task))
    return {(row.harness, row.session) for row in found}


def _phases_of(
    db: Connection, linked: dict[str, set[tuple[str, str]]], read: dict[tuple[str, str], Any]
) -> list[dict[str, Any]]:
    sessions = sorted(set().union(*linked.values()))
    folds = [
        read[key] if key in read else db.execute(_FOLD, {"harness": key[0], "session": key[1]}).scalar_one()
        for key in sessions
    ]
    return [
        {"task": task, "phase": phase, "profile": row["profile"], "wte": row["wte"], "last_at": row["last_at"]}
        for (task, phase), row in spend.phase_rows(folds).items()
        if task in linked
    ]


class TaskSpend:
    """Keeps the task_spend family in step with the spend folds."""

    def __init__(self, events: EventLog) -> None:
        self._events = events

    def catch_up(self) -> int:
        """Relink and resum each session whose spend fold was rewritten past the cursor, and return how many that was.

        An unstamped family is emptied and refolds from revision 0. The links, the phase rows, the cursor and the stamp
        are written in one transaction, so a reader sees one pass whole; the cursor moves to the revision read before
        the folds, so a fold rewritten during the pass is the next pass's. Raises when the database does."""
        engine = self._events.engine
        with engine.connect() as db:
            stamped = is_stamped(db, FAMILY, STAMP)
        if not stamped:
            with engine.begin() as db:
                swap(db, FAMILY, _TABLES)
        cursor = (self._events.setting(CURSOR) or 0) if stamped else 0
        through = self._events.setting(REVISION) or 0
        if stamped and through <= cursor:
            return 0
        with engine.connect() as db:
            rows = db.execute(
                select(signal_folds.c.harness, signal_folds.c.session, signal_folds.c.result).where(
                    signal_folds.c.view == "spend",
                    signal_folds.c.folded_through > cursor,
                    signal_folds.c.folded_through <= through,
                )
            )
            read = {(row.harness, row.session): row.result for row in rows}
            changed = {key: spend.named(result) for key, result in read.items()}
            linked: dict[str, set[tuple[str, str]]] = {}
            for (harness, session), tasks in changed.items():
                before = db.execute(
                    select(task_sessions.c.task).where(
                        task_sessions.c.harness == harness, task_sessions.c.session == session
                    )
                ).scalars()
                for task in {*before, *tasks}:
                    if task not in linked:
                        linked[task] = _sessions_of(db, task) - changed.keys()
                    if task in tasks:
                        linked[task].add((harness, session))
            phases = _phases_of(db, linked, read)
        with engine.begin() as db:
            if changed:
                db.execute(
                    delete(task_sessions).where(
                        task_sessions.c.harness == bindparam("h"), task_sessions.c.session == bindparam("s")
                    ),
                    [{"h": h, "s": s} for h, s in changed],
                )
            links = [{"task": t, "harness": h, "session": s} for (h, s), tasks in changed.items() for t in tasks]
            if links:
                db.execute(insert(task_sessions), links)
            if linked:
                db.execute(
                    delete(task_phase_spend).where(task_phase_spend.c.task == bindparam("t")),
                    [{"t": task} for task in linked],
                )
            if phases:
                db.execute(insert(task_phase_spend), phases)
            now = time.time()
            kept = sqlite.insert(settings).values(key=CURSOR, value=through, updated_at=now)
            db.execute(
                kept.on_conflict_do_update(index_elements=[settings.c.key], set_={"value": through, "updated_at": now})
            )
            if not stamped:
                write_stamp(db, FAMILY, STAMP)
        return len(changed)

    def follow(self, stop: StopEvent) -> None:
        """Run `catch_up` after each append or another process's commit until `stop` is set."""
        self._events.run_on_wake(stop, self.catch_up, "task spend catch-up failed")
