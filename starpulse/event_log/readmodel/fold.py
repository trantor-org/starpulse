"""How a Task's Events fold into its read-model row.

The row's keys are the read model's columns: StarPulse's own Task fields, the `fields` a deployment declares, a flat
`meta` map, the claim, the archive marker and the Criteria. `version` is the stream version folded last."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from typing import Any

from starpulse.event_log.store import StoredEvent

Row = dict[str, Any]

TEXT_FIELDS = ("title", "type", "state", "priority", "milestone", "description", "plan", "notes", "final_summary")
LIST_FIELDS = ("labels", "dependencies", "references", "documentation", "modified_files")
OWN_FIELDS = TEXT_FIELDS + LIST_FIELDS


class UnknownEvent(ValueError):
    """A Task stream holds an Event type the fold has no rule for."""


class BrokenHistory(ValueError):
    """An Event names something the History before it never made."""


def _blank(event: StoredEvent) -> Row:
    row: Row = {"id": event.subject_id, "version": 0, "created_at": event.at, "updated_at": event.at}
    row |= dict.fromkeys(TEXT_FIELDS, "")
    row |= {name: [] for name in LIST_FIELDS}
    return row | {
        "assignee": "",
        "released": None,
        "archived": False,
        "fields": {},
        "meta": {},
        "criteria": [],
        "comments": [],
    }


def _set(row: Row, values: dict[str, Any]) -> None:
    for name, value in values.items():
        if name in OWN_FIELDS:
            row[name] = list(value) if name in LIST_FIELDS else str(value)
        elif name in ("assignee", "archived", "fields", "meta", "criteria", "comments"):
            row[name] = copy.deepcopy(value)
        else:
            raise BrokenHistory(f"{row['id']}: {name!r} is not a Task field")


def _merge(target: dict[str, Any], changes: dict[str, Any]) -> None:
    for key, value in changes.items():
        if value is None:
            target.pop(key, None)
        else:
            target[key] = value


def _created(row: Row, event: StoredEvent) -> None:
    _set(row, dict(event.payload))


def _edited(row: Row, event: StoredEvent) -> None:
    payload = event.payload
    _set(row, dict(payload.get("changes", {})))
    _merge(row["fields"], payload.get("fields", {}))
    _merge(row["meta"], payload.get("meta", {}))


def _criterion_added(row: Row, event: StoredEvent) -> None:
    kind = event.payload["kind"]
    number = 1 + sum(1 for criterion in row["criteria"] if criterion["kind"] == kind)
    row["criteria"].append({"kind": kind, "n": number, "text": event.payload["text"], "checked": False, "evidence": ""})
    row["criteria"].sort(key=lambda criterion: (criterion["kind"], criterion["n"]))


def _criterion_checked(row: Row, event: StoredEvent) -> None:
    payload = event.payload
    for criterion in row["criteria"]:
        if (criterion["kind"], criterion["n"]) == (payload["kind"], payload["n"]):
            criterion |= {"checked": payload["checked"], "evidence": payload.get("evidence", "")}
            return
    raise BrokenHistory(f"{row['id']}: no {payload['kind']} criterion {payload['n']}")


def _remapped(row: Row, event: StoredEvent) -> None:
    row["state"] = event.payload["mapping"].get(row["state"], row["state"])


def _comment(row: Row, event: StoredEvent) -> None:
    row["comments"].append({"at": event.at, "actor": event.actor, "text": event.payload["text"]})


def _claimed(row: Row, event: StoredEvent) -> None:
    row.update(assignee=event.payload["assignee"], released=None)


def _released(row: Row, event: StoredEvent) -> None:
    payload = event.payload
    row["assignee"] = ""
    row["released"] = None
    if "ttl" in payload:
        row["released"] = {
            "at": event.at,
            "session": payload["session"],
            "last_renewal": payload["last_renewal"],
            "ttl": payload["ttl"],
        }


def _nothing(row: Row, event: StoredEvent) -> None:
    """An Event that records an attempt and changes no column."""


_RULES: dict[str, Callable[[Row, StoredEvent], None]] = {
    "TaskCreated": _created,
    "TaskImported": _created,
    "FieldsEdited": _edited,
    "CriterionAdded": _criterion_added,
    "CriterionChecked": _criterion_checked,
    "CommentAdded": _comment,
    "Claimed": _claimed,
    "Released": _released,
    "ClaimRefused": _nothing,
    "Transitioned": lambda row, event: row.update(state=event.payload["to"]),
    "Remapped": _remapped,
    "Archived": lambda row, event: row.update(archived=True),
    "Rehydrated": lambda row, event: row.update(archived=False),
}


def _apply(row: Row | None, event: StoredEvent) -> Row:
    rule = _RULES.get(event.type)
    if rule is None:
        raise UnknownEvent(f"{event.subject_id}: no fold rule for {event.type}")
    row = _blank(event) if row is None else row
    rule(row, event)
    row |= {"version": event.version, "updated_at": event.at}
    return row


def fold(row: Row | None, event: StoredEvent) -> Row:
    """`row` after `event`, as a new row; `row` is None before a Task's first Event."""
    return _apply(copy.deepcopy(row), event)


def replay(events: Iterable[StoredEvent]) -> Row:
    """The row a Task's whole History folds into; empty for no Events."""
    row: Row | None = None
    for event in events:
        row = _apply(row, event)
    return row or {}
