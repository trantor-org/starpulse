"""A board adapter the seam tests name by its dotted path: lanes from its settings, one task, one cue."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from starpulse.board import Board, Written
from starpulse.contracts.adapters import BoardTask, TaskKeys

#: Each `(settings, base)` the view built this board from.
BUILT: list[tuple[dict, Path]] = []
#: The workflows each draw of its machines was given.
DRAWN: list[list[str]] = []


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
    return Board(
        machines=machines,
        start=start,
        keys=TaskKeys(key=re.compile(r"FAKE-\d+"), branch=re.compile(r"(FAKE-\d+)")),
        cues=lambda qualify: [{"event": "SHUT", "dag": "q/nightly", "state": lanes[-1]}],
        **writers,
    )
