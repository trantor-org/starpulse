"""Compile a YAML machine definition to a python-statemachine class.

A machine is declared in YAML and validated against `machine.schema.json`, the
published schema. States carry `initial` or `final`, or a `role` (`resting`, `waiting_on_fact`, `waiting_on_person`) that `role_of` answers by state, so code reads roles and never a deployment's state names; each event lists
transitions from one or more states to one state. A guard is either a `when:`
field match on the event that fires the transition (`equals`, `in`,
`exists`) or the name of a guard an adapter registers in Python through a
`Registry`; a transition may name a registered `action` the same way. Config
holds no expressions or code, so a shared definition is never executable.

A machine composes with another through `submachines:`, each naming a state, a sibling machine file's stem and the
events that machine's final states fire; the loader compiles each file on its own.

A state may list `waits`: a fact kind mapped to the event that leaves the state when the fact holds. The loader
refuses an unknown fact kind and an event that is not a transition out of the state; it fires nothing.

A top-level `source:` names the third party that moves the machine; StarPulse only observes it, and the snapshot
carries the name so the page can draw it apart from a machine its own actors move.

A transition may carry a `cite:` (the `skill` and the `quote` of its sentence that sends a session down it); the
compiled class keeps it by `(source, event, target)` in `citations`, and the page and `machine show` draw it.

A top-level `writers:` block names, per event, who fires it: each entry is an
`actor` (`agent`, `operator`, or a workflow as `<instance>/<workflow>`) and
the `trigger` it fires through. `refuse_unlisted` refuses a workflow no
configured adapter lists.

The compiled class is an ordinary `StateChart`, so `board_client`'s paths,
conformance and guard replay run on it unchanged.
"""

import json
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError, best_match
from statemachine import StateChart
from statemachine.exceptions import InvalidDefinition
from statemachine.io import create_machine_class_from_definition

__all__ = [
    "Compiled",
    "Cue",
    "MachineDefinitionError",
    "Registry",
    "Writer",
    "field_matches",
    "load_machine",
    "opened_by",
    "refuse_unlisted",
    "role_of",
    "validate",
    "writers_of",
]

#: The top-level keys that only change how the page draws a machine.
DRAWING = ("tiers", "main_line", "rests", "submachines", "launches")
#: The fact kinds a state's `waits` may name: what the task actor derives from a task's pull request, dependencies and criteria.
WAIT_FACTS = ("pr_terminal", "deps_done", "deps_unresolved", "criteria_met", "criteria_unmet")
SCHEMA = json.loads((Path(__file__).parents[2] / "machine.schema.json").read_text())
_VALIDATOR = Draft202012Validator(SCHEMA)


class MachineDefinitionError(ValueError):
    """A machine file the schema or the compiler refuses: `file` is the one to blame and `line` where in it, when known."""

    def __init__(self, message: str, file: Path | None = None, line: int | None = None) -> None:
        super().__init__(message)
        self.file = file
        self.line = line


@dataclass(frozen=True)
class Registry:
    """The Python an adapter supplies for the names a definition uses: guards return a bool, actions act on the model."""

    guards: Mapping[str, Callable[..., bool]] = field(default_factory=dict)
    actions: Mapping[str, Callable[..., None]] = field(default_factory=dict)


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
    """Refuse a machine whose writers name a workflow (`<instance>/<workflow>`) that `listed` lacks, by name."""
    if missing := sorted({w.actor for ws in writers.values() for w in ws if "/" in w.actor} - set(listed)):
        raise MachineDefinitionError(f"{machine}: writers name workflows no configured adapter lists: {missing}")


@dataclass(frozen=True)
class Compiled:
    """A compiled machine, the adapter events that move it (`adapter event -> machine event`) and who fires each event."""

    name: str
    machine: type[StateChart]
    bindings: Mapping[str, str]
    writers: Mapping[str, tuple[Writer, ...]]
    cues: tuple[Cue, ...] = ()
    drawing: Mapping[str, Any] = field(default_factory=dict)
    waits: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    roles: Mapping[str, str | None] = field(default_factory=dict)


def writers_of(machine: type[StateChart]) -> Mapping[str, tuple[Writer, ...]]:
    """The writers a compiled machine declares per event, `{}` for a machine written in Python."""
    return getattr(machine, "writers", {})


def role_of(compiled: Compiled, state: str) -> str | None:
    """The role `state` plays in the machine: `initial` or `final` from its flags, else the `role:` it declares, else `None`.

    Raises `KeyError` for a state the machine lacks."""
    return compiled.roles[state]


