"""A task whose file and read-model row name different lanes is found, re-read, and alerted on if it stays so.

The board draws the Task Events read model, and the task file is only what a write leaves behind. A write that edits a
file and records nothing (an archive's unlink of its dependents, before TASK-10187) leaves the row in the old lane and
the board drawing it, with nothing to correct it until another write to that task.

Each pass compares every open task's row state with its file's lane. A mismatch is reconciled (`Board.reconcile`
appends the Events that bring the History to the file); one found again on the next pass has survived a re-read, so it
is logged and exported as `starpulse_board_lane_mismatch` on `/metrics` for the Grafana rule to raise.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:
    from starpulse.board.model.seam import Board

logger = logging.getLogger(__name__)

METRIC = "starpulse_board_lane_mismatch"
HELP = "Tasks whose file lane differs from the board's, still so a pass after being reconciled."
INTERVAL = 60.0


class _Feed(Protocol):
    def open_tasks(self) -> list[dict]: ...


def mismatches(
    agents: Iterable[Mapping[str, Any]], read: Callable[[str], Mapping[str, Any] | None]
) -> dict[str, tuple[str, str]]:
    """`{task: (file lane, board state)}` for each open agent whose file names another lane; a task with no file is not judged."""
    found = {}
    for agent in agents:
        record = read(agent["id"])
        lane = lane_id(str(record.get("status") or "")) if record else ""
        if lane and lane != agent["state"]:
            found[agent["id"]] = (lane, agent["state"])
    return found


class LaneSweep:
    """Reconciles each mismatched task and keeps the ones a second pass finds mismatched still."""

    def __init__(self, feed: _Feed, board: Board) -> None:
        self._feed, self._board = feed, board
        self._seen: set[str] = set()
        self._persisting: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()

    def sweep(self) -> None:
        found = mismatches(self._feed.open_tasks(), self._board.read)
        for task in found:
            if self._board.reconcile is not None:
                self._board.reconcile(task)
        persisting = {task: lanes for task, lanes in found.items() if task in self._seen}
        self._seen = set(found)
        with self._lock:
            self._persisting = persisting
        if persisting:
            listed = ", ".join(
                f"{task} (file {lanes[0]}, board {lanes[1]})" for task, lanes in sorted(persisting.items())
            )
            logger.error("StarPulse: board lanes differ from the task files after a re-read: %s", listed)

    def exposition(self) -> str:
        """Prometheus text of the gauge: a series per persisting task, none when the board and the files agree."""
        with self._lock:
            series = "".join(
                f'{METRIC}{{task="{task}",file="{lanes[0]}",board="{lanes[1]}"}} 1\n'
                for task, lanes in sorted(self._persisting.items())
            )
        return f"# HELP {METRIC} {HELP}\n# TYPE {METRIC} gauge\n{series}"

    def start(self, stopped: threading.Event) -> None:
        """Sweep on a daemon thread every `INTERVAL` seconds until `stopped` is set."""

        def run() -> None:
            while not stopped.wait(INTERVAL):
                try:
                    self.sweep()
                except Exception as exc:  # the history or a file is unreadable; the next pass tries again
                    logger.warning("StarPulse: the lane sweep failed: %s", exc)

        threading.Thread(target=run, name="lane-sweep", daemon=True).start()
