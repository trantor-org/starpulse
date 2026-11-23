"""The sweeper's `board-files` kind: the board's files against the feed, the file lanes against the machine lanes, and the
search vectors against the tasks; a lane or file find is counted as a correction, an embedding is not. The StarPulse Operations doc's Board Lane Disagrees
With the Task File section holds the scan sequence and the `starpulse_board_lane_mismatch` metric."""

import logging
import threading
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy.exc import SQLAlchemyError

from starpulse.board.adapters.search import EmbeddingError
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:
    from starpulse.board.model.seam import Board

logger = logging.getLogger(__name__)

METRIC = "starpulse_board_lane_mismatch"
HELP = "Tasks whose file lane differs from the board's, still so a pass after the one that first found it."


class _Feed(Protocol):
    def open_tasks(self) -> list[dict]: ...

    def alias(self, alias: str, task: str) -> None: ...


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
    """Rescans the files, answers each alias, and keeps the tasks whose file lane a second pass finds still apart from the board's.

    `vectors` embeds the tasks that hold no vector and answers `(embedded, indexed)`."""

    def __init__(
        self,
        feed: _Feed,
        board: Board,
        vectors: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        self._feed, self._board = feed, board
        self._vectors = vectors
        self._seen: set[str] = set()
        self._persisting: dict[str, tuple[str, str]] = {}
        self._lock = threading.Lock()

    def _alias(self) -> None:
        """Make each alias a file lists, a done task's included, answer its id."""
        for task, aliases in (*self._board.done_files(), *self._board.files()):
            for alias in aliases:
                self._feed.alias(alias, task)

    def _embed(self) -> tuple[int, int]:
        try:
            return self._vectors() if self._vectors is not None else (0, 0)
        except (EmbeddingError, SQLAlchemyError) as exc:
            logger.warning("StarPulse: the board-files pass cannot embed tasks for search: %s", exc)
            return 0, 0

    def run(self) -> tuple[int, int]:
        """One pass: `(sampled, corrected)`, the order `_BoardKind` reads. `sampled` is the open tasks read and the tasks
        the vector index holds; `corrected` is the lanes reconciled and the files a rescan had to read, each a task a
        push should have placed. Embedding is catch-up after an endpoint timeout or a worker restart, the pass's own
        job, so it is sampled and never counted as a correction."""
        corrected = self._board.rescan()
        self._alias()
        agents = self._feed.open_tasks()
        found = mismatches(agents, self._board.read)
        persisting = {task: lanes for task, lanes in found.items() if task in self._seen}
        self._seen = set(found)
        with self._lock:
            self._persisting = persisting
        if persisting:
            listed = ", ".join(
                f"{task} (file {lanes[0]}, board {lanes[1]})" for task, lanes in sorted(persisting.items())
            )
            logger.error("StarPulse: board lanes differ from the task files after a re-read: %s", listed)
        _, indexed = self._embed()
        return len(agents) + indexed, corrected

    def exposition(self) -> str:
        """Prometheus text of the gauge: a series per persisting task, none when the board and the files agree."""
        with self._lock:
            series = "".join(
                f'{METRIC}{{task="{task}",file="{lanes[0]}",board="{lanes[1]}"}} 1\n'
                for task, lanes in sorted(self._persisting.items())
            )
        return f"# HELP {METRIC} {HELP}\n# TYPE {METRIC} gauge\n{series}"
