"""A read model over a temporary SQLite database, holding the tasks an adapter's `BoardTask` records place.

The adapter kit and the tests draw a `BoardFeed` from it: a record becomes the History Events the Board writer's files
become in a served board, and the Projector folds them into the rows the feed reads."""

import shutil
import tempfile
import threading
import uuid
import weakref
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.contracts.adapters import BoardTask
from starpulse.contracts.task_keys import TaskKeys
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.declared import Declared, declared_fields
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.readmodel.signals import EVENTS
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.event_log.wake import StopEvent
from starpulse.runtime.assembly import assemble, declared
from starpulse.runtime.config import Config
from starpulse.runtime.store_migrate import maintain

__all__ = ["Placed", "assembled"]

KIND = "task"
_META = ("profile", "impact", "urgency", "tier")


def placed_events(task: BoardTask, held: Mapping[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    """The Events that take the row `held` (None before the task's first Event) to the task `task` records."""
    columns: dict[str, Any] = {
        "title": task.title,
        "state": task.lane,
        "type": task.type,
        "milestone": task.milestone,
        "description": task.description,
        "labels": list(task.labels),
        "dependencies": list(task.dependencies),
        "references": list(task.references),
    }
    meta = {key: value for key in _META if (value := getattr(task, key))}
    if held is None:
        stamp = str(uuid.uuid5(uuid.NAMESPACE_URL, f"starpulse:placed:{task.id.upper()}"))  # the board stamps each task it creates
        events = [("TaskCreated", {**columns, "meta": {**meta, "uuid": stamp}, "assignee": task.assignee})]
    else:
        changes = {name: value for name, value in columns.items() if name != "state" and held[name] != value}
        edited: dict[str, Any] = {}
        if changes:
            edited["changes"] = changes
        kept = {key: value for key, value in held["meta"].items() if key != "uuid"}  # a stamp the record never carries
        if changed := {key: meta.get(key) for key in (*meta.keys(), *kept) if kept.get(key) != meta.get(key)}:
            edited["meta"] = changed
        events = [("FieldsEdited", edited)] if edited else []
        if held["state"] != task.lane:
            events.append(("Transitioned", {"from": held["state"], "to": task.lane}))
        if held["archived"] and task.settled != "archived":
            events.append(("Rehydrated", {}))
    events += _criteria(task, [] if held is None else held["criteria"])
    if task.settled == "archived" and not (held and held["archived"]):
        events.append(("Archived", {}))
    return events


def _criteria(task: BoardTask, held: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    ticks = {n: criterion["checked"] for n, criterion in enumerate(held, 1) if criterion["kind"] == "ac"}
    events: list[tuple[str, dict[str, Any]]] = []
    for n, text in enumerate(task.acceptance_criteria, 1):
        if n not in ticks:
            events.append(("CriterionAdded", {"kind": "ac", "text": text}))
            ticks[n] = False
        if (checked := n <= len(task.acceptance_checked) and task.acceptance_checked[n - 1]) != ticks[n]:
            events.append(("CriterionChecked", {"kind": "ac", "n": n, "checked": checked}))
    return events


class Placed:
    """The Events and read model of one temporary database; `put` and `retract` place a record as the board's files would
    and fold it, so a `BoardFeed` over `read_model` draws it."""

    def __init__(
        self,
        machines: Mapping[str, dict] | None = None,
        keys: TaskKeys | None = None,
        fields: Mapping[str, Declared] | None = None,
        directory: Path | None = None,
    ) -> None:
        """A temporary database, or `events.sqlite` in `directory` when a test shares its store with other readers."""
        kept = directory is not None
        directory = directory or Path(tempfile.mkdtemp(prefix="placed-"))
        url = f"sqlite:///{directory / 'events.sqlite'}"
        maintain(url, machines or {})
        self.keys = keys
        self.log = EventLog(url)
        self.events = EventStore(self.log.engine)
        self.projector = Projector(self.log.engine, self.events, log=self.log, drawn=machines, keys=keys)
        self.read_model = ReadModel(self.log.engine, fields)
        #: Closes the log and removes the files: when the feed that reads the read model is collected, or on `close`.
        self.close = weakref.finalize(self.read_model, _discard, self.log, None if kept else directory)
        self.feed: BoardFeed | None = None
        self._folding = threading.RLock()

    def draw(self, **settings: Any) -> BoardFeed:
        """A `BoardFeed` over the read model, told of each fold; `settings` are its keyword arguments."""
        self.feed = BoardFeed(self.read_model, **settings)
        return self.feed

    def follow(self, stop: StopEvent) -> threading.Thread:
        """Fold on each wake of the log until `stop`: what a write instance's Board writer appends."""
        thread = threading.Thread(
            target=self.log.run_on_wake,
            args=(stop, self.fold, "the read model pass failed", EVENTS),
            name="placed-follow",
            daemon=True,
        )
        thread.start()
        return thread

    def put(self, task: BoardTask) -> None:
        """Place `task` where its record says: its lane, or settled, with its fields, at its `observed_at` when it has one. A task outside the adapter's keys is
        not placed."""
        if self.keys is not None and not self.keys.matches(task.id):
            return
        stream = self.events.read(KIND, task.id)
        if events := placed_events(task, replay(stream) if stream else None):
            self.events.append(KIND, task.id, len(stream), [_new(kind, payload) for kind, payload in events], at=task.observed_at)
        if self.feed is not None:
            for alias in task.aliases:  # a scanned task names them: the read model holds them as meta `aliases`
                self.feed.alias(alias, task.id)
        self.fold()

    def retract(self, task_id: str) -> None:
        """Take `task_id` off the board, as a task whose file is gone leaves it."""
        stream = self.events.read(KIND, task_id)
        if stream and not replay(stream)["archived"]:
            self.events.append(KIND, task_id, len(stream), [_new("Archived", {})])
        self.fold()

    def catch_up(self) -> None:
        """Fold what was appended."""
        with self._folding:
            self.projector.catch_up()

    def fold(self) -> None:
        """Fold what was appended and tell the feed's subscribers."""
        with self._folding:
            self.catch_up()
            if self.feed is not None:
                self.feed.follow_read_model()


def _new(kind: str, payload: dict[str, Any]) -> NewEvent:
    return NewEvent(type=kind, payload=payload, actor="adin", writer="operator")


def _discard(log: EventLog, directory: Path | None) -> None:
    log.close()
    if directory is not None:
        shutil.rmtree(directory, ignore_errors=True)


def assembled(config: Config, base: Path) -> tuple[Board, BoardFeed, Placed]:
    """The board the config's `[board]` adapter builds and the feed that draws it from a temporary read model, as
    `starpulse serve` assembles them."""
    board, machines, *_ = declared(config, base)
    placed = Placed(machines, board.keys, declared_fields(config.board))
    board, feed = assemble(config, base, None, placed.read_model)
    placed.feed = feed
    return board, feed, placed
