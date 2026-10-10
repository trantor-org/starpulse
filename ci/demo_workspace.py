"""The UI preview's synthetic workspace, the Board adapter `ci/preview.toml` names as `ci.demo_workspace`.

It draws what a working team's StarPulse draws, from the machine files in `ci/workspace`: an eight-lane Board whose In
Progress opens a delivery machine (and, under that machine's open pull request, a review triage), and the lifecycle
machines of the other skills an agent session runs. It places no task: `starpulse._internal.cli.demo` seeds the tasks, sessions and
runs at a real workspace's scale onto this structure, so nothing a real tracker holds is behind the public demo.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from starpulse._internal.board.seam import Board
from starpulse._internal.machines.machine_definition import load_machine, refuse_unlisted
from starpulse._internal.machines.snapshot import Qualify, describe

WORKSPACE = Path(__file__).with_name("workspace")
#: The Board's main line, the lanes drawn on its axis; Waiting, Needs Attention and the final states sit off it.
MAIN_LINE = ["new", "ready", "in_progress", "review"]
#: Each machine that opens under another's state: (parent, state, flow, when).
SUBFLOWS = [("board", "in_progress", "delivery", ""), ("delivery", "pr_opened", "review-triage", "a PR is open")]


def _drawn(workflows: Collection[str]) -> tuple[dict[str, dict], list[dict]]:
    """Each machine file drawn under its file name, with the sub-flows that open under it, and the Board's cues."""
    machines, cues = {}, []
    for path in sorted(WORKSPACE.glob("*.yaml")):
        name, compiled = path.stem, load_machine(path)
        if workflows:
            refuse_unlisted(name, compiled.writers, workflows)
        body = describe(compiled.machine)
        if links := [
            {"state": state, "flow": flow, "exits": {}, "parent": parent, "when": when}
            for parent, state, flow, when in SUBFLOWS
            if parent == name
        ]:
            body["subflows"] = links
        if name == "board":
            body["mainLine"] = MAIN_LINE
            body["dagActors"] = sorted({w["actor"] for ws in body.get("writers", {}).values() for w in ws})
            for cue in compiled.cues:
                state = next(t["target"] for t in body["transitions"] if t["event"] == cue.event)
                cues.append({**asdict(cue), "state": state})
        machines[name] = body
    return {"board": machines.pop("board"), **machines}, cues


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The synthetic workspace's Board; it takes no settings beyond its `type` and places no task."""
    if unknown := set(settings) - {"type"}:
        raise ValueError(f"board type ci.demo_workspace takes no settings: {', '.join(sorted(unknown))}")

    def machines(qualify: Qualify, workflows: Collection[str]) -> dict[str, dict]:
        return _drawn(workflows)[0]

    def cues(qualify: Qualify) -> list[dict]:
        return _drawn(())[1]

    return Board(machines=machines, start=lambda feed, group, log: None, cues=cues, source="the demo workspace")
