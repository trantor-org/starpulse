"""What a forwarded stream entry may carry out of an instance: the fields each stream names and which of them name a person."""

from __future__ import annotations

from typing import Any

from starpulse.adapters.runs import run_events
from starpulse.store import events, lane_events

__all__ = ["FIELDS", "PERSON", "project"]

#: The fields each forwarded stream may carry, and the ones among them that name a person.
FIELDS: dict[str, tuple[str, ...]] = {
    events.STREAM: ("machine", "event", "task", "run", "actor", "assignee", "time"),
    run_events.STREAM: ("time", "phase", "workflow", "run_id", "status", "step", "depends"),
    lane_events.STREAM: lane_events.FIELDS,
}
PERSON = ("actor", "assignee")


def project(stream: str, fields: dict[str, Any], *, opt_in: bool) -> dict[str, Any]:
    """The part of one `stream` entry's `fields` that may leave the IC; a person's name stays unless `opt_in`."""
    return {k: fields[k] for k in FIELDS[stream] if k in fields and (opt_in or k not in PERSON)}
