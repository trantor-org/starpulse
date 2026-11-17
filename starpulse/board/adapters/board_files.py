"""The sweeper's `board-files` kind: the board's files against the feed, the file lanes against the machine lanes, and the
search vectors against the tasks. The directory watch (`NativeScan.start`) pushes every file change; this pass finds what
it missed and counts each find as a correction.

The board draws the Task Events read model, and the task file is only what a write leaves behind. A write that edits a
file and records nothing (an archive's unlink of its dependents, before TASK-10187) leaves the row in the old lane and
the board drawing it, with nothing to correct it until another write to that task.

Each pass re-reads the files the watch did not place, then compares every open task's row state with its file's lane. A
mismatch is reconciled (`Board.reconcile` appends the Events that bring the History to the file); one found again on the
next pass has survived a re-read, so it is logged and exported as `starpulse_board_lane_mismatch` on `/metrics` for the
Grafana rule to raise.
"""

import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy.exc import SQLAlchemyError

from starpulse.board.adapters.search import EmbeddingError
from starpulse.board.adapters.task_history import RECONCILER
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:
    from starpulse.board.model.seam import Board

logger = logging.getLogger(__name__)

METRIC = "starpulse_board_lane_mismatch"
HELP = "Tasks whose file lane differs from the board's, still so a pass after being reconciled."


class _Feed(Protocol):
    recording: threading.RLock

    def open_tasks(self) -> list[dict]: ...

    def done_tasks(self) -> list[str]: ...

    def alias(self, alias: str, task: str) -> None: ...

    def record_written(self, task_id: str, lane: str, at: float, who: tuple[str, str, str]) -> None: ...


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


class BoardFiles:
    """Reconciles each mismatched task and keeps the ones a second pass finds mismatched still.

    `rescan` is a full pass of the board's files that answers how many it had to read (the watch had not placed them),
    and `vectors` embeds the tasks that hold no vector and answers `(embedded, indexed)`."""

    def __init__(
        self,
        feed: _Feed,
        board: Board,
        rescan: Callable[[], int] | None = None,
        vectors: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        self._feed, self._board = feed, board
        self._rescan, self._vectors = rescan, vectors
        self._seen: set[str] = set()
        self._absent: set[str] = set()
        self._persisting: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()

    def _place(self) -> int:
        """Bring the read model to the files where a rename left them apart: a listed file it lacks is reconciled, which
        seeds its History, and each alias a file lists, a done task's included, answers its id; an open task, or a Done one the live set has cooled out of, whose file is absent on two passes in
        a row, or whose id is only an alias another file lists (a rename's ghost), is reconciled, which archives it. With no files listed nothing is judged absent.
        Returns how many reconciles appended Events."""
        for task, aliases in self._board.done_files() if self._board.done_files is not None else ():
            for alias in aliases:
                self._feed.alias(alias, task)
        files = list(self._board.files()) if self._board.files is not None else []
        if not files:
            self._absent = set()
            return 0
        corrected = 0
        known = {agent["id"] for agent in self._feed.open_tasks()} | set(self._feed.done_tasks())
        for task, aliases in files:
            if task not in known:
                corrected += bool(self._board.reconcile(task))
            for alias in aliases:
                self._feed.alias(alias, task)
        renamed = {alias for _task, aliases in files for alias in aliases} - {task for task, _aliases in files}
        absent = {task for task in known if task in renamed or self._board.read(task) is None}
        for task in absent & self._absent:
            corrected += bool(self._board.reconcile(task))
        self._absent = absent
        return corrected

    def _reconcile(self, task: str, lane: str) -> bool:
        """Reconcile `task` holding the feed's `recording`, and record the file's lane as the sweep's lane change."""
        with self._feed.recording:
            if not self._board.reconcile(task):
                return False
            self._feed.record_written(task, lane, time.time(), (RECONCILER, "", ""))
            return True

    def _embed(self) -> tuple[int, int]:
        try:
            return self._vectors() if self._vectors is not None else (0, 0)
        except (EmbeddingError, SQLAlchemyError) as exc:
            logger.warning("StarPulse: the board-files pass cannot embed tasks for search: %s", exc)
            return 0, 0

    def run(self) -> tuple[int, int]:
        """One pass: `(corrected, sampled)`, the sweeper's counts for the kind."""
        corrected = self._rescan() if self._rescan is not None else 0
        corrected += self._place()
        agents = self._feed.open_tasks()
        found = mismatches(agents, self._board.read)
        for task, (lane, _state) in found.items():
            if self._board.reconcile is not None:
                corrected += self._reconcile(task, lane)
        persisting = {task: lanes for task, lanes in found.items() if task in self._seen}
        self._seen = set(found)
        with self._lock:
            self._persisting = persisting
        if persisting:
            listed = ", ".join(
                f"{task} (file {lanes[0]}, board {lanes[1]})" for task, lanes in sorted(persisting.items())
            )
            logger.error("StarPulse: board lanes differ from the task files after a re-read: %s", listed)
        embedded, indexed = self._embed()
        return corrected + embedded, len(agents) + indexed

    def exposition(self) -> str:
        """Prometheus text of the gauge: a series per persisting task, none when the board and the files agree."""
        with self._lock:
            series = "".join(
                f'{METRIC}{{task="{task}",file="{lanes[0]}",board="{lanes[1]}"}} 1\n'
                for task, lanes in sorted(self._persisting.items())
            )
        return f"# HELP {METRIC} {HELP}\n# TYPE {METRIC} gauge\n{series}"
