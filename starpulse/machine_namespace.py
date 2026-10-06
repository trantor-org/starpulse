"""Machines are namespaced `<repo>/<machine>`; two merge only when their compiled definitions hash equal.

A definition reduces to a set of facts: one per state flag, per transition (one for each source state, with its
guards and action), per binding and per writer, a `flow:` child's facts under the state that opens it. The hash is
over the sorted facts, so the order of keys, states, events and `from` lists never moves it, and the difference of
two fact sets is the transition diff a drift record carries.
"""

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starpulse.machine_definition import MachineDefinitionError, _read

__all__ = ["Definition", "Drift", "Merged", "Source", "definition", "merge"]


@dataclass(frozen=True)
class Definition:
    """A compiled machine reduced to its facts and the sha256 of them."""

    name: str
    digest: str
    facts: frozenset[str]


def definition(path: Path) -> Definition:
    """The definition of the machine file at `path`, opening each state's `flow:` child file."""
    document = _read(path)
    facts = _facts(document, path, prefix="")
    facts |= {f"binding {adapter} -> {event}" for adapter, event in document.get("bindings", {}).items()}
    for event, writers in document.get("writers", {}).items():
        facts |= {f"writer {event} {writer['actor']} via {writer['trigger']}" for writer in writers}
    digest = hashlib.sha256("\n".join(sorted(facts)).encode()).hexdigest()
    return Definition(document["name"], digest, frozenset(facts))


def _facts(document: Mapping[str, Any], path: Path, *, prefix: str, nested: bool = False) -> set[str]:
    facts: set[str] = set()
    for name, state in document["states"].items():
        facts |= {f"state {prefix}{name} {flag}" for flag in ("initial", "final") if state.get(flag)}
        facts.add(f"state {prefix}{name}")
        if "flow" in state:
            if nested:
                raise MachineDefinitionError(
                    f"{path}: state {name!r} opens a flow, but subflows go one level only", path
                )
            child = path.parent / state["flow"]
            facts |= _facts(_read(child), child, prefix=f"{prefix}{name}_", nested=True)
    for event, transitions in document["events"].items():
        for transition in transitions:
            sources = [transition["from"]] if isinstance(transition["from"], str) else transition["from"]
            guards = "".join(
                f" {key} {_spec(transition[key])}" for key in ("if", "unless", "action") if key in transition
            )
            facts |= {f"{event}: {prefix}{source} -> {prefix}{transition['to']}{guards}" for source in sources}
    return facts


def _spec(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class Source:
    """One repository's declaration of a machine: `repo` is whatever names the repository, `owner/name` included."""

    repo: str
    definition: Definition

    @property
    def id(self) -> str:
        """The machine's namespaced id, `<repo>/<machine>`; a machine name holds no `/`, so the last one splits it."""
        return f"{self.repo}/{self.definition.name}"


@dataclass(frozen=True)
class Drift:
    """A source whose definition differs from the merged one: both digests and the facts that differ."""

    source: str
    digest: str
    merged_digest: str
    added: tuple[str, ...]
    removed: tuple[str, ...]


@dataclass(frozen=True)
class Merged:
    """One machine's merged graph: the sources whose definition hashes to `digest`, and the sources left out."""

    machine: str
    digest: str
    members: tuple[str, ...]
    drift: tuple[Drift, ...]


def merge(sources: Iterable[Source]) -> dict[str, Merged]:
    """Group sources by machine name and merge those whose digest equals the one most repositories hold.

    A tie goes to the smaller digest, so the answer never depends on the order the sources arrive in. Every other
    source is recorded as drift and stays out of `members`. A repository declaring one machine twice is refused."""
    by_machine: dict[str, dict[str, Source]] = {}
    for source in sources:
        declared = by_machine.setdefault(source.definition.name, {})
        if source.id in declared:
            raise ValueError(f"{source.id} is declared twice")
        declared[source.id] = source
    return {machine: _merged(machine, declared) for machine, declared in sorted(by_machine.items())}


def _merged(machine: str, declared: Mapping[str, Source]) -> Merged:
    held = Counter(source.definition.digest for source in declared.values())
    digest = min(held, key=lambda candidate: (-held[candidate], candidate))
    baseline = next(source.definition for source in declared.values() if source.definition.digest == digest)
    members = tuple(sorted(id for id, source in declared.items() if source.definition.digest == digest))
    drift = tuple(
        Drift(
            id,
            source.definition.digest,
            digest,
            tuple(sorted(source.definition.facts - baseline.facts)),
            tuple(sorted(baseline.facts - source.definition.facts)),
        )
        for id, source in sorted(declared.items())
        if source.definition.digest != digest
    )
    return Merged(machine, digest, members, drift)
