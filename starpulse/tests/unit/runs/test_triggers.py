"""A board event a `[[triggers]]` table matches starts its run once, through the runs adapter's `start`."""

import threading
import time
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy.exc import OperationalError

from starpulse._internal.config.triggers import EVENTS, Trigger
from starpulse._internal.eventlog import events, lane_events
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore
from starpulse._internal.runs.triggers import STREAMS, run_triggers
from starpulse.contracts.adapters import StartFailedError

_DONE = Trigger("lane", "dagu/reconcile", {"lane": {"equals": "done"}})
_CURSOR = "triggers"


class _Dagu:
    """The `start` a serve takes from the dagu runs adapter: each call is one run started."""

    def __init__(self, failing: bool = False) -> None:
        self.calls: list[str] = []
        self.failing = failing

    def __call__(self, workflow: str) -> str:
        self.calls.append(workflow)
        if self.failing:
            raise StartFailedError("dagu is down")
        return f"run-{len(self.calls)}"


class _LockedOnce:
    """A store whose next cursor save fails as a locked database does, then works."""

    def __init__(self, store: HistoryStore) -> None:
        self.store = store
        self.armed = False

    def cursor(self, stream: str) -> int | None:
        return self.store.cursor(stream)

    def save_cursor(self, stream: str, after_id: int) -> None:
        if self.armed:
            self.armed = False
            raise OperationalError("save_cursor", {}, Exception("database is locked"))
        self.store.save_cursor(stream, after_id)


def test_every_event_a_trigger_may_name_has_a_stream() -> None:
    assert set(STREAMS) == set(EVENTS)


@pytest.fixture
def log(store: HistoryStore) -> EventLog:
    return EventLog(store.engine.url.render_as_string(hide_password=False), engine=store.engine)


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def _until(done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 10
    while not done():
        assert time.monotonic() < deadline, "the consumer never got there"
        time.sleep(0.01)


def _run(
    triggers: list[Trigger], dagu: _Dagu, store: HistoryStore, log: EventLog, stop: threading.Event
) -> threading.Thread:
    """Start the consumer and return once it has taken its place in the log, so what follows is after it."""
    thread = threading.Thread(
        target=run_triggers,
        args=(triggers, {"dagu": dagu}, store, log, stop),
        kwargs={"interval": 0.01},
        daemon=True,
    )
    thread.start()
    _until(lambda: store.cursor(_CURSOR) is not None)
    return thread


def _stop(stop: threading.Event, thread: threading.Thread) -> None:
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def _move(log: EventLog, task: str, lane: str, at: float) -> int:
    cursor = lane_events.append(log, f"{task}@{lane}@{at}", task, lane, at)
    assert cursor is not None
    return cursor


def _passed(store: HistoryStore, cursor: int) -> None:
    _until(lambda: (store.cursor(_CURSOR) or 0) >= cursor)


def test_a_matching_lane_event_starts_the_declared_run_once_and_a_replayed_event_starts_no_second(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    dagu = _Dagu()
    thread = _run([_DONE], dagu, store, log, stop)

    first = _move(log, "TASK-1", "done", 100.0)
    replayed = _move(log, "TASK-1", "done", 100.0)  # the producer sent the same event id again
    after = _move(log, "TASK-2", "review", 101.0)  # the consumer has read past the replay once this is passed
    _passed(store, after)
    _stop(stop, thread)

    assert replayed == first
    assert dagu.calls == ["reconcile"]


def test_an_entry_read_again_after_a_failed_cursor_save_starts_no_second_run(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    dagu, locked = _Dagu(), _LockedOnce(store)
    thread = _run([_DONE], dagu, locked, log, stop)  # type: ignore[arg-type]

    locked.armed = True
    _move(log, "TASK-1", "done", 100.0)  # started, then its cursor save fails: the entry is read again
    _until(lambda: not locked.armed)
    after = _move(log, "TASK-2", "review", 101.0)
    _passed(store, after)
    _stop(stop, thread)

    assert dagu.calls == ["reconcile"]


def test_a_restart_resumes_after_its_saved_cursor_and_starts_nothing_twice(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    dagu = _Dagu()
    first = _run([_DONE], dagu, store, log, stop)
    _move(log, "TASK-1", "done", 100.0)
    _until(lambda: dagu.calls)
    _stop(stop, first)

    again = threading.Event()
    second = _run([_DONE], dagu, store, log, again)
    later = _move(log, "TASK-3", "done", 102.0)
    _passed(store, later)
    _stop(again, second)

    assert dagu.calls == ["reconcile", "reconcile"]  # TASK-1 once, TASK-3 once


def test_an_event_that_matches_no_filter_starts_no_run(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    dagu = _Dagu()
    thread = _run([_DONE], dagu, store, log, stop)

    last = _move(log, "TASK-1", "review", 100.0)
    _passed(store, last)
    _stop(stop, thread)

    assert dagu.calls == []


def test_a_trigger_reads_only_the_stream_its_event_names(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    dagu = _Dagu()
    thread = _run([Trigger("machine", "dagu/criteria", {})], dagu, store, log, stop)

    _move(log, "TASK-1", "done", 100.0)
    last = log.append(events.STREAM, {"machine": "review", "event": "OPENED", "task": "TASK-1", "time": 1})
    assert last is not None
    _passed(store, last)
    _stop(stop, thread)

    assert dagu.calls == ["criteria"]  # the machine event started it; the lane event before it did not


def test_a_trigger_starts_only_for_what_arrives_after_it_was_first_started(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    _move(log, "TASK-0", "done", 99.0)  # history the log retains is no reason to start a run
    dagu = _Dagu()
    thread = _run([_DONE], dagu, store, log, stop)

    last = _move(log, "TASK-1", "done", 100.0)
    _passed(store, last)
    _stop(stop, thread)

    assert dagu.calls == ["reconcile"]


def test_a_machine_event_is_filtered_by_its_fields(store: HistoryStore, log: EventLog, stop: threading.Event) -> None:
    dagu = _Dagu()
    trigger = Trigger("machine", "dagu/criteria", {"machine": {"equals": "in-progress"}, "task": {"exists": True}})
    thread = _run([trigger], dagu, store, log, stop)

    log.append(events.STREAM, {"machine": "review", "event": "OPENED", "task": "TASK-1", "time": 1})
    last = log.append(events.STREAM, {"machine": "in-progress", "event": "READY", "task": "TASK-1", "time": 2})
    assert last is not None
    _passed(store, last)
    _stop(stop, thread)

    assert dagu.calls == ["criteria"]


def test_a_start_the_adapter_refuses_is_dropped_and_the_next_event_still_starts(
    store: HistoryStore, log: EventLog, stop: threading.Event
) -> None:
    dagu = _Dagu(failing=True)
    thread = _run([_DONE], dagu, store, log, stop)

    _move(log, "TASK-1", "done", 100.0)
    last = _move(log, "TASK-2", "done", 101.0)
    _passed(store, last)
    _stop(stop, thread)

    assert dagu.calls == ["reconcile", "reconcile"]