def _schema_error(document: Any) -> ValidationError | None:
    return best_match(_VALIDATOR.iter_errors(document))


def _describe(error: ValidationError) -> str:
    where = "/".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{where}: {error.message}"


def validate(document: Any) -> None:
    """Refuse a document the published schema rejects."""
    if (error := _schema_error(document)) is not None:
        raise MachineDefinitionError(_describe(error))


def _line_of(text: str, parts: Iterable[str | int]) -> int:
    """The 1-based line of the YAML value at `parts`, or of the deepest enclosing node that exists."""
    node = yaml.compose(text)
    for part in parts:
        if isinstance(node, yaml.MappingNode):
            child = next((value for key, value in node.value if key.value == part), None)
        elif isinstance(node, yaml.SequenceNode) and isinstance(part, int):
            child = node.value[part]
        else:
            child = None
        if child is None:
            break
        node = child
    return node.start_mark.line + 1


def load_machine(path: Path, registry: Registry = Registry()) -> Compiled:
    """Compile the machine file at `path`."""
    return compile_document(_read(path), path, registry)


def compile_document(document: dict[str, Any], path: Path, registry: Registry = Registry()) -> Compiled:
    """Compile a machine `document` the schema has accepted; `path` names it in errors."""
    states, bindings, waits = _compile(document, path, registry)
    writers = {
        event: tuple(Writer(**writer) for writer in declared) for event, declared in document.get("writers", {}).items()
    }
    if unknown := sorted(writers.keys() - document["events"].keys()):
        raise MachineDefinitionError(f"{path}: writers name events the machine lacks: {unknown}", path)
    cues = tuple(Cue(**cue) for cue in document.get("cues", ()))
    if unknown := sorted({cue.event for cue in cues} - document["events"].keys()):
        raise MachineDefinitionError(f"{path}: cues name events the machine lacks: {unknown}", path)
    try:
        machine = create_machine_class_from_definition(document["name"], states=states)
    except InvalidDefinition as error:
        raise MachineDefinitionError(f"{path}: {error}", path) from error
    setattr(machine, "writers", writers)
    setattr(machine, "citations", _citations(document["events"]))
    setattr(machine, "source", document.get("source"))
    drawing = {key: document[key] for key in DRAWING if key in document}
    roles = {name: _role(state) for name, state in document["states"].items()}
    return Compiled(document["name"], machine, bindings, writers, cues, drawing, waits, roles)


