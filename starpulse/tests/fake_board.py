"""A board adapter the seam tests name by its dotted path: lanes from its settings, one task, one cue."""

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from starpulse.board import Board
from starpulse.contracts import BoardTask, TaskKeys

#: Each `(settings, base)` the view built this board from.
BUILT: list[tuple[dict, Path]] = []


def board(settings: Mapping[str, Any], base: Path) -> Board:
    BUILT.append((dict(settings), base))
    lanes = list(settings["lanes"])
    machine = {
        "states": [
            {"id": lane, "name": lane, "initial": i == 0, "final": i == len(lanes) - 1} for i, lane in enumerate(lanes)
        ],
        "transitions": [{"source": lanes[0], "target": lanes[-1], "event": "SHUT"}],
    }

    def start(feed, group: str) -> None:
        feed.put(BoardTask(id="FAKE-1", title="t", lane=lanes[0]))
        feed.put(BoardTask(id="other-1", title="t", lane=lanes[0]))

    return Board(
        machines=lambda qualify, workflows: {"board": machine},
        start=start,
        keys=TaskKeys(key=re.compile(r"FAKE-\d+"), branch=re.compile(r"(FAKE-\d+)")),
        cues=lambda qualify: [{"dag": "q/nightly"}],
    )
