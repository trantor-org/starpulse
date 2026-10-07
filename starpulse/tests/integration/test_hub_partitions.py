"""The hub keeps its raw events in daily partitions of `starpulse_events`, created ahead of the clock."""

import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, create_engine, event, text

pytest.importorskip("alembic", reason="the hub extras are not installed")

from starpulse import hub  # noqa: E402
from starpulse.machine_tasks import tables  # noqa: E402
from starpulse.store.event_log import EventLog, Tail  # noqa: E402
from starpulse.tests.machines import MACHINES  # noqa: E402

TODAY = date(2026, 10, 6)


def _epoch(day: date, seconds: float = 0.0) -> float:
    return datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() + seconds


def _url(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def _partitions(engine: Engine) -> list[str]:
    with engine.connect() as db:
        return list(
            db.execute(
                text(
                    "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                    "WHERE i.inhparent = 'starpulse_events'::regclass ORDER BY c.relname"
                )
            ).scalars()
        )


def _insert(engine: Engine, event_id: str, at: float, fields: dict | None = None) -> str:
    """Insert one row through the parent table and return the partition it landed in."""
    with engine.begin() as db:
        return db.execute(
            text(
                "INSERT INTO starpulse_events (stream, event_id, fields, at) "
                "VALUES ('machine:events', :event_id, :fields, :at) RETURNING tableoid::regclass::text"
            ),
            {"event_id": event_id, "fields": json.dumps(fields or {}), "at": at},
        ).scalar_one()


def test_the_hub_creates_tomorrows_partition_ahead_of_time(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))

    hub.ensure_partitions(empty_database, today=TODAY)

    assert _partitions(empty_database) == ["starpulse_events_20261006", "starpulse_events_20261007"]


def test_ensuring_partitions_twice_changes_nothing(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))
    hub.ensure_partitions(empty_database, today=TODAY)

    hub.ensure_partitions(empty_database, today=TODAY)

    assert len(_partitions(empty_database)) == 2


def test_an_insert_at_the_day_boundary_lands_in_the_day_it_belongs_to(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))
    hub.ensure_partitions(empty_database, today=TODAY)
    midnight = _epoch(date(2026, 10, 7))

    assert _insert(empty_database, "last-of-the-6th", midnight - 0.001) == "starpulse_events_20261006"
    assert _insert(empty_database, "first-of-the-7th", midnight) == "starpulse_events_20261007"


def test_the_event_log_appends_once_to_the_partitioned_table(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))
    hub.ensure_partitions(empty_database, today=datetime.now(UTC).date())
    log = EventLog(_url(empty_database))

    first = log.append("machine:events", {"machine": "board"}, event_id="e1")
    again = log.append("machine:events", {"machine": "board"}, event_id="e1")

    assert first is not None
    assert again == first
    with empty_database.connect() as db:
        assert db.execute(text("SELECT count(*) FROM starpulse_events")).scalar() == 1


def _hub_with_a_row_on_each_of(engine: Engine, days: list[date]) -> None:
    hub.prepare(_url(engine))
    for day in days:
        hub.ensure_partitions(engine, today=day, ahead=0)
        _insert(engine, f"on-{day}", _epoch(day, 3600))


def test_retention_drops_old_partitions_whole_and_a_reader_inside_one_records_a_gap(empty_database: Engine) -> None:
    days = [TODAY - timedelta(days=age) for age in (3, 2, 0)]
    _hub_with_a_row_on_each_of(empty_database, days)
    log = EventLog(_url(empty_database))
    reader = Tail(log, "machine:events", after=1)  # it read the 3-day-old row and had not reached the 2-day-old one
    statements: list[str] = []
    event.listen(empty_database, "before_cursor_execute", lambda _c, _cur, sql, *_: statements.append(sql))

    dropped = hub.enforce_retention(empty_database, today=TODAY, retention_days=1, machines={})

    assert dropped == [TODAY - timedelta(days=3), TODAY - timedelta(days=2)]
    assert _partitions(empty_database) == ["starpulse_events_20261006"]
    assert not [sql for sql in statements if sql.lstrip().upper().startswith("DELETE")]
    assert any(sql.lstrip().upper().startswith("DROP TABLE") for sql in statements)
    assert [entry.event_id for entry in reader.poll()] == ["on-2026-10-06"]
    with empty_database.connect() as db:
        gap = db.execute(text("SELECT stream, after_id, before_id, lost FROM starpulse_gaps")).one()
    assert tuple(gap) == ("machine:events", "1", "3", 1)


