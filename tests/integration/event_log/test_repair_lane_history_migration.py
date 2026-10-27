"""`starpulse migrate` repairs a lane history two writers filled, once: one spelling, one row per move, an unbroken chain."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, text
from starpulse.event_log.migrate import alembic_config, migrate
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.runtime.store_migrate import maintain

from tests.machines import MACHINES
from tests.summaries import assert_matches_rebuild

#: The revision before the one that repairs: a store at it holds whatever rows the two writers left.
BEFORE = "0034"

#: A swept task's rows as the board migration left them, in the order they landed: the settle was read after the
#: moves, but dated by the file's age (200), so it sorts between Ready and In Progress. Its twin, dated by the floor,
#: closes the path. `T-2` really moved on from `completed` and back, in the order the moves landed.
SETTLED = [
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

#: One task's rows as two writers left them, in the order they landed: the replayed board events (a UUID, a status
#: as spelled, the board's time) and the lane stream (a lane id, the feed's later clock), each chaining off whichever
#: row came before it.
TWO_WRITERS = [
    ("trantor/u1", "T-1", None, "Waiting", 100.0),
    ("trantor/T-1@waiting@160.0", "T-1", "Waiting", "waiting", 160.0),  # u1 seen again, a minute late
    ("trantor/u2", "T-1", "waiting", "Ready", 200.0),
    ("trantor/u3", "T-1", "Ready", "In Progress", 300.0),
    ("trantor/T-1@ready@250.0", "T-1", "In Progress", "ready", 250.0),  # u2 seen again, late
    ("trantor/T-1@in_progress@360.0", "T-1", "ready", "in_progress", 360.0),  # u3 seen again, late
    ("trantor/T-1@review@900.0", "T-1", "in_progress", "review", 900.0),  # a move only the stream saw
    ("trantor/u4", "T-1", "review", "Review", 901.0),  # the same move, spelled by the replay
]


def _store_before_the_repair(tmp_path: Path, rows: list[tuple]) -> str:
    """A store holding `rows` and summaries folded from them, at the revision before the repair."""
    url = f"sqlite:///{tmp_path / 'history.sqlite'}"
    held = HistoryStore(url, MACHINES)
    with held.engine.begin() as db:
        for event_id, task, old, new, at in rows:
            db.execute(
                text(
                    "INSERT INTO starpulse_lane_changes (event_id, task, old_status, new_status, observed_at) "
                    "VALUES (:e, :t, :o, :n, :a)"
                ),
                {"e": event_id, "t": task, "o": old, "n": new, "a": at},
            )
    held.rebuild_summaries()
    held.engine.dispose()
    engine = create_engine(url)
    with engine.begin() as db:
        command.stamp(alembic_config(db), BEFORE)
    engine.dispose()
    return url


def test_the_migration_drops_the_settle_recorded_behind_later_moves(tmp_path: Path) -> None:
    url = _store_before_the_repair(tmp_path, SETTLED)

    migrate(create_engine(url))
    repaired = HistoryStore(url, MACHINES)

    assert [change["to"] for change in repaired.lane_path("T-1")] == ["ready", "in_progress", "done", "completed"]
    assert [change["to"] for change in repaired.lane_path("T-2")] == ["done", "completed", "done", "completed"]


def test_the_migration_leaves_one_chain_in_the_lane_id_for_a_store_holding_both_writers_rows(tmp_path: Path) -> None:
    url = _store_before_the_repair(tmp_path, TWO_WRITERS)

    migrate(create_engine(url))

    assert HistoryStore(url, MACHINES).lane_path("T-1") == [
        {"at": 100.0, "from": None, "to": "waiting"},
        {"at": 200.0, "from": "waiting", "to": "ready"},
        {"at": 300.0, "from": "ready", "to": "in_progress"},
        {"at": 900.0, "from": "in_progress", "to": "review"},
    ]


def test_starpulse_migrate_refolds_the_summaries_from_the_repaired_rows_and_a_second_run_changes_nothing(
    tmp_path: Path,
) -> None:
    url = _store_before_the_repair(tmp_path, TWO_WRITERS)

    maintain(url, MACHINES, None)
    repaired = HistoryStore(url, MACHINES)
    assert_matches_rebuild(repaired)

    maintain(url, MACHINES, None)
    assert HistoryStore(url, MACHINES).lane_changes() == repaired.lane_changes()
