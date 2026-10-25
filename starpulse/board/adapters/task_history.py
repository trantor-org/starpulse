"""The native board's writes as Events: each successful write appends what it changed to the Task's History (D2).

The board still writes the task's file; this records, per write, the intent the file's before and after show. A Task
with no History yet is seeded with a `TaskImported` of its record before the write, so a replay equals the row."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from sqlalchemy import Engine

from starpulse.board.model.seam import OPERATOR, Written
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore, NewEvent, StaleVersion

WRITER = "native-board"
#: The writer of Events an editor import appends: the operator's break-glass edit, not a command of the board (D5).
BREAK_GLASS = "break-glass"
_break_glass: ContextVar[bool] = ContextVar("break_glass", default=False)


@contextmanager
def break_glass() -> Iterator[None]:
    """Mark the Events the writes made inside as break-glass."""
    token = _break_glass.set(True)
    try:
        yield
    finally:
        _break_glass.reset(token)


KIND = "task"

#: The record's keys that are the fold's own Task fields, by the fold's name.
_OWN = {
    "title": "title",
    "type": "type",
    "status": "state",
    "priority": "priority",
    "milestone": "milestone",
    "description": "description",
    "plan": "plan",
    "notes": "notes",
    "finalSummary": "final_summary",
    "labels": "labels",
    "dependencies": "dependencies",
    "references": "references",
    "documentation": "documentation",
    "modifiedFiles": "modified_files",
}
_LISTS = ("labels", "dependencies", "references", "documentation", "modifiedFiles")
#: The record's keys the fold keeps in `meta`.
_META = ("profile", "impact", "urgency", "start_criteria")
#: The record's criteria lists, by the kind the fold keeps them under.
_KINDS = {"ac": "acceptanceCriteria", "dod": "definitionOfDone"}

Record = Mapping[str, Any]
Event = tuple[str, dict[str, Any]]


def _criteria(record: Record) -> dict[str, list[dict[str, Any]]]:
    return {kind: list(record.get(key) or []) for kind, key in _KINDS.items()}


def _fold_criteria(record: Record) -> list[dict[str, Any]]:
    """The record's criteria as the fold keeps them, `ac` before `dod`."""
    rows = []
    for kind, items in _criteria(record).items():
        for item in items:
            rows.append(
                {
                    "kind": kind,
                    "n": item["n"],
                    "text": item["text"],
                    "checked": bool(item.get("checked")),
                    "evidence": "",
                }
            )
    return rows


def _comments(record: Record) -> list[Mapping[str, Any]]:
    return list(record.get("comments") or [])


def seed(record: Record, at: float) -> dict[str, Any]:
    """What a Task's first Event holds: every column the record shows."""
    seed: dict[str, Any] = {}
    for key, name in _OWN.items():
        seed[name] = list(record.get(key) or []) if key in _LISTS else record.get(key) or ""
    seed["meta"] = {key: record[key] for key in _META if record.get(key)}
    seed["assignee"] = record.get("session") or ""
    seed["criteria"] = _fold_criteria(record)
    seed["comments"] = [
        {"at": at, "actor": item.get("author", ""), "text": item.get("text", "")} for item in _comments(record)
    ]
    return seed


def _field_changes(before: Record, after: Record) -> dict[str, Any]:
    changes = {}
    for key, name in _OWN.items():
        if key != "status" and before.get(key) != after.get(key):
            changes[name] = after.get(key)
    return changes


def _meta_changes(before: Record, after: Record) -> dict[str, Any]:
    return {key: after.get(key) or None for key in _META if before.get(key) != after.get(key)}


def _criteria_events(before: Record, after: Record) -> list[Event]:
    """The criterion Events from `before` to `after`; a criterion changed any other way is one whole-list field edit."""
    events: list[Event] = []
    old, new = _criteria(before), _criteria(after)
    for kind in _KINDS:
        kept, items = old[kind], new[kind]
        grown = len(items) >= len(kept) and all(a["text"] == b["text"] for a, b in zip(kept, items, strict=False))
        numbered = all(item["n"] == index for index, item in enumerate(items, start=1))
        if not (grown and numbered):
            return [("FieldsEdited", {"changes": {"criteria": _fold_criteria(after)}})]
        for old_item, item in zip(kept, items, strict=False):
            if bool(old_item.get("checked")) != bool(item.get("checked")):
                events.append(
                    ("CriterionChecked", {"kind": kind, "n": item["n"], "checked": bool(item.get("checked"))})
                )
        events += [("CriterionAdded", {"kind": kind, "text": item["text"]}) for item in items[len(kept) :]]
    return events


