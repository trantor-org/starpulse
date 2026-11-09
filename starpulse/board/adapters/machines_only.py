"""The `machines` board: a project's declared machines, with no task source.

It draws every file under `.starpulse/machines/` as the native board draws them, the Board machine among them, and
places no task: it reads no board directory and writes nothing.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starpulse.board.adapters import project_machines
from starpulse.board.model.seam import Board

if TYPE_CHECKING:
    from starpulse.board.board_feed import BoardFeed
    from starpulse.event_log import EventLog
    from starpulse.machine_engine.model.snapshot import Qualify


def _start(feed: BoardFeed, group: str, log: EventLog) -> None:
    """Nothing to follow: the tasks arrive as lane entries."""


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The machines under `base`'s `.starpulse/machines/`; it takes no settings beyond its `type`."""
    if unknown := sorted(settings.keys() - {"type"}):
        raise ValueError(f"board type machines takes no settings: {', '.join(unknown)}")

    def machines(qualify: Qualify, workflows: Collection[str]) -> dict[str, dict]:
        return project_machines.draw(project_machines.load(base, None), qualify, workflows)

    return Board(machines=machines, start=_start, source="the events instances forward")
