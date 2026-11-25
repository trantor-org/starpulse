"""Compile a YAML machine definition to a `Machine` class.

A machine is declared in YAML and validated against `machine.schema.json`, the
published schema. States carry `initial` or `final`, or a `role` (`resting`, `waiting_on_fact`, `waiting_on_person`) that `role_of` answers by state, so code reads roles and never a deployment's state names; each event lists
transitions from one or more states to one state. A guard is a `when:` field match on the event that fires the
transition (`equals`, `in`, `exists`). Config holds no expressions or code, so a shared definition is never executable.

A machine composes with another through `submachines:`, each naming a state, a sibling machine file's stem and the
events that machine's final states fire; the loader compiles each file on its own.

A state lists no `waits`: the facts the task actor watches, and the event each fires, are rows of the policy DB, and
the loader refuses a file that still declares them.

A top-level `source:` names the third party that moves the machine; StarPulse only observes it, and the snapshot
carries the name so the page can draw it apart from a machine its own actors move.

A transition may carry a `cite:` (the `skill` and the `quote` of its sentence that sends a session down it); the
compiled class keeps it by `(source, event, target)` in `citations`, and the page and `machine show` draw it.

A top-level `writers:` block names, per event, who fires it: each entry is an
`actor` (`agent`, `operator`, or a workflow as `<instance>/<workflow>`) and
the `trigger` it fires through. `refuse_unlisted` refuses a workflow no
configured adapter lists, and the compiler refuses an `agent` writer of an event
into a final state whose trigger is prose rather than a command or tool a
session's transcript shows.

A definition the compiler refuses names its fault: not exactly one initial state, a transition naming an undeclared
state, a state no route from the initial state reaches, a transition out of a final state, a non-final state with no
outgoing transition, or a non-final state with no path to a final state.

The compiled class is a `runner.Machine`, so `machine_engine`'s paths, conformance and guard replay run on it.
"""

import logging
import re
from collections import deque
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starpulse.machine_engine.model.runner import Machine, State, Transition, field_matches, machine_class

_LOG = logging.getLogger(__name__)

__all__ = [
    "Compiled",
    "Cue",
    "MachineDefinitionError",
    "Writer",
    "field_matches",
    "refuse_unlisted",
    "role_of",
    "writers_of",
]

#: The top-level keys that only change how the page draws a machine.
DRAWING = ("type", "parents", "tiers", "main_line", "rests", "submachines", "launches", "next")
#: The fact kinds a lane's watch may name: what the task actor derives from a task's pull request, dependencies and criteria.
WAIT_FACTS = (
    "pr_terminal",
    "pr_merged",
    "pr_closed_unmerged",
    "pr_closed_unmerged_complete",
    "pr_merged_unfinished",
    "pr_ready",
    "pr_failing",
    "pr_draft",
    "pr_conflicting",
    "phase_resumed",
    "operator_pushback",
    "wait_requested",
    "ask_requested",
    "archive_requested",
    "move_requested",
    "pr_unfinished_alive",
    "pr_unfinished_dead",
    "deps_done",
    "deps_done_with_pr",
    "deps_done_started",
    "deps_unresolved",
    "criteria_met",
    "criteria_met_started",
    "owner_stale",
    "overdue",
)
#: Words that open a sentence, never a command: an agent trigger of a final event opening with one is prose no mapper matches.
PROSE_HEADS = frozenset(
    {"a", "an", "the", "each", "every", "any", "its", "their", "this", "that", "after", "before", "when", "once", "on"}
)


class MachineDefinitionError(ValueError):
    """A machine file the schema or the compiler refuses: `file` is the one to blame and `line` where in it, when known."""

    def __init__(self, message: str, file: Path | None = None, line: int | None = None) -> None:
        super().__init__(message)
        self.file = file
        self.line = line


@dataclass(frozen=True)
class Writer:
    """Who fires a machine event: an `actor` and the `trigger` it fires through."""

    actor: str
    trigger: str


@dataclass(frozen=True)
class Cue:
    """A workflow `dag` an `event` cues, `on` the occasion the page names, and how its failure `resolves`:
    `forced` stays pinned until a forced rerun, `next` clears on the DAG's next run. `grace` is the seconds after its
    event a run of `dag` may take to start before the page marks the merge overdue."""

    event: str
    dag: str
    on: str
    resolves: str
    grace: int = 300


