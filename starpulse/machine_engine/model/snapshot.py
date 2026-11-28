"""The static shape StarPulse draws: a lifecycle machine as the page reads it.

A machine's tasks come from `machine_tasks` (the `machine:events` stream) and the Board's from the configured
board adapter (`starpulse.board.model.seam`); this module holds the shape of each machine.
"""

import dataclasses
from collections.abc import Sequence
from typing import Any

lazy from starpulse.machine_engine.model.machine_definition import writers_of

__all__ = ["describe", "is_workflow", "writers"]


def _titled(name: str) -> str:
    """A state's name with every word capitalised (`In Progress`); a state's own `name` capitalises only the first."""
    return " ".join(word[:1].upper() + word[1:] for word in name.split(" "))


def describe(machine: Any, rests: Sequence[str] = ()) -> dict:
    """The machine's states and transitions, self-loops included, its `source` when a third party moves it, and its
    YAML-declared writers. A transition its YAML cites carries the `cite`. A state in `rests` is where the lifecycle
    ends though an event leaves it, so it is served as the `final` type.

    A writer is a workflow when its actor is named `<instance>/<workflow>`; a machine that declares none carries no
    `writers`.
    """
    cited = getattr(machine, "citations", {})
    roles = {state: "final" if state in rests else role for state, role in getattr(machine, "roles", {}).items()}
    priorities = getattr(machine, "priorities", {})
    body: dict[str, Any] = {
        "states": [
            {
                "id": s.id,
                "name": _titled(s.name),
                "initial": s.initial,
                "final": s.final,
                "role": roles.get(s.id),
                "priority": priorities.get(s.id, 0),
            }
            for s in machine.states
        ],
        "transitions": [
            {"source": t.source.id, "target": t.target.id, "event": str(t.event)}
            | ({"cite": dict(cite)} if (cite := cited.get((t.source.id, str(t.event), t.target.id))) else {})
            for s in machine.states
            for t in s.transitions
        ],
    }
    if source := getattr(machine, "source", None):
        body["source"] = source
    if declared_writers := {event: ws for event, ws in writers(machine).items() if ws}:
        body["writers"] = declared_writers
    return body


def writers(machine: Any) -> dict[str, list[dict]]:
    """Every writer the machine's YAML declares, by event, as the page draws it."""

    return {event: [dataclasses.asdict(w) for w in ws] for event, ws in writers_of(machine).items()}


def is_workflow(actor: str) -> bool:
    """A writer's actor is a workflow when it is named `<instance>/<workflow>`, not a bare `agent` or `operator`."""
    return "/" in actor

