"""What wakes an event-log reader: an append here, a file watch on the store for a commit elsewhere, and the stop
event; none of them a timer."""

import logging
import threading
from pathlib import Path

import pytest
from starpulse.event_log import event_log as event_log_module
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import FALLBACK_WAKE_S, StopEvent
from starpulse.sweeper.config import Sweeper


def _url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'events.sqlite'}"


def _wait_in_thread(log: EventLog, seen: int, stop: StopEvent) -> threading.Thread:
    waiter = threading.Thread(target=log.wait_for_append, args=(seen, stop), daemon=True)
    waiter.start()
    return waiter


def test_the_fallback_wake_is_the_sweepers_default_interval() -> None:
    assert FALLBACK_WAKE_S == Sweeper().interval_s


def test_setting_the_stop_event_ends_a_wait_with_no_timeout(tmp_path: Path) -> None:
    log = EventLog(_url(tmp_path))
    stop = StopEvent()
    waiter = _wait_in_thread(log, log.appends, stop)

    stop.set()
    waiter.join(timeout=2)

    assert not waiter.is_alive()


def test_a_stop_set_before_the_wait_ends_it_at_once(tmp_path: Path) -> None:
    log = EventLog(_url(tmp_path))
    stop = StopEvent()
    stop.set()

    log.wait_for_append(log.appends, stop)


def test_a_commit_by_another_connection_ends_a_wait_with_no_timeout(tmp_path: Path) -> None:
    log, other = EventLog(_url(tmp_path)), EventLog(_url(tmp_path))
    log.engine
    stop = StopEvent()
    seen = log.appends
    waiter = _wait_in_thread(log, seen, stop)

    other.publish("a", {"n": "elsewhere"})
    waiter.join(timeout=5)
    stop.set()

    assert not waiter.is_alive()
    assert log.appends != seen


def test_without_a_file_watch_a_commit_elsewhere_wakes_at_the_fallback_interval_and_the_log_says_so_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(event_log_module, "open_watch", lambda database: None)
    monkeypatch.setattr(event_log_module, "_NO_WATCH_LOGGED", threading.Event())
    log, other = EventLog(_url(tmp_path), fallback_interval=0.2), EventLog(_url(tmp_path))
    log.engine
    stop = StopEvent()
    with caplog.at_level(logging.WARNING, logger="starpulse.event_log.event_log"):
        seen = log.appends
        other.publish("a", {"n": "elsewhere"})
        waiter = _wait_in_thread(log, seen, stop)
        waiter.join(timeout=5)
        stop.set()
        second = EventLog(_url(tmp_path), fallback_interval=0.2)
        second.appends

    assert not waiter.is_alive()
    assert len([r for r in caplog.records if "no file watch" in r.getMessage()]) == 1


def test_a_log_dropped_by_its_owner_ends_the_commit_watch_it_started(tmp_path: Path) -> None:
    import gc

    before = set(threading.enumerate())
    log = EventLog(_url(tmp_path))
    log.appends  # starts the commit watch

    watches = [t for t in threading.enumerate() if t not in before and t.name == "eventlog-commit-watch"]
    assert watches

    del log
    gc.collect()
    for started in watches:
        started.join(timeout=2)

    assert not any(started.is_alive() for started in watches)


def test_run_on_wake_runs_its_step_again_on_a_commit_by_another_process_and_ends_on_stop(tmp_path: Path) -> None:
    log, other = EventLog(_url(tmp_path)), EventLog(_url(tmp_path))
    stop, passes, second = StopEvent(), [], threading.Event()

    def step() -> None:
        passes.append(1)
        if len(passes) == 2:
            second.set()

    thread = threading.Thread(target=log.run_on_wake, args=(stop, step, "failed"), daemon=True)
    thread.start()
    other.publish("a", {"n": "elsewhere"})

    assert second.wait(timeout=5)
    stop.set()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_run_on_wake_logs_a_failing_step_and_runs_it_again_after_the_retry_delay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(event_log_module, "RETRY_DELAY", 0.01)
    log, stop, calls = EventLog(_url(tmp_path)), StopEvent(), []

    def step() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("locked")
        stop.set()

    with caplog.at_level(logging.ERROR, logger="starpulse.event_log.event_log"):
        log.run_on_wake(stop, step, "the pass failed")

    assert len(calls) == 2
    assert [r.getMessage() for r in caplog.records] == ["the pass failed"]
