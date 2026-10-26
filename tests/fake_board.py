"""A board adapter the seam tests name by its dotted path: lanes from its settings, one task, one cue."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from starpulse.board.model.seam import Board, Written
from starpulse.contracts.adapters import BoardTask, TaskKeys
from starpulse.machine_engine.model.state_roles import StateRoles

#: Each `(settings, base)` the view built this board from.
BUILT: list[tuple[dict, Path]] = []
#: The workflows each draw of its machines was given.
DRAWN: list[list[str]] = []
#: Each feed the board's claim sweep was started on.
SWEPT: list[Any] = []


def board(settings: Mapping[str, Any], base: Path) -> Board:
    BUILT.append((dict(settings), base))
    lanes = list(settings["lanes"])
    machine = {
        "states": [
            {"id": lane, "name": lane, "initial": i == 0, "final": i == len(lanes) - 1} for i, lane in enumerate(lanes)
        ],
        "transitions": [{"source": lanes[0], "target": lanes[-1], "event": "SHUT"}],
    }

    def machines(qualify, workflows) -> dict:
        DRAWN.append(list(workflows))
        return {"board": machine}

    def start(feed, group: str, log) -> None:
        feed.put(BoardTask(id="FAKE-1", team="demo", title="t", lane=lanes[0]))
        feed.put(BoardTask(id="other-1", team="demo", title="t", lane=lanes[0]))

    writers: dict[str, Any] = {}
    if settings.get("writes"):
        writers = {
            "read": lambda task: {"title": "t"},
            "edit": lambda task, changes, comment: Written(True, ""),
            "archive": lambda task, reason: Written(True, ""),
        }
    waits = {"ready": {"criteria_unmet": ""}, "waiting": {"criteria_met": ""}}
    roles = StateRoles(
        StateRoles.of_statuses(lanes).roles, {lane: facts for lane, facts in waits.items() if lane in lanes}
    )
    return Board(
        machines=machines,
        roles=roles,
        start=start,
        sweep=lambda feed, log, persist: SWEPT.append(feed),
        keys=TaskKeys(key=re.compile(r"FAKE-\d+"), branch=re.compile(r"(FAKE-\d+)")),
        cues=lambda qualify: [{"event": "SHUT", "dag": "q/nightly", "state": lanes[-1]}],
        **writers,
    )


def bare_board(**fields: Any) -> Board:
    """A Board that places nothing and keeps only `fields`, for a test of one route through `serve`."""
    return Board(machines=lambda qualify, workflows: {}, start=lambda feed, name, log: None, **fields)
