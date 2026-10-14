"""What the held and lanes streams share: the Board's columns built once per snapshot, and which changes touch a view.

Every stream used to reread and rebuild on every change to the board, so a change cost every open stream a pass over
the whole board. A stream now wakes only for a change its own view reads, and the streams woken by one change read the
one build of the columns.
"""

import threading
from collections.abc import Sequence
from typing import Any

from starpulse._internal.board.view import board_columns, board_flow
from starpulse._internal.server.snapshot_cache import Served


class ColumnViews:
    """The Board's columns for the snapshot last asked about, built once however many streams read them.

    Streams woken by one change can read snapshots a publish apart, so the columns are reused for any snapshot whose
    Board lanes, settled tasks and pull requests equal those they were built from.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inputs: tuple[Any, ...] | None = None
        self._columns: list[dict[str, Any]] = []

    def of(self, served: Served) -> list[dict[str, Any]]:
        snapshot = served.snapshot
        inputs = (board_flow(snapshot), snapshot["settled"], snapshot["pulls"])
        with self._lock:
            if inputs != self._inputs:
                self._columns = board_columns(snapshot, lambda agent: True)["columns"]
                self._inputs = inputs
            return self._columns


def column_view(columns: list[dict[str, Any]], holder: str | None, states: Sequence[str]) -> dict[str, Any]:
    """The columns of `states` (all when none), each with the tasks `holder` holds (every task when None)."""
    return {
        "columns": [
            {**column, "tasks": [t for t in column["tasks"] if holder is None or t["holder"] == holder]}
            for column in columns
            if not states or column["state"] in states
        ]
    }


class Interest:
    """The changes that alter a stream's view: those to a task it shows, to one a shown task waits on, or to one that
    its `holder` and `states` would show after the change."""

    def __init__(self, view: dict[str, Any], holder: str | None, states: Sequence[str]) -> None:
        tasks = [task for column in view["columns"] for task in column["tasks"]]
        self._ids = {t["id"] for t in tasks} | {dependency for t in tasks for dependency in t["dependencies"]}
        self._pulled = any(t["prs"] for t in tasks)
        self._holder = holder
        self._states = states

    def _shows(self, agent: dict[str, Any]) -> bool:
        return (self._holder is None or agent.get("holder", "") == self._holder) and (
            not self._states or agent["state"] in self._states
        )

    def touched_by(self, kind: str, data: dict[str, Any]) -> bool:
        """Whether the change `kind` publishes with `data` alters the view; a kind the view does not read never does."""
        if kind == "snapshot":
            return True
        if kind == "pulls":
            return self._pulled
        return kind == "task" and (
            data["id"] in self._ids or (data["agent"] is not None and self._shows(data["agent"]))
        )
