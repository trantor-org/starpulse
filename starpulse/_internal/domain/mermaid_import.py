"""Draft a StarPulse machine definition from a Mermaid `stateDiagram-v2` file.

A diagram carries states, an initial and final marker, and labelled transitions;
it cannot carry event names, guards or actions, so the YAML definition stays the
source of truth and `.mmd` stays generated output (`make diagrams`). The draft
names each event from its transition label (`Deps done` becomes `DEPS_DONE`),
leaves a trailing `[guard]` in the label out, and imports no guard or action:
the author adds those.

Usage:
    python -m starpulse._internal.domain.mermaid_import flow.mmd
    python -m starpulse._internal.domain.mermaid_import flow.mmd --out flow.yaml

An existing file is never overwritten.
"""

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from starpulse._internal.domain.machine_definition import MachineDefinitionError, validate

__all__ = ["Diagram", "Edge", "draft_machine", "dump", "parse"]

_ID = r"[A-Za-z][A-Za-z0-9_]*"
_DECLARATION = re.compile(rf'state\s+"[^"]*"\s+as\s+(?P<id>{_ID})$')
_INITIAL = re.compile(rf"\[\*\]\s*-->\s*(?P<id>{_ID})$")
_FINAL = re.compile(rf"(?P<id>{_ID})\s*-->\s*\[\*\]$")
_TRANSITION = re.compile(rf"(?P<source>{_ID})\s*-->\s*(?P<target>{_ID})(?:\s*:\s*(?P<label>.*))?$")
_GUARD = re.compile(r"\s*\[[^\]]*\]\s*$")
_STATE_ID = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    label: str | None


@dataclass
class Diagram:
    states: list[str] = field(default_factory=list)
    initial: str | None = None
    final: list[str] = field(default_factory=list)
    transitions: list[Edge] = field(default_factory=list)

    def declare(self, name: str, line: str) -> None:
        if not _STATE_ID.fullmatch(name):
            raise MachineDefinitionError(f"{line!r}: state id {name!r} must be lowercase letters, digits and _")
        if name not in self.states:
            self.states.append(name)


def parse(text: str) -> Diagram:
    """The states, markers and transitions of a `stateDiagram-v2` source."""
    lines = [(number, line.strip()) for number, line in enumerate(text.splitlines(), 1)]
    lines = [(number, line) for number, line in lines if line and not line.startswith("%%")]
    if not lines or lines[0][1] not in ("stateDiagram-v2", "stateDiagram"):
        raise MachineDefinitionError("not a stateDiagram-v2 file: its first line must be `stateDiagram-v2`")

    diagram = Diagram()
    for number, line in lines[1:]:
        if line.startswith("direction "):
            continue
        if match := _DECLARATION.fullmatch(line):
            diagram.declare(match["id"], line)
        elif match := _INITIAL.fullmatch(line):
            diagram.declare(match["id"], line)
            if diagram.initial is not None:
                raise MachineDefinitionError(f"line {number}: a machine has one initial state, found a second")
            diagram.initial = match["id"]
        elif match := _FINAL.fullmatch(line):
            diagram.declare(match["id"], line)
            diagram.final.append(match["id"])
        elif match := _TRANSITION.fullmatch(line):
            diagram.declare(match["source"], line)
            diagram.declare(match["target"], line)
            label = _GUARD.sub("", match["label"] or "").strip() or None
            diagram.transitions.append(Edge(match["source"], match["target"], label))
        else:
            raise MachineDefinitionError(f"line {number}: unsupported stateDiagram syntax: {line!r}")
    if diagram.initial is None:
        raise MachineDefinitionError("the diagram has no initial state: add `[*] --> <state>`")
    return diagram


def draft_machine(name: str, diagram: Diagram) -> dict[str, Any]:
    """A machine document for `diagram`: no guards, no actions, one event per distinct label."""
    events: dict[str, list[dict[str, str]]] = {}
    for edge in diagram.transitions:
        events.setdefault(_event_name(edge), []).append({"from": edge.source, "to": edge.target})
    return {
        "name": name,
        "states": {
            state: {"initial": True} if state == diagram.initial else {"final": True} if state in diagram.final else {}
            for state in diagram.states
        },
        "events": events,
    }


def _event_name(edge: Edge) -> str:
    name = re.sub(r"[^A-Za-z0-9]+", "_", edge.label or f"{edge.source}_to_{edge.target}").strip("_").upper()
    if not name[:1].isalpha():
        raise MachineDefinitionError(f"cannot name an event from the label {edge.label!r}: it must start with a letter")
    return name


def dump(draft: dict[str, Any], source: str = "") -> str:
    """The draft as YAML, headed by a note that its guards and actions are still to write."""
    header = f"# Draft imported from {source}: add guards and actions by hand.\n" if source else ""
    return header + yaml.safe_dump(draft, sort_keys=False)  # pragma: no mutate: `None` and `False` both keep key order


def import_file(source: Path, out: Path | None = None) -> Path:
    """Write the draft machine of the diagram in `source` to `out` (default under `.starpulse/machines`) and return
    where it went; an existing file is never overwritten."""
    out = out or Path(".starpulse/machines") / f"{source.stem}.yaml"
    draft = draft_machine(source.stem, parse(source.read_text()))
    validate(draft)
    with out.open("x") as handle:
        handle.write(dump(draft, source.name))
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Draft a StarPulse machine definition from a stateDiagram-v2 file.")
    parser.add_argument("source", type=Path, help="a stateDiagram-v2 .mmd file")
    parser.add_argument("--out", type=Path, help="default: .starpulse/machines/<source name>.yaml")
    args = parser.parse_args(argv)
    try:
        out = import_file(args.source, args.out)
    except (MachineDefinitionError, OSError) as error:
        parser.error(f"{args.source}: {error}")
    print(f"Wrote {out}")