def _restored(record: Record) -> Event:
    """A returning task's FieldsEdited: every column its file shows, so the fold's row is the file's, not the one it left with."""
    columns = seed(record, 0.0)
    columns.pop("comments")
    columns.pop("meta")
    meta = {key: record.get(key) or None for key in _META}
    return ("FieldsEdited", {"changes": columns, "meta": meta})


def _events(before: Record, after: Record | None, note: str) -> list[Event]:
    """The Events that take `before` to `after`; None is a task that left the board, `{}` one that was not on it."""
    if after is None:
        return ([("CommentAdded", {"text": note})] if note else []) + [("Archived", {})]
    if not before:
        return [("Rehydrated", {}), _restored(after)]
    events: list[Event] = []
    edited: dict[str, Any] = {}
    changes, meta = _field_changes(before, after), _meta_changes(before, after)
    if changes:
        edited["changes"] = changes
    if meta:
        edited["meta"] = meta
    if edited:
        events.append(("FieldsEdited", edited))
    if before.get("status") != after.get("status"):
        events.append(("Transitioned", {"from": before.get("status"), "to": after.get("status")}))
    events += _criteria_events(before, after)
    events += [("CommentAdded", {"text": item.get("text", "")}) for item in _comments(after)[len(_comments(before)) :]]
    if before.get("session") != after.get("session"):
        held = after.get("session")
        events.append(("Claimed", {"assignee": held}) if held else ("Released", {}))
    return events


class TaskHistory:
    """Appends a board write's Events once the log's engine is known; before that, a write records nothing."""

    def __init__(self) -> None:
        self._store: EventStore | None = None

    def attach(self, engine: Engine) -> None:
        self._store = EventStore(engine)

    def recorded(
        self,
        write: Callable[..., Written],
        read: Callable[[str], Record | None],
        *,
        actor_at: int | None = None,
        reason_at: int | None = None,
    ) -> Callable[..., Written]:
        """`write` (a verb taking a task id first) that appends what it changed once it succeeds.

        `actor_at` is the index in the arguments after the task of an actor passed positionally; `reason_at` that of an archive's reason."""

        def run(task: str, *args: Any, **kwargs: Any) -> Written:
            before = read(task)
            written = write(task, *args, **kwargs)
            if written.ok:
                actor = kwargs.get("actor") or (
                    args[actor_at] if actor_at is not None and len(args) > actor_at else OPERATOR
                )
                note = args[reason_at] if reason_at is not None and len(args) > reason_at else ""
                self._append(task, before, read(task), actor, note.strip())
            return written

        return run

    def created(self, create: Callable[..., Written], read: Callable[[str], Record | None]) -> Callable[..., Written]:
        """`create` that appends the new task's `TaskCreated` once it succeeds."""

        def run(title: str, details: Mapping[str, Any], /, actor: str = OPERATOR) -> Written:
            written = create(title, details, actor=actor)
            record = read(written.output) if written.ok else None
            if record is not None and self._store is not None:
                self._store.append(KIND, written.output, 0, [self._new("TaskCreated", seed(record, 0.0), actor)])
            return written

        return run

    def import_retired(self, rows: Iterable[tuple[str, str]], parse: Callable[[str], Record]) -> None:
        """Give each retired `(task, text)` row without History its `TaskImported` of `parse(text)` and an `Archived`."""
        store = self._store
        if store is None:
            return
        for task, text in rows:
            if store.head(KIND, task) == 0:
                events = [
                    self._new("TaskImported", seed(parse(text), 0.0), OPERATOR),
                    self._new("Archived", {}, OPERATOR),
                ]
                store.append(KIND, task, 0, events)

    def _append(self, task: str, before: Record | None, after: Record | None, actor: str, note: str) -> None:
        store = self._store
        if store is None:
            return
        for _ in range(2):
            head = store.head(KIND, task)
            if after is None and head and store.read(KIND, task, head - 1)[-1].type == "Archived":
                return  # retiring an archived task leaves the board no more than it already has
            base = before if before is not None else after
            # a status is diffed from the History's state, so a write whose earlier append was lost still records its move
            held = {**before, "status": replay(store.read(KIND, task))["state"]} if head and before else before
            events = _events(held or {}, after, note)
            seeded = [("TaskImported", seed(base, 0.0))] if head == 0 and base else []
            if not events and not seeded:
                return
            try:
                store.append(KIND, task, head, [self._new(kind, payload, actor) for kind, payload in seeded + events])
                return
            except StaleVersion:
                continue
        raise StaleVersion(f"task {task} kept moving while its History was appended to")

    @staticmethod
    def _new(kind: str, payload: dict[str, Any], actor: str) -> NewEvent:
        return NewEvent(kind, payload, actor, BREAK_GLASS if _break_glass.get() else WRITER)
