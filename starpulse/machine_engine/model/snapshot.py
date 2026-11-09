"""The static shape StarPulse draws: a lifecycle machine as the page reads it, and the workflow declarations.

A machine's tasks come from `machine_tasks` (the `machine:events` stream) and the Board's from the configured
board adapter (`starpulse.board.model.seam`); this module holds the shape of each machine.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

__all__ = ["Qualify", "describe", "is_workflow", "qualifier", "writers"]

#: Names a workflow as the page draws it. A machine or cue names its workflows by their own name; the page draws
#: them as `<instance>/<workflow>`, so what a machine says is read through one of these.
Qualify = Callable[[str], str]


def qualifier(domains: Mapping[str, Sequence[str]]) -> Qualify:
    """A workflow's own name as `<instance>/<workflow>`, when exactly one configured instance lists it.

    `domains` is the config's qualified domains. A name two instances list names neither of them, and a name
    no instance lists (`operator`, `agent`) is not a workflow, so both stay as they are.
    """
    owners: dict[str, set[str]] = {}
    for qualified in (name for names in domains.values() for name in names):
        owners.setdefault(qualified.partition("/")[2], set()).add(qualified)
    unique = {own: next(iter(names)) for own, names in owners.items() if len(names) == 1}
    return lambda name: unique.get(name, name)


def _titled(name: str) -> str:
    """A state's name with every word capitalised (`In Progress`); python-statemachine capitalises only the first."""
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
    body: dict[str, Any] = {
        "states": [
            {"id": s.id, "name": _titled(s.name), "initial": s.initial, "final": s.final, "role": roles.get(s.id)}
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
    from starpulse.machine_engine.model.machine_definition import (  # noqa: PLC0415 - import cost, paid on first use
        writers_of,
    )

    return {event: [dataclasses.asdict(w) for w in ws] for event, ws in writers_of(machine).items()}


def is_workflow(actor: str) -> bool:
    """A writer's actor is a workflow when it is named `<instance>/<workflow>`, not a bare `agent` or `operator`."""
    return "/" in actor


def declared(
    domains: Mapping[str, Sequence[str]] | None = None,
    run_safe: Collection[str] = (),
    cues: Sequence[dict] = (),
    processes: Mapping[str, Sequence[tuple[str, Sequence[str]]]] | None = None,
) -> dict:
    """The workflow relationships the page draws: the board adapter's cues, and the config's domains with each
    workflow flagged when `run_safe` holds it.

    `domains` and `run_safe` name workflows as `<instance>/<workflow>`, and so does each cue's `dag`.
    """
    procs = processes or {}

    def dags_of(names: Sequence[str]) -> list[dict]:
        return [{"name": dag, "runSafe": dag in run_safe} for dag in names]

    return {
        "cues": list(cues),
        "domains": [
            {
                "name": name,
                "dags": dags_of(dags),
                "processes": [{"name": pname, "dags": dags_of(p_dags)} for pname, p_dags in procs.get(name, ())],
            }
            for name, dags in (domains or {}).items()
        ],
    }