def refuse_unlisted(machine: str, writers: Mapping[str, tuple[Writer, ...]], listed: Collection[str]) -> None:
    """Refuse a machine whose writers name a workflow (`<instance>/<workflow>`) that `listed` lacks, by name.

    A `<instance>/*` entry of `listed` stands for an instance whose workflows are read live and may be read short:
    its missing workflows are warned about, not refused.
    """
    named = {w.actor for ws in writers.values() for w in ws if "/" in w.actor}
    missing = sorted(named - set(listed))
    unread = [name for name in missing if f"{name.split('/')[0]}/*" in listed]
    if unread:
        _LOG.warning("%s: writers name workflows the adapter did not list: %s", machine, unread)
    if refused := [name for name in missing if name not in unread]:
        raise MachineDefinitionError(f"{machine}: writers name workflows no configured adapter lists: {refused}")


@dataclass(frozen=True)
class Compiled:
    """A compiled machine, the adapter events that move it (`adapter event -> machine event`) and who fires each event."""

    name: str
    machine: type[Machine]
    bindings: Mapping[str, str]
    writers: Mapping[str, tuple[Writer, ...]]
    cues: tuple[Cue, ...] = ()
    drawing: Mapping[str, Any] = field(default_factory=dict)
    waits: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    roles: Mapping[str, str | None] = field(default_factory=dict)
    labels: Mapping[str, str] = field(default_factory=dict)
    aliases: Mapping[str, str] = field(default_factory=dict)
    """Each retired name a state declares in `aliases`, by the state id it became."""
    priorities: Mapping[str, int] = field(default_factory=dict)
    """Each state's `priority`, zero when it declares none: the higher state wins a task its dependencies split."""


def writers_of(machine: type[Machine]) -> Mapping[str, tuple[Writer, ...]]:
    """The writers a compiled machine declares per event, `{}` for a machine written in Python."""
    return getattr(machine, "writers", {})


def role_of(compiled: Compiled, state: str) -> str | None:
    """The role `state` plays in the machine: `initial` or `final` from its flags, else the `role:` it declares, else `None`.

    Raises `KeyError` for a state the machine lacks."""
    return compiled.roles[state]


def compile_document(document: dict[str, Any], path: Path) -> Compiled:
    """Compile a machine `document` the schema has accepted; `path` names it in errors."""
    states, bindings = _compile(document, path)
    writers = {
        event: tuple(Writer(**writer) for writer in declared) for event, declared in document.get("writers", {}).items()
    }
    if unknown := sorted(writers.keys() - document["events"].keys()):
        raise MachineDefinitionError(f"{path}: writers name events the machine lacks: {unknown}", path)
    if prose := _prose_exits(document, writers):
        raise MachineDefinitionError(
            f"{path}: agent writers of final events must name a command or tool, not prose: {prose}", path
        )
    cues = tuple(Cue(**cue) for cue in document.get("cues", ()))
    if unknown := sorted({cue.event for cue in cues} - document["events"].keys()):
        raise MachineDefinitionError(f"{path}: cues name events the machine lacks: {unknown}", path)
    _check(list(states.values()), path)
    machine = machine_class(document["name"], list(states.values()))
    machine.writers = writers
    machine.citations = _citations(document["events"])
    machine.source = document.get("source")
    roles = {name: _role(state) for name, state in document["states"].items()}
    machine.roles = roles
    labels = {name: state.get("label", name) for name, state in document["states"].items()}
    aliases = {old: name for name, state in document["states"].items() for old in state.get("aliases", ())}
    priorities = {name: state.get("priority", 0) for name, state in document["states"].items()}
    machine.priorities = priorities
    drawing = {key: document[key] for key in DRAWING if key in document}
    return Compiled(
        document["name"],
        machine,
        bindings,
        writers,
        cues,
        drawing,
        roles=roles,
        labels=labels,
        aliases=aliases,
        priorities=priorities,
    )


