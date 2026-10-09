"""The event log's rules on SQLite: fail-open append, replay and resume by cursor, retention and gaps."""

import gzip
import json
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, text, update
from sqlalchemy.exc import OperationalError

from starpulse._internal.eventlog.event_log import (
    DEFAULT_POLL_INTERVAL,
    EventLog,
    Tail,
    _sqlite_pragmas,
    create_tables,
    prune_forever,
)
from starpulse._internal.eventlog.tables import events, metadata


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    return tmp_path / "archive"


def _gaps(log: EventLog) -> list[tuple]:
    with log.engine.connect() as db:
        return [tuple(r) for r in db.execute(text("SELECT stream, after_id, before_id, lost FROM starpulse_gaps"))]


def test_append_returns_the_next_cursor_and_keeps_the_fields(log: EventLog) -> None:
    first = log.append("machine:events", {"machine": "m", "event": "A"})
    second = log.append("machine:events", {"machine": "m", "event": "B"})

    assert (first, second) == (1, 2)
    [entry, _] = Tail(log, "machine:events").poll()
    assert (entry.id, entry.stream, entry.fields["event"]) == (1, "machine:events", "A")


def test_an_append_mints_an_event_id_unless_the_fields_or_caller_supply_one(log: EventLog) -> None:
    log.append("s", {"k": "v"})
    log.append("s", {"event_id": "from-fields"})
    log.append("s", {"event_id": "ignored"}, event_id="from-caller")

    ids = [e.event_id for e in Tail(log, "s").poll()]

    assert ids[0] not in {"from-fields", "from-caller", ""}
    assert ids[1:] == ["from-fields", "from-caller"]


def test_a_repeated_event_id_is_one_row_and_returns_the_first_cursor(log: EventLog) -> None:
    first = log.append("s", {"event_id": "e-1", "n": "1"})
    again = log.append("s", {"event_id": "e-1", "n": "2"})
    after = log.append("s", {"event_id": "e-2"})

    assert (first, again, after) == (1, 1, 2)
    assert [e.fields.get("n") for e in Tail(log, "s").poll()] == ["1", None]


def test_an_append_to_an_unreachable_database_returns_none_without_raising(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'missing-directory' / 'events.sqlite'}")

    assert log.append("s", {"k": "v"}) is None


def test_an_append_with_fields_that_are_not_json_returns_none_without_raising(log: EventLog) -> None:
    assert log.append("s", {"k": object()}) is None  # type: ignore[dict-item]
    assert log.append("s", {"k": "v"}) == 1  # the failed attempt left no row and the log still works


def test_a_log_whose_database_appears_later_appends_once_it_is_reachable(tmp_path: Path) -> None:
    directory = tmp_path / "later"
    log = EventLog(f"sqlite:///{directory / 'events.sqlite'}")
    assert log.append("s", {"k": "v"}) is None

    directory.mkdir()

    assert log.append("s", {"k": "v"}) == 1


def test_a_producer_that_loses_the_race_to_create_the_tables_still_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    create_all = metadata.create_all
    attempts: list[int] = []

    def lose_the_race(engine, **kwargs) -> None:
        attempts.append(1)
        create_all(engine, **kwargs)  # the other process's tables exist ...
        if len(attempts) == 1:
            raise OperationalError("CREATE TABLE starpulse_events", {}, Exception("table already exists"))

    monkeypatch.setattr(metadata, "create_all", lose_the_race)

    assert log.append("s", {"k": "v"}) == 1
    assert len(attempts) == 2


def test_a_new_tail_replays_its_stream_from_the_start_of_retention_in_order(log: EventLog) -> None:
    log.append("a", {"n": "1"})
    log.append("b", {"n": "other stream"})
    log.append("a", {"n": "2"})
    tail = Tail(log, "a")

    assert [e.fields["n"] for e in tail.poll()] == ["1", "2"]
    assert tail.poll() == []
    assert tail.cursor == 3  # the cursor passed the other stream's row too


def test_a_tail_returns_only_what_was_appended_since_its_last_poll(log: EventLog) -> None:
    tail = Tail(log, "a")
    log.append("a", {"n": "1"})
    assert [e.id for e in tail.poll()] == [1]

    log.append("a", {"n": "2"})

    assert [e.id for e in tail.poll()] == [2]


