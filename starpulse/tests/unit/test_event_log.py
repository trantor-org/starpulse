"""The event log's rules on SQLite: fail-open append, replay and resume by cursor, retention and gaps."""

import sqlite3
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from starpulse.event_log import DEFAULT_POLL_INTERVAL, EventLog, Tail, _sqlite_pragmas
from starpulse.tables import metadata


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


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


def test_a_poll_reads_at_most_one_batch(log: EventLog) -> None:
    for n in range(5):
        log.append("a", {"n": str(n)})
    tail = Tail(log, "a", batch=2)

    assert [[e.id for e in tail.poll()] for _ in range(3)] == [[1, 2], [3, 4], [5]]


def test_a_cursor_below_the_oldest_retained_row_is_a_gap_and_the_tail_reads_on(log: EventLog) -> None:
    for n in range(3):
        log.append("a", {"n": str(n)})
    assert log.prune(retention=0, now=time.time() + 10) == 3
    log.append("a", {"n": "kept-1"})
    log.append("a", {"n": "kept-2"})
    resumed = Tail(log, "a", after=1)  # read row 1 and nothing after it before the prune

    assert [e.fields["n"] for e in resumed.poll()] == ["kept-1", "kept-2"]
    assert [e.id for e in resumed.poll()] == []
    assert _gaps(log) == [("a", "1", "4", 2)]  # rows 2 and 3 were pruned unread; ids continue past the prune


def test_a_gap_is_recorded_once_for_the_same_cursor(log: EventLog) -> None:
    log.append("a", {"n": "old"})
    log.prune(retention=0, now=time.time() + 10)
    log.append("a", {"n": "new"})

    Tail(log, "a", after=0).poll()
    Tail(log, "a", after=0).poll()

    assert _gaps(log) == [("a", "0", "2", 1)]


def test_a_replay_from_the_start_of_retention_is_not_a_gap(log: EventLog) -> None:
    log.append("a", {"n": "old"})
    log.prune(retention=0, now=time.time() + 10)
    log.append("a", {"n": "new"})

    assert [e.fields["n"] for e in Tail(log, "a").poll()] == ["new"]
    assert _gaps(log) == []


def test_a_tail_that_kept_up_across_a_prune_of_everything_it_read_is_no_gap(log: EventLog) -> None:
    tail = Tail(log, "a")
    log.append("a", {"n": "1"})
    tail.poll()
    log.prune(retention=0, now=time.time() + 10)
    log.append("a", {"n": "2"})

    assert [e.id for e in tail.poll()] == [2]  # the id after the pruned one: SQLite does not reuse it
    assert _gaps(log) == []


def test_a_prune_removes_only_rows_older_than_the_retention(log: EventLog) -> None:
    log.append("a", {"n": "old"})
    time.sleep(0.05)
    log.append("a", {"n": "new"})
    newest = Tail(log, "a").poll()[-1].at

    assert log.prune(retention=0.02, now=newest + 0.01) == 1  # the cutoff falls between the two rows
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
