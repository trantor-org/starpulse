"""Each task's Stays, kept in `starpulse_stays` as they happen and never rebuilt.

The recorder opens a Stay as a task enters a state on a machine and closes it with its length as the task leaves; the
session ledger adds each Model step to every Stay of its task that holds the step's time, so a step that arrives after
the move it came before goes to the Stay it came in. A step is spent once per machine: on the lane's Stay and on a flow
machine's Stay alike, since spend sums within one machine.
"""

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import ColumnElement, Connection, or_, select, update
from sqlalchemy.dialects import sqlite

from starpulse.event_log.readmodel import task_uuid
from starpulse.event_log.tables import stays
from starpulse.flow_metrics.model.spend import CLASSES, wte

__all__ = ["enter", "spend"]

def enter(db: Connection, task: str, machine: str, state: str, at: float, last: tuple[float, str] | None) -> None:
    """Close the Stay `task` holds on `machine` with its length at `at`, and open one in `state` from `at`.

    `last`, the time and state of the task's move before on the machine, gives a reconstructed Stay of unknown spend
    when the task entered it before Stays were kept."""
    c = stays.c
    uuid = task_uuid.of(task)
    held = (_of(task), c.machine == machine, c.seconds.is_(None), c.entered_at <= at)
    closed = db.execute(update(stays).where(*held).values(seconds=at - c.entered_at)).rowcount
    keyed = {"task": task, "task_uuid": uuid, "machine": machine}
    if not closed and last is not None and last[1] and last[0] <= at:
        before = keyed | {"state": last[1], "entered_at": last[0], "seconds": at - last[0], "reconstructed": True, "spend": None}
        db.execute(sqlite.insert(stays).values(before).on_conflict_do_nothing())
    db.execute(sqlite.insert(stays).values(keyed | {"state": state, "entered_at": at, "spend": []}).on_conflict_do_nothing())


def spend(db: Connection, steps: Iterable[Mapping[str, Any]]) -> None:
    """Add each of `steps`, a Model step naming its task, to the spend of every Stay of the task that holds its time,
    under its model and effort pair. A Stay whose spend is unknown stays unknown."""
    c = stays.c
    changed: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
    for step in steps:
        held = db.execute(
            select(c.task, c.machine, c.entered_at, c.spend).where(
                _of(step["task"]),
                c.entered_at <= step["at"],
                or_(c.seconds.is_(None), c.entered_at + c.seconds > step["at"]),
                c.spend.is_not(None),
            )
        )
        for task, machine, entered_at, pairs in held:
            key = task, machine, entered_at
            changed[key] = _added(changed.get(key, pairs), step)
    for (task, machine, entered_at), pairs in changed.items():
        db.execute(
            update(stays).where(c.task == task, c.machine == machine, c.entered_at == entered_at).values(spend=pairs)
        )


def _of(task: str) -> ColumnElement[bool]:
    return or_(stays.c.task_uuid == task_uuid.of(task), stays.c.task == task)  # a task the board gives no UUID yet


def _added(pairs: list[dict[str, Any]], step: Mapping[str, Any]) -> list[dict[str, Any]]:
    model, effort, tokens = step["model"], step["effort"] or None, step["tokens"]
    pair = next((p for p in pairs if p["model"] == model and p["effort"] == effort), None)
    if pair is None:
        pair = {"model": model, "effort": effort, "steps": 0, **dict.fromkeys(CLASSES, 0), "wte": 0.0}
        pairs = sorted([*pairs, pair], key=lambda p: (p["model"], p["effort"] or ""))
    pair["steps"] += 1
    for name in CLASSES:
        pair[name] += tokens[name]
    pair["wte"] += wte(tokens)
    return pairs