def _read(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text()
        document = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as error:
        mark = getattr(error, "problem_mark", None)
        raise MachineDefinitionError(f"{path}: {error}", path, mark.line + 1 if mark else None) from error
    _spell_on(document)
    if isinstance(document, dict) and "subflows" in document:
        raise MachineDefinitionError(
            f"{path}: `subflows:` is now `submachines:`; rename the key", path, _line_of(text, ["subflows"])
        )
    if (error := _schema_error(document)) is not None:
        raise MachineDefinitionError(f"{path}: {_describe(error)}", path, _line_of(text, error.absolute_path))
    return document


def _spell_on(document: Any) -> None:
    """Read a cue's bare `on:` key as the word it is: YAML 1.1 loads it as the boolean `True`."""
    cues = document.get("cues") if isinstance(document, dict) else None
    for cue in cues if isinstance(cues, list) else ():
        if isinstance(cue, dict) and True in cue:
            cue["on"] = cue.pop(True)


def _compile(
    document: dict[str, Any], path: Path, registry: Registry
) -> tuple[dict[str, Any], dict[str, str], dict[str, dict[str, str]]]:
    """The library's state definitions, bindings and waits for one machine file."""
    declared = document["states"]
    if sum(bool(state.get("initial")) for state in declared.values()) != 1:
        raise MachineDefinitionError(f"{path}: a machine needs exactly one initial state", path)
    if unknown := {event for event in document.get("bindings", {}).values() if event not in document["events"]}:
        raise MachineDefinitionError(f"{path}: bindings name events the machine lacks: {sorted(unknown)}", path)

    states: dict[str, Any] = {name: _state(state) for name, state in declared.items()}
    bindings = dict(document.get("bindings", {}))
    for event, transitions in document["events"].items():
        for transition in transitions:
            sources = _sources(transition)
            for name in (*sources, transition["to"]):
                if name not in declared:
                    raise MachineDefinitionError(f"{path}: event {event} names undeclared state {name!r}", path)
            target = {
                "target": transition["to"],
                **{
                    callback: _guard(transition[key], registry, path)
                    for key, callback in (("if", "cond"), ("unless", "unless"))
                    if key in transition
                },
                **({"on": _named(transition["action"], registry.actions, path)} if "action" in transition else {}),
            }
            for source in sources:
                states[source].setdefault("on", {}).setdefault(event, []).append(target)

    waits = _waits(declared, document["events"], path)
    return states, bindings, waits


def _citations(events: Mapping[str, Any]) -> dict[tuple[str, str, str], Mapping[str, str]]:
    """Each cited transition's `cite`, by `(source, event, target)`."""
    return {
        (source, event, transition["to"]): transition["cite"]
        for event, transitions in events.items()
        for transition in transitions
        if "cite" in transition
        for source in _sources(transition)
    }


def _sources(transition: Mapping[str, Any]) -> list[str]:
    return [transition["from"]] if isinstance(transition["from"], str) else transition["from"]


def _waits(declared: Mapping[str, Any], events: Mapping[str, Any], path: Path) -> dict[str, dict[str, str]]:
    """Each state's `waits` by id, refusing an unknown fact kind and an event that does not leave the state."""
    waits: dict[str, dict[str, str]] = {}
    for name, state in declared.items():
        for fact, event in state.get("waits", {}).items():
            if fact not in WAIT_FACTS:
                raise MachineDefinitionError(
                    f"{path}: state {name!r} waits on unknown fact {fact!r} for event {event}; known: {list(WAIT_FACTS)}",
                    path,
                )
            if not any(name in _sources(transition) for transition in events.get(event, ())):
                raise MachineDefinitionError(
                    f"{path}: state {name!r} waits on {fact!r} for event {event}, which is not a transition out of it",
                    path,
                )
        if "waits" in state:
            waits[name] = dict(state["waits"])
    return waits


def _role(declared: Mapping[str, Any]) -> str | None:
    return "initial" if declared.get("initial") else "final" if declared.get("final") else declared.get("role")


def _state(declared: Mapping[str, Any]) -> dict[str, Any]:
    return {key: declared[key] for key in ("initial", "final") if key in declared}


def _guard(spec: Any, registry: Registry, path: Path) -> Callable[..., bool]:
    """The Python behind a guard: a registered name, or a field match built from a `when:`."""
    if isinstance(spec, str):
        return _labelled(spec, _named(spec, registry.guards, path))
    return _field_match(spec["when"])


def _labelled(name: str, guard: Callable[..., bool]) -> Callable[..., bool]:
    """The guard under its registered name, which the library labels it by in place of a lambda's `<lambda>`.

    `wraps` keeps the guard's signature, so the library injects the same arguments into it."""

    @wraps(guard)
    def labelled(*args: Any, **kwargs: Any) -> bool:
        return guard(*args, **kwargs)

    labelled.__name__ = labelled.__qualname__ = name
    return labelled


def _named[F: Callable[..., Any]](name: str, table: Mapping[str, F], path: Path) -> F:
    if name not in table:
        raise MachineDefinitionError(f"{path}: {name!r} is not registered by the adapter", path)
    return table[name]


def field_matches(when: Mapping[str, Mapping[str, Any]], fields: Mapping[str, Any]) -> bool:
    """Whether every field `when` lists matches `fields`: the grammar a guard's `when:` uses."""
    return all(_holds(match, name in fields, fields.get(name)) for name, match in when.items())


def _field_match(when: Mapping[str, Mapping[str, Any]]) -> Callable[..., bool]:
    """A matcher named for the fields it reads, which the library labels the guard by: `{ready: {equals: true}}`
    reads `ready`, any other match `kind == push`, `branch in [main, dev]`, `sha exists` or `sha missing`."""

    def matches(**fields: Any) -> bool:
        return field_matches(when, fields)

    matches.__name__ = matches.__qualname__ = " and ".join(_label(name, match) for name, match in when.items())
    return matches


def _label(name: str, match: Mapping[str, Any]) -> str:
    if "exists" in match:
        return f"{name} {'exists' if match['exists'] else 'missing'}"
    if "equals" in match:
        return name if match["equals"] is True else f"{name} == {match['equals']}"
    return f"{name} in [{', '.join(map(str, match['in']))}]"


def _holds(match: Mapping[str, Any], present: bool, value: Any) -> bool:
    if "exists" in match:
        return present == match["exists"]
    if not present:
        return False
    return value == match["equals"] if "equals" in match else value in match["in"]
