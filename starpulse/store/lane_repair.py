"""Repair a lane history two writers filled: one spelling, one row per board move, an unbroken chain.

A history once took each move twice: from the board's events (a UUID id, the status as spelled, the board's time) and
from the lane stream (`<task>@<lane>@<time>`, the lane id, the time the feed read the move). The pair interleaves into
moves that never happened (`In Progress -> waiting -> Waiting`). `plan` says which rows to drop and how to rewrite the
rest so each task's path chains again; `HistoryStore.repair_lanes` applies it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from starpulse.domain.transitions import lane_id

#: How long after the board made a move the lane stream may have read it and still be taken for the same move.
TWIN_WINDOW_S = 3600.0

#: `(id, event_id, task, old_status, new_status, observed_at)`, a row of `starpulse_lane_changes`.
Row = tuple[int, str, str, str | None, str, float]


def source_of(event_id: str) -> str:
    """The `<source>/` a forwarded event id carries; empty for an id with none."""
    name, slash, _ = event_id.partition("/")
    return name if slash else ""


def _fed(event_id: str) -> bool:
    """Whether the lane stream wrote the row: its id is `<task>@<lane>@<time>`, a board event's a UUID."""
    return "@" in event_id.partition("/")[2]


def plan(rows: Iterable[Row]) -> tuple[dict[int, tuple[str | None, str]], list[int]]:
    """`(rewrites, drops)` that repair `rows`: each rewrite is a row id and its `(old_status, new_status)`, each drop a row id.

    Per task and source, in time order (the earlier insert first on a tie): a row the lane stream wrote is dropped when
    a board row into the same lane came no more than `TWIN_WINDOW_S` before it, each board row twinning one stream
    row; a row into the lane the one before it entered is dropped; the rest are rewritten as lane ids chaining off
    the row before. A history that needs nothing gives two empty results.
    """
    groups: dict[tuple[str, str], list[Row]] = defaultdict(list)
    for row in rows:
        groups[row[2], source_of(row[1])].append(row)
    rewrites: dict[int, tuple[str | None, str]] = {}
    drops: list[int] = []
    for group in groups.values():
        group.sort(key=lambda row: (row[5], row[0]))
        twinned = _twinned(group)
        kept: list[Row] = []
        for row in group:
            if row[0] in twinned or (kept and lane_id(kept[-1][4]) == lane_id(row[4])):
                drops.append(row[0])
            else:
                kept.append(row)
        before: str | None = None
        for id_, _, _, old, new, _ in kept:
            lane = lane_id(new)
            if (old, new) != (before, lane):
                rewrites[id_] = (before, lane)
            before = lane
    return rewrites, drops


def _twinned(group: list[Row]) -> set[int]:
    """The ids of the stream rows that repeat a board row of the same lane, read within `TWIN_WINDOW_S` of it."""
    open_board: dict[str, list[Row]] = defaultdict(list)
    twinned: set[int] = set()
    for row in group:
        lane = lane_id(row[4])
        if not _fed(row[1]):
            open_board[lane].append(row)
            continue
        waiting = open_board[lane]
        match = next((b for b in reversed(waiting) if 0 <= row[5] - b[5] <= TWIN_WINDOW_S), None)
        if match is not None:
            waiting.remove(match)
            twinned.add(row[0])
    return twinned
