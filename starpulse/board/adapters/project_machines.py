"""The machines a project declares under `.starpulse/machines/`, drawn as the page reads them.

The Board's own file is the one `[board] machine` names. Every other file there is a machine of its own, named by its file
stem. A file may also declare how the page draws it (`tiers`,
`main_line`, `rests`) and what opens under it or is launched from it (`submachines`, `launches`); the Board's writers and
the workflows among them are drawn beside those.
"""

from collections.abc import Collection, Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from starpulse.machine_engine.model.machine_definition import Compiled
    from starpulse.machine_engine.model.workflow_names import Qualify
lazy from starpulse.machine_engine.adapters.machine_loader import load_machine
lazy from starpulse.machine_engine.model.snapshot import describe, is_workflow, writers

__all__ = ["DIRECTORY", "draw", "load"]

DIRECTORY = Path(".starpulse") / "machines"


def load(base: Path, board_file: Path | None) -> dict[str, Compiled]:
    """Each machine file under `base`'s machines directory except the Board's, compiled, by file stem."""

    board = board_file.resolve() if board_file else None
    files = [path for path in sorted((base / DIRECTORY).glob("*.yaml")) if path.resolve() != board]
    return {path.stem: load_machine(path) for path in files}


def draw(flows: Mapping[str, Compiled], qualify: Qualify, workflows: Collection[str]) -> dict[str, dict]:
    """Each machine of `flows` as the page draws it: its states and transitions, then what it declares to draw.

    `qualify` names the launching workflows as the page does. With `workflows` listed, a machine whose writers name
    another is refused by that name.
    """
    from starpulse.machine_engine.model.machine_definition import refuse_unlisted

    if workflows:
        for name, compiled in flows.items():
            refuse_unlisted(name, compiled.writers, workflows)
    drawn = {name: describe(compiled.machine, compiled.drawing.get("rests", ())) for name, compiled in flows.items()}
    for name, compiled in flows.items():
        body, declared = drawn[name], compiled.drawing
        states = {state["id"] for state in body["states"]}
        tiered = [state for tier in declared.get("tiers", ()) for state in tier]
        for key, named in (
            ("tiers", tiered),
            ("main_line", declared.get("main_line", ())),
            ("rests", declared.get("rests", ())),
        ):
            _known(name, key, states, named)
        if "tiers" in declared:
            body["tiers"] = [list(tier) for tier in declared["tiers"]]
        if "main_line" in declared:
            body["mainLine"] = list(declared["main_line"])
        if "rests" in declared:
            body["states"] = [{**s, "final": s["final"] or s["id"] in declared["rests"]} for s in body["states"]]
        if "submachines" in declared:
            events = {t["event"] for t in body["transitions"]}
            body["submachines"] = [_link(name, link, states, events, drawn) for link in declared["submachines"]]
        if "launches" in declared:
            body["launches"] = {
                qualify(dag): {"skill": launch["skill"], "machine": _machine(name, launch.get("machine"), drawn)}
                for dag, launch in declared["launches"].items()
            }
        body["next"] = declared.get("next")
        for key in ("type", "parents"):
            if key in declared:
                body[key] = declared[key]
        if name == "board":
            every = writers(compiled.machine)
            body["writers"] = every
            body["dagActors"] = sorted({w["actor"] for ws in every.values() for w in ws if is_workflow(w["actor"])})
    _agree(flows, drawn)
    return drawn


def _agree(flows: Mapping[str, Compiled], drawn: Mapping[str, dict]) -> None:
    """Refuse a machine whose declared `parents` differ from the machines whose `submachines` name it."""
    for name, compiled in flows.items():
        linked = sorted(parent for parent, body in drawn.items() if any(l["machine"] == name for l in body.get("submachines", ())))
        declared = sorted(compiled.drawing.get("parents", ()))
        if declared != linked:
            raise ValueError(f"{name}: parents {declared} disagree with the machines whose submachines name it {linked}")


def _known(name: str, key: str, states: set[str], named: Iterable[str]) -> None:
    if unknown := sorted(set(named) - states):
        raise ValueError(f"{name}: {key} names states the machine lacks: {unknown}")


def _machine(name: str, machine: str | None, drawn: Mapping[str, dict]) -> str | None:
    if machine is not None and machine not in drawn:
        raise ValueError(f"{name}: names the machine {machine!r}, which no machine file under {DIRECTORY} is")
    return machine


def _link(name: str, link: Mapping[str, Any], states: set[str], events: set[str], drawn: Mapping[str, dict]) -> dict:
    """A submachine link as the page draws it, refused unless its state, its inner machine, the inner final states it
    exits from and the events it fires all exist."""
    _known(name, "submachines", states, [link["state"]])
    machine = _machine(name, link["machine"], drawn)
    inner = {state["id"] for state in drawn[machine]["states"]}
    _known(f"{name} -> {machine}", "submachine exits", inner, link["exits"])
    if unknown := sorted(set(link["exits"].values()) - events):
        raise ValueError(f"{name}: submachine exits fire events the machine lacks: {unknown}")
    routes = dict(link.get("routes", {}))
    if unknown := sorted(set(routes.values()) - events):
        raise ValueError(f"{name}: submachine routes fire events the machine lacks: {unknown}")
    drawn_link = {
        "state": link["state"],
        "machine": machine,
        "exits": dict(link["exits"]),
        "parent": name,
        "when": link.get("when", ""),
        "skill": link.get("skill", ""),
    }
    return drawn_link | {"routes": routes} if routes else drawn_link
