"""The task History the native board serves its reads and writes from: a task's replayed row, the alias a task answers to,
and the dependency graph. A task is held nowhere else: no file of it is written (D2)."""

import copy
import threading
from collections.abc import Collection
from typing import Any

from sqlalchemy import Engine

from starpulse.board.adapters.task_history import KIND
from starpulse.event_log.readmodel.fold import Row, apply
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore

#: How many replayed rows are kept, the least recently read dropped first.
_KEPT = 2048
#: A `since` no task changed at or after, so `open` leaves out every Done task.
_FOREVER = 1e18


class TaskView:
    """Replays each task's History once, then folds only the Events appended since; a reader sees a row at the head it
    read, never the projector's lag."""

    def __init__(self) -> None:
        self._store: EventStore | None = None
        self._model: ReadModel | None = None
        self._rows: dict[str, Row] = {}
        self._aliases: dict[str, str] = {}
        self._lock = threading.Lock()

    def attach(self, engine: Engine) -> None:
        self._store, self._model = EventStore(engine), ReadModel(engine)
        self.listed()

    def listed(self) -> list[tuple[str, list[str]]]:
        """Each task that lists an alias with its aliases, as the History names them now."""
        if self._model is None:
            return []
        found: dict[str, list[str]] = {}
        for alias, task in self._model.aliased().items():
            found.setdefault(task, []).append(alias)
        with self._lock:
            self._aliases = {alias.casefold(): task for task, aliases in found.items() for alias in aliases}
        return list(found.items())

    def open(self, done: str | None) -> list[dict[str, Any]]:
        """The unarchived tasks not in the `done` lane, as the read model has folded them: each one's id, milestone, labels,
        dependencies, references and meta."""
        return [] if self._model is None else self._model.snapshot(done or "", _FOREVER)

    def finished(self, done: str | None) -> list[str]:
        """The ids of the unarchived tasks in the `done` lane, of any age, as the read model has folded them."""
        return [] if self._model is None or not done else self._model.held_done(done)

    def taken(self) -> list[str]:
        """Every id a task has a History under, and every alias a task lists: the names a new task cannot take."""
        store = self._store
        if store is None:
            return []
        with self._lock:
            aliases = {*self._aliases, *(alias.casefold() for alias in (self._model.aliased() if self._model else ()))}
        return [*store.heads(KIND), *aliases]

    def dependencies_of(self, ids: Collection[str]) -> dict[str, list[str]]:
        return self._model.dependencies_of(ids) if self._model is not None else {}

    def row(self, task: str) -> Row | None:
        """`task`'s row at its History's head, found by its id, then an alias, then its id in any case; None for a task with
        no History. The row is shared: a reader copies what it keeps."""
        store = self._store
        if store is None or (key := self._key(task)) is None:
            return None
        with self._lock:
            held = self._rows.get(key)
        if not (events := store.read(KIND, key, held["version"] if held else 0)):
            return held
        row = copy.deepcopy(held) if held else None
        for event in events:
            row = apply(row, event)
        assert row is not None  # at least one event was folded
        with self._lock:
            self._rows.pop(key, None)
            self._rows[key] = row
            while len(self._rows) > _KEPT:
                del self._rows[next(iter(self._rows))]
            for alias in row["meta"].get("aliases") or []:
                self._aliases[alias.casefold()] = key
        return row

    def _key(self, task: str) -> str | None:
        store, model = self._store, self._model
        if store is None or model is None:
            return None
        with self._lock:
            if task in self._rows:
                return task
            aliased = self._aliases.get(task.casefold())
        if store.head(KIND, task):
            return task
        if aliased:
            return aliased
        found = model.task(task)
        return str(found["id"]) if found else None
