"""The native board's writes as Events: each write appends what it changes to the Task's History (D2) before it renders the file.

A write reads its base from the History, appends the Events that take it to the file the write would render, with a
compare-and-swap at the head it read, and only then writes the file. An append that fails or loses the swap fails the
write and writes no file; a Task with no History refuses every write."""

import json
from collections import Counter
from collections.abc import Callable, Collection, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from starpulse.board.model import criteria
from starpulse.board.model.seam import OPERATOR, Written
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore, NewEvent, StaleVersion
from starpulse.machine_engine.model.transitions import lane_id

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
_META = (
    "profile",
    "impact",
    "urgency",
    "tier",
    "start_criteria",
    "source",
    "needsAttention",
    "follows",
    "dependencyNeeds",
    "actorMemory",
    "members",
    "createdBy",
    "aliases",
    "uuid",
    "uuids",
    "frozen",
)
#: The meta keys a dedicated Event records, so a `FieldsEdited` never carries them.
_EVENTED = ("frozen",)
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
    seed["assignee"] = record.get("assignee") or ""
    seed["criteria"] = _fold_criteria(record)
    seed["comments"] = [
        {"at": at, "actor": item.get("author", ""), "text": item.get("text", ""), "created": item.get("created", "")}
        for item in _comments(record)
    ]
    return seed


def _replayed(row: Record) -> dict[str, Any]:
    """The record a replayed `row` draws, in the shape of a task file's record."""
    record: dict[str, Any] = {key: row[name] for key, name in _OWN.items()}
    record |= {key: row["meta"].get(key) for key in _META}
    for kind, key in _KINDS.items():
        record[key] = [item for item in row["criteria"] if item["kind"] == kind]
    record["assignee"] = row["assignee"]
    record["comments"] = [{"text": item["text"]} for item in row["comments"]]
    return record


def _column(record: Record, key: str) -> Any:
    return list(record.get(key) or []) if key in _LISTS else record.get(key) or ""


def _field_changes(before: Record, after: Record) -> dict[str, Any]:
    return {
        name: after.get(key)
        for key, name in _OWN.items()
        if key != "status" and _column(before, key) != _column(after, key)
    }


def _meta_value(record: Record, key: str) -> Any:
    value = record.get(key) or None
    return criteria.bare(value) if key == "start_criteria" and value else value


def _meta_changes(before: Record, after: Record) -> dict[str, Any]:
    return {
        key: after.get(key) or None
        for key in _META
        if key not in _EVENTED and _meta_value(before, key) != _meta_value(after, key)
    }


def _freeze_events(before: Record, after: Record) -> list[Event]:
    """A `TaskUnfrozen` of the freeze `after` lifts and a `TaskFrozen` of the one it sets."""
    was, now = dict(before.get("frozen") or {}), dict(after.get("frozen") or {})
    if was == now:
        return []
    return ([("TaskUnfrozen", was)] if was else []) + ([("TaskFrozen", now)] if now else [])


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
        for item in items[len(kept) :]:
            events.append(("CriterionAdded", {"kind": kind, "text": item["text"]}))
            if item.get("checked"):
                events.append(("CriterionChecked", {"kind": kind, "n": item["n"], "checked": True}))
    return events


def revises_plan(status: str, held: str, plan: str, unstarted: Collection[str]) -> bool:
    """Whether writing `plan` over `held` on a task in `status` changes a plan that work began under (D10).

    The first plan of a started task is no revision, and neither is a plan written while the task is still unstarted."""
    return bool(held) and plan != held and lane_id(status) not in unstarted


def _comment_events(before: Record, after: Record) -> list[Event]:
    """A `CommentAdded` for each comment of `after` that `before` does not hold, so a note the file holds alone is recorded
    though the History holds others the file lacks."""
    held = Counter(item.get("text", "") for item in _comments(before))
    events: list[Event] = []
    for item in _comments(after):
        text = item.get("text", "")
        if held[text]:
            held[text] -= 1
        else:
            events.append(("CommentAdded", {"text": text}))
    return events


def _events(before: Record, after: Record | None, note: str) -> list[Event]:
    """The Events that take `before` to `after`; None is a task that left the board."""
    if after is None:
        return ([("CommentAdded", {"text": f"Archived: {note}"})] if note else []) + [("Archived", {})]
    events: list[Event] = []
    edited: dict[str, Any] = {}
    changes, meta = _field_changes(before, after), _meta_changes(before, after)
    if changes:
        edited["changes"] = changes
    if meta:
        edited["meta"] = meta
    if edited:
        events.append(("FieldsEdited", edited))
    events += _freeze_events(before, after)
    if before.get("status") != after.get("status"):
        events.append(("Transitioned", {"from": before.get("status"), "to": after.get("status")}))
    events += _criteria_events(before, after)
    events += _comment_events(before, after)
    if (before.get("assignee") or "") != (after.get("assignee") or ""):
        held = after.get("assignee")
        events.append(("Claimed", {"assignee": held}) if held else ("Released", {}))
    return events


def _plan_reason(args: tuple[Any, ...]) -> str:
    """The reason an edit's changes (its first argument) give for rewriting the plan; blank when it gives none."""
    changes = args[0] if args else None
    return str(changes.get("planReason") or "").strip() if isinstance(changes, Mapping) else ""


class Refused(Exception):
    """A write whose Events its Task's History could not take: nothing is written."""