def _compile(document: dict[str, Any], path: Path) -> tuple[dict[str, State], dict[str, str]]:
    """The states, with their transitions, and the bindings of one machine file."""
    declared = document["states"]
    if sum(bool(state.get("initial")) for state in declared.values()) != 1:
        raise MachineDefinitionError(f"{path}: a machine needs exactly one initial state", path)
    named = [old for state in declared.values() for old in state.get("aliases", ())]
    if len(named) != len(set(named)) or any(
        state.get("initial") and state.get("aliases") for state in declared.values()
    ):
        raise MachineDefinitionError(f"{path}: an alias names one non-initial state, once", path)
    if unknown := {event for event in document.get("bindings", {}).values() if event not in document["events"]}:
        raise MachineDefinitionError(f"{path}: bindings name events the machine lacks: {sorted(unknown)}", path)

    states = {
        name: State(name, initial=bool(state.get("initial")), final=bool(state.get("final")))
        for name, state in declared.items()
    }
    bindings = dict(document.get("bindings", {}))
    for event, transitions in document["events"].items():
        for transition in transitions:
            sources = _sources(transition)
            for name in (*sources, transition["to"]):
                if name not in declared:
                    raise MachineDefinitionError(f"{path}: event {event} names undeclared state {name!r}", path)
            guards = {key: transition[key]["when"] for key in ("if", "unless") if key in transition}
            for source in sources:
                states[source].transitions.append(
                    Transition(states[source], states[transition["to"]], event, guards.get("if"), guards.get("unless"))
                )

    return states, bindings


def _check(states: list[State], path: Path) -> None:
    """Refuse a definition with an unreachable state, a transition out of a final state, a dead end, or no way to finish."""
    initial = next(state for state in states if state.initial)
    reached = {initial}
    queue = deque([initial])
    while queue:
        for transition in queue.popleft().transitions:
            if transition.target not in reached:
                reached.add(transition.target)
                queue.append(transition.target)
    if unreachable := [state.id for state in states if state not in reached]:
        raise MachineDefinitionError(
            f"{path}: unreachable states, no route from the initial state: {unreachable}", path
        )
    if leaving := [state.id for state in states if state.final and state.transitions]:
        raise MachineDefinitionError(f"{path}: transitions leave final states: {leaving}", path)
    if stuck := [state.id for state in states if not state.final and not state.transitions]:
        raise MachineDefinitionError(f"{path}: states with no outgoing transition: {stuck}", path)
    finishing = {state for state in states if state.final}
    while finishing and (
        more := {s for s in states if s not in finishing and any(t.target in finishing for t in s.transitions)}
    ):
        finishing |= more
    if finishing and (unfinished := [state.id for state in states if state not in finishing]):
        raise MachineDefinitionError(f"{path}: states with no path to a final state: {unfinished}", path)


def _citations(events: Mapping[str, Any]) -> dict[tuple[str, str, str], Mapping[str, str]]:
    """Each cited transition's `cite`, by `(source, event, target)`."""
    return {
        (source, event, transition["to"]): transition["cite"]
        for event, transitions in events.items()
        for transition in transitions
        if "cite" in transition
        for source in _sources(transition)
    }


def _prose_exits(document: Mapping[str, Any], writers: Mapping[str, tuple[Writer, ...]]) -> dict[str, list[str]]:
    """Each event into a final state whose `agent` writer's trigger opens with a word of prose, not a command or tool."""
    finals = {name for name, state in document["states"].items() if state.get("final")}
    exits = {event for event, transitions in document["events"].items() if any(t["to"] in finals for t in transitions)}
    prose = {
        event: [w.trigger for w in writers.get(event, ()) if w.actor == "agent" and _is_prose(w.trigger)]
        for event in sorted(exits)
    }
    return {event: triggers for event, triggers in prose.items() if triggers}


def _is_prose(trigger: str) -> bool:
    head = trigger.split(maxsplit=1)[0] if trigger.strip() else ""
    return head.lower() in PROSE_HEADS or not re.fullmatch(r"[\w./-]+", head)


def _sources(transition: Mapping[str, Any]) -> list[str]:
    return [transition["from"]] if isinstance(transition["from"], str) else transition["from"]


def _role(declared: Mapping[str, Any]) -> str | None:
    return "initial" if declared.get("initial") else "final" if declared.get("final") else declared.get("role")