def test_a_tail_resumes_after_the_cursor_it_is_given(log: EventLog) -> None:
    for n in range(4):
        log.append("a", {"n": str(n)})

    resumed = Tail(log, "a", after=2)

    assert [e.id for e in resumed.poll()] == [3, 4]
    assert _gaps(log) == []


def test_a_tail_over_several_streams_reads_them_in_log_order_under_one_cursor(log: EventLog) -> None:
    log.append("a", {"n": 1})
    log.append("other", {"n": 2})
    log.append("b", {"n": 3})
    log.append("a", {"n": 4})

    tail = Tail(log, "forward", streams=("a", "b"))

    assert [(e.stream, e.fields["n"]) for e in tail.poll()] == [("a", 1), ("b", 3), ("a", 4)]
    assert tail.cursor == 4
    assert tail.poll() == []


def test_a_gap_before_a_multi_stream_tail_is_recorded_under_the_readers_name(log: EventLog, archive: Path) -> None:
    for n in range(4):
        log.append("a", {"n": n})
    log.prune(0, now=time.time() + 1, archive_dir=archive)
    log.append("a", {"n": 9})

    Tail(log, "forward", streams=("a", "b"), after=2).poll()

    assert [row[0] for row in _gaps(log)] == ["forward"]


def test_a_poll_reads_at_most_one_batch(log: EventLog) -> None:
    for n in range(5):
        log.append("a", {"n": str(n)})
    tail = Tail(log, "a", batch=2)

    assert [[e.id for e in tail.poll()] for _ in range(3)] == [[1, 2], [3, 4], [5]]


def test_a_cursor_below_the_oldest_retained_row_is_a_gap_and_the_tail_reads_on(log: EventLog, archive: Path) -> None:
    for n in range(3):
        log.append("a", {"n": str(n)})
    assert log.prune(retention=0, now=time.time() + 10, archive_dir=archive) == 3
    log.append("a", {"n": "kept-1"})
    log.append("a", {"n": "kept-2"})
    resumed = Tail(log, "a", after=1)  # read row 1 and nothing after it before the prune

    assert [e.fields["n"] for e in resumed.poll()] == ["kept-1", "kept-2"]
    assert [e.id for e in resumed.poll()] == []
    assert _gaps(log) == [("a", "1", "4", 2)]  # rows 2 and 3 were pruned unread; ids continue past the prune


def test_a_gap_is_recorded_once_for_the_same_cursor(log: EventLog, archive: Path) -> None:
    log.append("a", {"n": "old"})
    log.prune(retention=0, now=time.time() + 10, archive_dir=archive)
    log.append("a", {"n": "new"})

    Tail(log, "a", after=0).poll()
    Tail(log, "a", after=0).poll()

    assert _gaps(log) == [("a", "0", "2", 1)]


def test_a_replay_from_the_start_of_retention_is_not_a_gap(log: EventLog, archive: Path) -> None:
    log.append("a", {"n": "old"})
    log.prune(retention=0, now=time.time() + 10, archive_dir=archive)
    log.append("a", {"n": "new"})

    assert [e.fields["n"] for e in Tail(log, "a").poll()] == ["new"]
    assert _gaps(log) == []


def test_a_tail_that_kept_up_across_a_prune_of_everything_it_read_is_no_gap(log: EventLog, archive: Path) -> None:
    tail = Tail(log, "a")
    log.append("a", {"n": "1"})
    tail.poll()
    log.prune(retention=0, now=time.time() + 10, archive_dir=archive)
    log.append("a", {"n": "2"})

    assert [e.id for e in tail.poll()] == [2]  # the id after the pruned one: SQLite does not reuse it
    assert _gaps(log) == []


def test_a_prune_removes_only_rows_older_than_the_retention(log: EventLog, archive: Path) -> None:
    log.append("a", {"n": "old"})
    time.sleep(0.05)
    log.append("a", {"n": "new"})
    newest = Tail(log, "a").poll()[-1].at

    assert (
        log.prune(retention=0.02, now=newest + 0.01, archive_dir=archive) == 1
    )  # the cutoff falls between the two rows
    assert [e.fields["n"] for e in Tail(log, "a").poll()] == ["new"]