@dataclass(frozen=True)
class _Write:
    history: "TaskHistory"
    unstarted: Collection[str] | None
    reason: str
    moves: bool
    task: str


_write: ContextVar[_Write | None] = ContextVar("task_write", default=None)


def appended(
    task: str,
    after: Record | None,
    actor: str,
    *,
    created: bool = False,
    note: str = "",
    rehydrates: bool = False,
    before: Record | None = None,
) -> None:
    """Append the Events that take `task`'s History to `after`, the file about to be rendered (None: the task leaves the
    board, with `note` as its reason), as `actor`; nothing outside a recorded write.

    `created` makes them the task's first Event, and `rehydrates` leads them with a `Rehydrated` when the task replays archived.
    `before` is the file the write replaces: the Events are what the write changed in it, so a hand edit the file held
    already is never imported by a later write; without it they diff the History's replay against `after`.
    Raises `StaleVersion` when the History moved after it was read, and `Refused` when it cannot take the Events."""
    if (write := _write.get()) is None:
        return
    history = write.history

    def events(row: Record, revisions: int) -> list[Event]:
        if after is None:
            return [] if row["archived"] else _events({}, None, note)
        base = before if before is not None else _replayed(row)
        if write.moves and before is not None and task.casefold() == write.task.casefold():
            base = {**before, "status": _replayed(row)["status"]}  # an explicit move is judged against the History, not a file a hand edit already moved
        found = ([("Rehydrated", {})] if rehydrates and row["archived"] else []) + _events(base, after, note)
        if write.reason and revises_plan(row["state"], row["plan"], after.get("plan") or "", write.unstarted or ()):
            found.append(("PlanRevised", {"ordinal": revisions + 1, "reason": write.reason}))
        return found

    history.append(task, actor, events, created=after if created else None)


class TaskHistory:
    """Appends a board write's Events once the log's engine is known; before that, a write records nothing."""

    def __init__(self) -> None:
        self._store: EventStore | None = None

    def attach(self, engine: Engine) -> None:
        self._store = EventStore(engine)

    def recorded(
        self, write: Callable[..., Written], *, unstarted: Collection[str] | None = None, moves: bool = False
    ) -> Callable[..., Written]:
        """`write` (a verb taking a task id first) with each change of a file it makes appended to its Task's History first,
        through `appended`, `archived` and `rehydrated`; a write whose append fails or loses its swap is not ok.

        `unstarted` (an edit's lanes where work has not begun) makes a plan change with a `planReason` in the changes also
        append a numbered `PlanRevised`. `moves` marks `write` an explicit move to a status, whose `Transitioned` for the moved task compares the
        History's status, not the file's, so a file a hand edit already moved there still records the move; another
        task the move edits (an archive's dependents) keeps its file's status as the base."""

        def run(task: str, *args: Any, **kwargs: Any) -> Written:
            reason = _plan_reason(args) if unstarted is not None else ""
            token = _write.set(_Write(self, unstarted, reason, moves, task))
            try:
                return write(task, *args, **kwargs)
            except Refused as refused:
                return Written(False, str(refused))
            except StaleVersion:
                return Written(False, f"{task}: its History changed while it was written", transient=True)
            finally:
                _write.reset(token)

        return run

    def imported(self, task: str, record: Record, archived: bool) -> bool:
        """Give `task` without History its `TaskImported` of `record`, and an `Archived` when it has left the lanes; whether it got them."""
        store = self._store
        if store is None or store.head(KIND, task):
            return False
        events = [self._new("TaskImported", seed(record, 0.0), OPERATOR)]
        if archived:
            events.append(self._new("Archived", {}, OPERATOR))
        store.append(KIND, task, 0, events)
        return True

    def settle(self, task: str, archived: bool) -> bool:
        """Append an `Archived`, or a `Rehydrated`, to `task`'s History when it replays the other way; whether it did."""
        store = self._store
        head = store.head(KIND, task) if store else 0
        if store is None or not head or replay(store.read(KIND, task))["archived"] == archived:
            return False
        store.append(KIND, task, head, [self._new("Archived" if archived else "Rehydrated", {}, OPERATOR)])
        return True

    def append(
        self, task: str, actor: str, events: Callable[[Record, int], list[Event]], *, created: Record | None = None
    ) -> None:
        """Append what `events` makes of the replay of `task`'s History at the head read, at that head; a created task's
        `TaskCreated` of `created` at none."""
        store = self._store
        if store is None:
            return
        head = store.head(KIND, task)
        if created is not None:
            if head:
                raise Refused(f"{task} already has a History")
            batch: list[Event] = [("TaskCreated", seed(created, 0.0))]
        elif not head:
            raise Refused(f"{task} has no History, so it takes no write")
        else:
            stored = store.read(KIND, task)
            batch = events(replay(stored), sum(1 for event in stored if event.type == "PlanRevised"))
        if not batch:
            return
        try:
            store.append(KIND, task, head, [self._new(kind, payload, actor) for kind, payload in batch])
        except (OSError, SQLAlchemyError) as error:
            raise Refused(f"{task}: its History could not be appended to: {error}") from error

    @staticmethod
    def _new(kind: str, payload: dict[str, Any], actor: str) -> NewEvent:
        stored = json.loads(
            json.dumps(payload, default=str)
        )  # a front matter date is a datetime, which JSON cannot hold
        return NewEvent(kind, stored, actor, BREAK_GLASS if _break_glass.get() else WRITER)
