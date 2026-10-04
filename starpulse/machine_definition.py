"""Compile a YAML machine definition to a python-statemachine class.

A machine is declared in YAML and validated against `machine.schema.json`, the
published schema. States carry `initial` or `final`; each event lists
transitions from one or more states to one state. A guard is either a `when:`
field match on the event that triggers the transition (`equals`, `in`,
`exists`) or the name of a guard an adapter registers in Python through a
`Registry`; a transition may name a registered `action` the same way. Config
holds no expressions or code, so a shared definition is never executable.

A state may open another machine file with `flow:`. The child's states nest
under that state as `<state>_<child state>`, and the child's own states may
not open a further file: one level of subflows.

A top-level `writers:` block names, per event, who fires it: each entry is an
`actor` (`agent`, `operator`, or a workflow as `<instance>/<workflow>`) and
the `trigger` it fires through. `refuse_unlisted` refuses a workflow no
configured adapter lists.

The compiled class is an ordinary `StateChart`, so `backlog_lifecycle`'s paths,
conformance and guard replay run on it unchanged.
"""

import json
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from functools import wraps
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from statemachine import StateChart
from statemachine.exceptions import InvalidDefinition
from statemachine.io import create_machine_class_from_definition

SCHEMA = json.loads(Path(__file__).with_name("machine.schema.json").read_text())
_VALIDATOR = Draft202012Validator(SCHEMA)


class MachineDefinitionError(ValueError):
    """A machine file the schema or the compiler refuses."""


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


def writers_of(machine: type[StateChart]) -> Mapping[str, tuple[Writer, ...]]:
    """The writers a compiled machine declares per event, `{}` for a machine written in Python."""
    return getattr(machine, "writers", {})


def validate(document: Any) -> None:
    """Refuse a document the published schema rejects."""
    if (error := best_match(_VALIDATOR.iter_errors(document))) is not None:
        where = "/".join(str(part) for part in error.absolute_path) or "<root>"
        raise MachineDefinitionError(f"{where}: {error.message}")


def load_machine(path: Path, registry: Registry = Registry()) -> Compiled:
    """Compile the machine file at `path`, opening each state's `flow:` child file."""
    document = _read(path)
    states, bindings = _compile(document, path, registry, prefix="")
    writers = {
        event: tuple(Writer(**writer) for writer in declared) for event, declared in document.get("writers", {}).items()
    }
    if unknown := sorted(writers.keys() - document["events"].keys()):
        raise MachineDefinitionError(f"{path}: writers name events the machine lacks: {unknown}")
    try:
        machine = create_machine_class_from_definition(document["name"], states=states)
    except InvalidDefinition as error:
        raise MachineDefinitionError(f"{path}: {error}") from error
    setattr(machine, "writers", writers)
    return Compiled(document["name"], machine, bindings, writers)


def _read(path: Path) -> dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise MachineDefinitionError(f"{path}: {error}") from error
    try:
        validate(document)
    except MachineDefinitionError as error:
        raise MachineDefinitionError(f"{path}: {error}") from error
    return document


def _compile(
    document: dict[str, Any], path: Path, registry: Registry, *, prefix: str, nested: bool = False
) -> tuple[dict[str, Any], dict[str, str]]:
    """The library's state definitions for one machine file, ids prefixed when it is a child."""
    declared = document["states"]
    if sum(bool(state.get("initial")) for state in declared.values()) != 1:
        raise MachineDefinitionError(f"{path}: a machine needs exactly one initial state")
    if unknown := {event for event in document.get("bindings", {}).values() if event not in document["events"]}:
        raise MachineDefinitionError(f"{path}: bindings name events the machine lacks: {sorted(unknown)}")

    states: dict[str, Any] = {f"{prefix}{name}": _state(state) for name, state in declared.items()}
    bindings = dict(document.get("bindings", {}))
    for event, transitions in document["events"].items():
        for transition in transitions:
            sources = [transition["from"]] if isinstance(transition["from"], str) else transition["from"]
            for name in (*sources, transition["to"]):
                if name not in declared:
                    raise MachineDefinitionError(f"{path}: event {event} names undeclared state {name!r}")
            target = {
                "target": f"{prefix}{transition['to']}",
                **{
                    callback: _guard(transition[key], registry, path)
                    for key, callback in (("if", "cond"), ("unless", "unless"))
                    if key in transition
                },
                **({"on": _named(transition["action"], registry.actions, path)} if "action" in transition else {}),
            }
            for source in sources:
                states[f"{prefix}{source}"].setdefault("on", {}).setdefault(event, []).append(target)

    for name, state in declared.items():
        if "flow" not in state:
            continue
        if nested:
            raise MachineDefinitionError(f"{path}: state {name!r} opens a flow, but subflows go one level only")
        child_path = path.parent / state["flow"]
        children, child_bindings = _compile(
            _read(child_path), child_path, registry, prefix=f"{prefix}{name}_", nested=True
        )
        if clash := bindings.keys() & child_bindings.keys():
            raise MachineDefinitionError(f"{child_path}: bindings already bound by {path}: {sorted(clash)}")
        bindings |= child_bindings
        states[f"{prefix}{name}"]["states"] = children
    return states, bindings


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
        raise MachineDefinitionError(f"{path}: {name!r} is not registered by the adapter")
    return table[name]


def _field_match(when: Mapping[str, Mapping[str, Any]]) -> Callable[..., bool]:
    def matches(**fields: Any) -> bool:
        return all(_holds(match, name in fields, fields.get(name)) for name, match in when.items())

    return matches


def _holds(match: Mapping[str, Any], present: bool, value: Any) -> bool:
    if "exists" in match:
        return present == match["exists"]
    if not present:
        return False
    return value == match["equals"] if "equals" in match else value in match["in"]