def test_the_default_poll_interval_is_at_most_half_a_second(log: EventLog) -> None:
    assert DEFAULT_POLL_INTERVAL <= 0.5
    assert Tail(log, "a").interval == DEFAULT_POLL_INTERVAL


@pytest.mark.parametrize("appended", [False, True])
def test_a_poll_returns_its_connection_so_no_read_transaction_outlasts_it(log: EventLog, appended: bool) -> None:
    if appended:
        log.append("a", {"n": "1"})
    tail = Tail(log, "a")

    tail.poll()

    assert log.engine.pool.checkedout() == 0  # type: ignore[attr-defined]


def test_the_sqlite_log_is_in_wal_mode_so_other_processes_append_while_a_reader_reads(log: EventLog) -> None:
    with log.engine.connect() as db:
        assert db.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_run_hands_each_entry_to_the_handler_and_stops_when_asked(log: EventLog) -> None:
    for n in range(3):
        log.append("a", {"n": str(n)})
    stop = threading.Event()
    seen: list[int] = []

    def handle(entry) -> None:
        seen.append(entry.id)
        if len(seen) == 3:
            stop.set()

    Tail(log, "a", interval=0.01).run(handle, stop)

    assert seen == [1, 2, 3]


def test_run_keeps_polling_after_a_failed_poll_and_after_a_failing_handler(
    log: EventLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    log.append("a", {"n": "1"})
    log.append("a", {"n": "2"})
    tail = Tail(log, "a", interval=0.01)
    real_poll = tail.poll
    calls = {"n": 0}

    def flaky_poll():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database went away")
        return real_poll()

    monkeypatch.setattr(tail, "poll", flaky_poll)
    stop = threading.Event()
    seen: list[int] = []

    def handle(entry) -> None:
        seen.append(entry.id)
        if entry.id == 1:
            raise ValueError("handler bug")
        stop.set()

    tail.run(handle, stop)

    assert seen == [1, 2]


def test_last_is_the_newest_cursor_of_one_stream_and_none_when_it_has_no_rows(log: EventLog) -> None:
    log.append("a", {"n": "1"})
    newest = log.append("a", {"n": "2"})
    log.append("b", {"n": "3"})

    assert (log.last("a"), log.last("c")) == (newest, None)


def test_run_reads_an_entry_again_when_its_handler_fails_with_a_transient_error(log: EventLog) -> None:
    log.append("a", {"n": "1"})
    log.append("a", {"n": "2"})
    stop = threading.Event()
    seen: list[int] = []

    def handle(entry) -> None:
        seen.append(entry.id)
        if seen == [1, 2]:
            raise OperationalError("insert", {}, Exception("database is locked"))
        if len(seen) == 3:
            stop.set()

    Tail(log, "a", interval=0.01).run(handle, stop, transient=(OperationalError,))

    assert seen == [1, 2, 2]


class _LockedOnce:
    """A SQLite connection whose first statement finds the database locked, as one opened beside another does."""

    def __init__(self) -> None:
        self.locked = True
        self.executed: list[str] = []

    def cursor(self) -> "_LockedOnce":
        return self

    def execute(self, statement: str) -> None:
        if self.locked:
            self.locked = False
            raise sqlite3.OperationalError("database is locked")
        self.executed.append(statement)

    def close(self) -> None:
        pass


def test_a_new_connection_that_finds_the_database_locked_sets_its_pragmas_once_it_is_free() -> None:
    connection = _LockedOnce()

    _sqlite_pragmas(connection, None)

    assert connection.executed == ["PRAGMA journal_mode=WAL", "PRAGMA synchronous=NORMAL"]


def test_an_instances_database_never_gains_the_hubs_rollups(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")

    create_tables(log.engine)

    names = set(inspect(log.engine).get_table_names())
    assert "starpulse_events" in names
    assert "starpulse_day_rollups" not in names


class _SpyLog:
    """Stands in for the log at the one seam under test, what the timer asks it to prune; `outcomes` is what each
    pass does, an exception to raise or None, and the last pass stops the timer."""

    def __init__(self, stop: threading.Event, outcomes: list[Exception | None]) -> None:
        self.stop = stop
        self.outcomes = outcomes
        self.retentions: list[float] = []
        self.archives: list[Path] = []

    def prune(self, retention: float, *, archive_dir: Path) -> int:
        self.retentions.append(retention)
        self.archives.append(archive_dir)
        outcome = self.outcomes[len(self.retentions) - 1]
        if len(self.retentions) == len(self.outcomes):
            self.stop.set()
        if outcome is not None:
            raise outcome
        return 0


def test_the_prune_timer_prunes_at_start_and_every_interval_with_the_configured_days_in_seconds(archive: Path) -> None:
    stop = threading.Event()
    spy = _SpyLog(stop, [None, None, None])

    prune_forever(spy, retention_days=7, archive_dir=archive, stop=stop, interval=0.001)

    assert spy.retentions == [7 * 86400] * 3
    assert spy.archives == [archive] * 3


def test_a_prune_pass_that_fails_is_retried_on_the_next_interval(archive: Path) -> None:
    stop = threading.Event()
    spy = _SpyLog(stop, [OperationalError("DELETE", {}, Exception("database is locked")), None])

    prune_forever(spy, retention_days=1, archive_dir=archive, stop=stop, interval=0.001)

    assert spy.retentions == [86400, 86400]


def _day(year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0) -> float:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC).timestamp()


def _age(log: EventLog, ages: dict[int, float]) -> None:
    with log.engine.begin() as db:
        for row_id, at in ages.items():
            db.execute(update(events).where(events.c.id == row_id).values(at=at))


def _read(path: Path) -> list[dict]:
    with gzip.open(path, "rt") as lines:
        return [json.loads(line) for line in lines]


def test_a_prune_writes_every_row_it_deletes_to_its_utc_day_file_and_a_later_prune_appends(
    log: EventLog, archive: Path
) -> None:
    for n in range(4):
        log.append("a", {"n": n}, event_id=f"e{n}")
    late_day_one = _day(2026, 9, 1, 23, 59, 59)
    early_day_two = _day(2026, 9, 2, 0, 0, 1)
    _age(log, {1: late_day_one, 2: early_day_two, 3: early_day_two + 5})

    assert log.prune(retention=5, now=early_day_two + 10, archive_dir=archive) == 2

    assert sorted(p.name for p in archive.iterdir()) == ["2026-09-01.jsonl.gz", "2026-09-02.jsonl.gz"]
    assert [r["id"] for r in _read(archive / "2026-09-01.jsonl.gz")] == [1]
    assert [r["id"] for r in _read(archive / "2026-09-02.jsonl.gz")] == [2]  # row 3 is still inside retention

    assert log.prune(retention=0, now=early_day_two + 10 + 86400 * 2, archive_dir=archive) == 1  # row 4 is current

    assert [r["id"] for r in _read(archive / "2026-09-02.jsonl.gz")] == [2, 3]  # appended, in id order
    assert [r["id"] for r in _read(archive / "2026-09-01.jsonl.gz")] == [1]


def test_an_archived_row_carries_every_column(log: EventLog, archive: Path) -> None:
    log.append("machine:events", {"machine": "m", "event": "A", "nested": {"k": [1, 2]}}, event_id="evt-1")
    at = _day(2026, 9, 3, 12, 30)
    _age(log, {1: at})

    log.prune(retention=0, now=at + 1, archive_dir=archive)

    [row] = _read(archive / "2026-09-03.jsonl.gz")
    assert row == {
        "id": 1,
        "stream": "machine:events",
        "event_id": "evt-1",
        "fields": {"machine": "m", "event": "A", "nested": {"k": [1, 2]}},
        "at": at,
    }


def test_a_failed_archive_write_deletes_no_row(log: EventLog, archive: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for n in range(3):
        log.append("a", {"n": n})
    at = _day(2026, 9, 4)
    _age(log, {1: at, 2: at, 3: at})

    def refuse(_fd: int) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "fsync", refuse)
    with pytest.raises(OSError, match="disk full"):
        log.prune(retention=0, now=at + 1, archive_dir=archive)
    monkeypatch.undo()

    assert [e.id for e in Tail(log, "a").poll()] == [1, 2, 3]
    day = archive / "2026-09-04.jsonl.gz"
    assert not day.exists() or day.stat().st_size == 0  # no torn member is left for a reader to trip on
    assert log.prune(retention=0, now=at + 1, archive_dir=archive) == 3  # the retry archives them once
    assert [r["id"] for r in _read(day)] == [1, 2, 3]
