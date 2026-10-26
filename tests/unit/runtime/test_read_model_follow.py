"""`serve` keeps the Task read model folded and the page told of each Task that changed."""

import threading
import time

from starpulse.runtime.read_model_follow import follow


class _Counts:
    def __init__(self, stop: threading.Event, after: int) -> None:
        self.stop, self.after, self.catch_ups, self.follows = stop, after, 0, 0

    def catch_up(self) -> int:
        self.catch_ups += 1
        return 0

    def follow_read_model(self) -> int:
        self.follows += 1
        if self.follows >= self.after:
            self.stop.set()
        return 0


def test_each_pass_folds_the_events_and_then_publishes_the_changed_tasks() -> None:
    stop = threading.Event()
    both = _Counts(stop, after=3)

    thread = follow(both, both, stop, interval_s=0.01)
    thread.join(5)

    assert not thread.is_alive()
    assert both.catch_ups == both.follows >= 3


def test_a_failed_pass_is_survived_and_the_next_one_runs() -> None:
    stop = threading.Event()
    both = _Counts(stop, after=2)
    real, calls = both.catch_up, []

    def flaky() -> int:
        calls.append(time.monotonic())
        if len(calls) == 1:
            raise OSError("database is locked")
        return real()

    both.catch_up = flaky  # type: ignore[method-assign]

    follow(both, both, stop, interval_s=0.01).join(5)

    assert both.follows >= 2
