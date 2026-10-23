"""The projector: a Task's row is what its History folds into, however the Events were batched or the projector restarted."""

import random
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from hypothesis import Phase, given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, text

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.readmodel.fold import replay
from starpulse._internal.readmodel.projector import Projector
from starpulse._internal.readmodel.rows import load
from starpulse._internal.store import EventStore, NewEvent

_TASKS = ("TASK-1", "TASK-2", "TASK-3", "TASK-4")


@contextmanager
def _store() -> Iterator[tuple[Engine, EventStore]]:
    with tempfile.TemporaryDirectory() as directory:
        engine = EventLog(f"sqlite:///{Path(directory) / 'events.sqlite'}").engine
        yield engine, EventStore(engine)
        engine.dispose()


def _new(type: str, **payload: object) -> NewEvent:
    return NewEvent(type=type, payload=payload, actor="adin", writer="operator")


def _commands(rng: random.Random, steps: int) -> list[tuple[str, NewEvent]]:
    """A valid random History for four Tasks: every Task is created first, then edited, claimed, checked and archived."""
    commands = [(task, _new("TaskCreated", title=f"Title {task}", state="Ready")) for task in _TASKS]
    criteria: dict[str, list[tuple[str, int]]] = {task: [] for task in _TASKS}
    for step in range(steps):
        task = rng.choice(_TASKS)
        kind = rng.choice(("edit", "criterion", "check", "comment", "claim", "release", "move", "archive", "rehydrate"))
        if kind == "criterion":
            which = rng.choice(("ac", "dod"))
            criteria[task].append((which, 1 + sum(1 for k, _ in criteria[task] if k == which)))
            commands.append((task, _new("CriterionAdded", kind=which, text=f"item {step}")))
        elif kind == "check" and criteria[task]:
            which, n = rng.choice(criteria[task])
            commands.append((task, _new("CriterionChecked", kind=which, n=n, checked=rng.random() < 0.7, evidence=f"run {step}")))
        elif kind == "comment":
            commands.append((task, _new("CommentAdded", text=f"note {step}", author="adin")))
        elif kind == "claim":
            commands.append((task, _new("Claimed", assignee=f"session-{step}")))
        elif kind == "release":
            commands.append((task, _new("Released")))
        elif kind == "move":
            commands.append((task, _new("Transitioned", to=rng.choice(("Ready", "In Progress", "Review", "Done")))))
        elif kind == "archive":
            commands.append((task, _new("Archived")))
        elif kind == "rehydrate":
            commands.append((task, _new("Rehydrated")))
        else:
            commands.append((task, _new("FieldsEdited", changes={"title": f"Edited {step}"}, fields={"area": rng.choice("abc")}, meta={"step": step})))
    return commands


def _append(store: EventStore, commands: list[tuple[str, NewEvent]]) -> None:
    for task, event in commands:
        store.append("task", task, store.head("task", task), [event])


def _rows(engine: Engine) -> dict[str, dict]:
    with engine.connect() as db:
        return {task: row for task in _TASKS if (row := load(db, task)) is not None}


@given(seed=st.integers(0, 2**32), split=st.floats(0, 1))
@settings(max_examples=10, deadline=None, phases=(Phase.generate,))
def test_every_tasks_row_equals_the_replay_of_its_history_whenever_the_projector_stopped(seed: int, split: float) -> None:
    commands = _commands(random.Random(seed), steps=30)
    cut = int(len(commands) * split)
    with _store() as (engine, store):
        _append(store, commands[:cut])
        Projector(engine, store).catch_up()
        _append(store, commands[cut:])
        Projector(engine, store).catch_up()

        assert _rows(engine) == {task: replay(store.read("task", task)) for task in _TASKS}


def test_catching_up_again_folds_nothing_and_leaves_the_rows_as_they_were() -> None:
    with _store() as (engine, store):
        _append(store, _commands(random.Random(7), steps=30))
        projector = Projector(engine, store)
        folded = projector.catch_up()
        before = _rows(engine)

        assert (folded, projector.catch_up(), _rows(engine)) == (folded, 0, before)
        assert folded > 0


def test_a_rebuild_replaces_a_damaged_projection_with_the_replay_of_every_history() -> None:
    with _store() as (engine, store):
        _append(store, _commands(random.Random(11), steps=30))
        projector = Projector(engine, store)
        projector.catch_up()
        expected = _rows(engine)
        with engine.begin() as db:
            db.execute(text("UPDATE starpulse_tasks SET title = 'damaged', state = 'Done'"))
            db.execute(text("DELETE FROM starpulse_task_criteria"))

        rebuilt = projector.rebuild()

        assert (rebuilt > 0, _rows(engine)) == (True, expected)