def test_retention_keeps_every_partition_inside_the_bound(empty_database: Engine) -> None:
    days = [TODAY - timedelta(days=age) for age in (1, 0)]
    _hub_with_a_row_on_each_of(empty_database, days)

    assert hub.enforce_retention(empty_database, today=TODAY, retention_days=1, machines={}) == []
    assert _partitions(empty_database) == ["starpulse_events_20261005", "starpulse_events_20261006"]


def _moved(engine: Engine, day: date, hour: float, task: str, event: str, team: str | None = None) -> None:
    fields = {"machine": "in-progress", "event": event, "task": task, **({"team": team} if team else {})}
    _insert(engine, f"{task}-{event}-{day}", _epoch(day, hour * 3600), fields)


def test_a_days_trend_is_read_from_its_rollup_after_the_raw_day_is_dropped(empty_database: Engine) -> None:
    day, next_day = TODAY - timedelta(days=3), TODAY - timedelta(days=2)
    hub.prepare(_url(empty_database))
    for d in (day, next_day):
        hub.ensure_partitions(empty_database, today=d, ahead=0)
    _moved(empty_database, day, 10, "T1", "WORKTREE_READY", "core")
    _moved(empty_database, day, 10.5, "T1", "RED_PROVEN", "core")
    _moved(empty_database, day, 11, "T1", "GREEN", "core")
    _moved(empty_database, day, 11.25, "T1", "GREEN", "core")  # a loop: not an entry, not an exit
    _moved(empty_database, day, 12, "T2", "WORKTREE_READY", "core")  # never leaves the state
    _moved(empty_database, day, 9, "T3", "WORKTREE_READY", "infra")
    _moved(empty_database, next_day, 9, "T3", "RED_PROVEN", "infra")  # leaves it a day later, in a retained partition
    _moved(empty_database, day, 13, "T4", "WORKTREE_READY")  # a team the event does not name

    dropped = hub.enforce_retention(empty_database, today=TODAY, retention_days=2, machines=tables(MACHINES))

    assert dropped == [day]
    assert _partitions(empty_database) == ["starpulse_events_20261004"]
    with empty_database.connect() as db:
        trend = db.execute(
            text(
                "SELECT team, machine, state, entries, open_entries, seconds FROM starpulse_day_rollups "
                "WHERE day = :day ORDER BY team, state"
            ),
            {"day": day},
        ).all()
    assert [tuple(row) for row in trend] == [
        ("", "in-progress", "worktree_ready", 1, 1, 0.0),
        ("core", "in-progress", "green", 1, 1, 0.0),
        ("core", "in-progress", "red_proven", 1, 0, 1800.0),
        ("core", "in-progress", "worktree_ready", 2, 1, 1800.0),
        ("infra", "in-progress", "worktree_ready", 1, 0, 86400.0),
    ]


def test_a_maintenance_pass_creates_the_next_partitions_and_retires_the_expired_ones(empty_database: Engine) -> None:
    old = TODAY - timedelta(days=5)
    _hub_with_a_row_on_each_of(empty_database, [old])
    noon = datetime(2026, 10, 6, 12, tzinfo=UTC)

    hub.maintain(empty_database, retention_days=2, machines={}, now=noon)

    assert _partitions(empty_database) == ["starpulse_events_20261006", "starpulse_events_20261007"]


def _run_loop_briefly(engine: Engine, until: Callable[[], bool]) -> None:
    """Run `hub.keep` on a short interval in a thread until `until` holds, then stop it."""
    stop = threading.Event()
    loop = threading.Thread(
        target=hub.keep, kwargs={"engine": engine, "retention_days": 2, "machines": {}, "stop": stop, "interval": 0.05}
    )
    loop.start()
    try:
        deadline = time.monotonic() + 10
        while not until() and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        stop.set()
        loop.join(timeout=10)


def test_the_maintenance_loop_runs_a_pass_every_interval(empty_database: Engine) -> None:
    hub.prepare(_url(empty_database))

    _run_loop_briefly(empty_database, lambda: len(_partitions(empty_database)) == 2)

    assert len(_partitions(empty_database)) == 2


def test_a_failed_maintenance_pass_is_logged_and_the_loop_goes_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    unreachable = create_engine(f"sqlite:///{tmp_path / 'not-a-hub.sqlite'}")

    with caplog.at_level(logging.ERROR, logger="starpulse.hub"):
        _run_loop_briefly(unreachable, lambda: caplog.text.count("hub maintenance pass failed") >= 2)

    assert caplog.text.count("hub maintenance pass failed") >= 2
