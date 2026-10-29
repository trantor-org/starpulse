"""What the held and lanes streams share: the Board's columns built once per snapshot, and which changes touch a view.

Every stream used to reread and rebuild on every change to the board, so a change cost every open stream a pass over
the whole board. A stream now wakes only for a change its own view reads, and the streams woken by one change read the
one build of the columns.
"""

import json
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from starpulse.board.model.view import board_columns
from starpulse.views.adapters.inbound.snapshot_cache import Served


class ColumnViews:
    """The Board's columns for the snapshot last asked about, built once however many streams read them.

    Streams woken by one change can read snapshots a publish apart, so the columns are reused for any snapshot whose
    Board lanes, settled tasks and pull requests equal those they were built from.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._served: Served | None = None
        self._inputs: tuple[Any, ...] | None = None
        self._columns: list[dict[str, Any]] = []
        #: One thread makes every view and frame: on a free-threaded interpreter a thread keeps the heap pages of what it
        #: allocated, so a stream thread that made its own view would hold a copy of its share of the board for as long
        #: as the stream is open.
        self._worker = ThreadPoolExecutor(1, thread_name_prefix="column-views")
        self._views: dict[tuple[str | None, tuple[str, ...]], tuple[list[dict[str, Any]], dict[str, Any]]] = {}
        self._frames: dict[tuple[str | None, tuple[str, ...]], tuple[dict[str, Any], str]] = {}

    def render(self, served: Served, assignee: str | None, states: Sequence[str]) -> tuple[dict[str, Any], str]:
        """The view of `assignee` and `states` in `served` with its JSON, made on the one worker thread."""
        return self._worker.submit(self._render, served, assignee, states).result()

    def _render(self, served: Served, assignee: str | None, states: Sequence[str]) -> tuple[dict[str, Any], str]:
        view = self.view(served, assignee, states)
        return view, self.frame(view, assignee, states)

    def view(self, served: Served, assignee: str | None, states: Sequence[str]) -> dict[str, Any]:
        """The view of `assignee` and `states` in `served`, filtered once however many streams with them read it."""
        columns, key = self.of(served), (assignee, tuple(states))
        with self._lock:
            held = self._views.get(key)
        if held is not None and held[0] is columns:
            return held[1]
        view = column_view(columns, assignee, states)
        with self._lock:
            self._views[key] = (columns, view)
        return view

    def frame(self, view: dict[str, Any], assignee: str | None, states: Sequence[str]) -> str:
        """`view` as JSON, encoded once however many streams with the same assignee and states send it."""
        key = (assignee, tuple(states))
        with self._lock:
            held = self._frames.get(key)
        if held is not None and held[0] == view:
            return held[1]
        text = json.dumps(view, ensure_ascii=False)
        with self._lock:
            self._frames[key] = (view, text)
        return text

    def of(self, served: Served) -> list[dict[str, Any]]:
        with self._lock:
            if served is self._served:
                return self._columns  # a stream rereading the snapshot it read last allocates nothing
            snapshot = served.snapshot
            inputs = (snapshot["flows"], snapshot["settled"], snapshot["pulls"], snapshot.get("interactive"))
            self._served = served
            if inputs != self._inputs:
                self._columns = board_columns(snapshot, lambda agent: True)["columns"]
                self._inputs = inputs
            return self._columns


def column_view(columns: list[dict[str, Any]], assignee: str | None, states: Sequence[str]) -> dict[str, Any]:
    """The columns of `states` (all when none), each with the tasks `assignee` holds (every task when None)."""
    return {
        "columns": [
            {**column, "tasks": [t for t in column["tasks"] if assignee is None or t["assignee"] == assignee]}
            for column in columns
            if not states or column["state"] in states
        ]
    }


class Interest:
    """The changes that alter a stream's view: those to a task it shows, to one a shown task waits on, or to one that
    its `assignee` and `states` would show after the change."""

    def __init__(self, view: dict[str, Any], assignee: str | None, states: Sequence[str]) -> None:
        tasks = [task for column in view["columns"] for task in column["tasks"]]
        self._ids = {t["id"] for t in tasks} | {dependency for t in tasks for dependency in t["dependencies"]}
        self._pulled = any(t["prs"] for t in tasks)
        self._assignee = assignee
        self._states = states

    def _shows(self, agent: dict[str, Any]) -> bool:
        return (self._assignee is None or agent.get("assignee", "") == self._assignee) and (
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
