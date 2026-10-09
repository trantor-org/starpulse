"""A settle row recorded behind the moves it sorts before no longer puts `completed` mid-path in a task's history."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from starpulse._internal.eventlog.history import HistoryStore
from starpulse.tests.machines import MACHINES

#: A swept task's rows as the board migration left them, in the order they landed: the settle was read after the
#: moves, but dated by the file's age (200), so it sorts between Ready and In Progress. Its twin, dated by the floor,
#: closes the path. `T-2` really moved on from `completed` and back, in the order the moves landed.
ROWS = [
    ("trantor/T-1@ready@100.0", "T-1", None, "ready", 100.0),
    ("trantor/T-1@in_progress@300.0", "T-1", "ready", "in_progress", 300.0),
    ("trantor/T-1@done@400.0", "T-1", "in_progress", "done", 400.0),
    ("trantor/T-1@completed@200.0", "T-1", "done", "completed", 200.0),
    ("trantor/T-1@completed@400.0", "T-1", "completed", "completed", 400.0),
    ("trantor/T-2@done@100.0", "T-2", None, "done", 100.0),
    ("trantor/T-2@completed@200.0", "T-2", "done", "completed", 200.0),
    ("trantor/T-2@done@300.0", "T-2", "completed", "done", 300.0),
    ("trantor/T-2@completed@400.0", "T-2", "done", "completed", 400.0),
]


def test_a_settle_recorded_behind_later_moves_is_dropped_when_the_store_starts(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'hub.sqlite'}"
    held = HistoryStore(url, MACHINES)
    with held.engine.begin() as db:
        for event_id, task, old, new, at in ROWS:
            db.execute(
                text(
                    "INSERT INTO starpulse_lane_changes (event_id, task, old_status, new_status, observed_at) "
                    "VALUES (:e, :t, :o, :n, :a)"
                ),
                {"e": event_id, "t": task, "o": old, "n": new, "a": at},
            )
    held.rebuild_summaries()
    held.engine.dispose()

    repaired = HistoryStore(url, MACHINES)

    assert [change["to"] for change in repaired.lane_path("T-1")] == ["ready", "in_progress", "done", "completed"]
    assert [change["to"] for change in repaired.lane_path("T-2")] == ["done", "completed", "done", "completed"]
    assert repaired.summary_differences() == []
