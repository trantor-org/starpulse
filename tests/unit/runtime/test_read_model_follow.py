"""`serve` keeps the Task read model folded and the page told of each Task that changed."""

import time
from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.runtime.read_model_follow import follow


class _Counts:
    def __init__(self, stop: StopEvent, log: EventLog, after: int, wakes: bool = True) -> None:
        self.stop, self.log, self.after, self.wakes, self.catch_ups, self.follows = stop, log, after, wakes, 0, 0

    def catch_up(self) -> int:
        self.catch_ups += 1
        return 0

    def follow_read_model(self) -> int:
        self.follows += 1
        if self.follows >= self.after:
            self.stop.set()
        elif self.wakes:
            self.log.publish("fold", {})  # the next pass is woken by this append, as a fold's own commit wakes one
        return 0


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def test_each_pass_folds_the_events_and_then_publishes_the_changed_tasks(log: EventLog) -> None:
    stop = StopEvent()
    both = _Counts(stop, log, after=3)

    thread = follow(both, both, stop, log)
    thread.join(5)

    assert not thread.is_alive()
    assert both.catch_ups == both.follows >= 3


def test_a_failed_pass_is_survived_and_the_next_one_runs(log: EventLog, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse.event_log.event_log.RETRY_DELAY", 0.01)
    stop = StopEvent()
    both = _Counts(stop, log, after=2)
    real, calls = both.catch_up, []

    def flaky() -> int:
        calls.append(time.monotonic())
        if len(calls) == 1:
            raise OSError("database is locked")
        return real()

    both.catch_up = flaky  # type: ignore[method-assign]

    follow(both, both, stop, log).join(5)

    assert both.follows >= 2


def test_an_idle_follower_waits_for_a_commit_and_a_stop_ends_it(log: EventLog) -> None:
    stop = StopEvent()
    both = _Counts(stop, log, after=99, wakes=False)

    thread = follow(both, both, stop, log)
    time.sleep(0.3)

    assert both.follows == 1  # no timer runs a second pass
    stop.set()
    thread.join(5)
    assert not thread.is_alive()
