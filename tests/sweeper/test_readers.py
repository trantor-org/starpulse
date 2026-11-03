"""The `readers` kind: a log reader with entries waiting and no progress since the last pass is woken and counted."""

from __future__ import annotations

from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.sweeper.readers import Readers


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'log.sqlite'}")


class _Wakes:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> None:
        self.count += 1


def test_a_reader_with_entries_waiting_and_no_progress_since_the_last_pass_is_woken_and_counted(log: EventLog) -> None:
    log.publish("machine:events", {"n": 1})
    log.checkpoints.save("machine:events", 0)
    woken = _Wakes()
    readers = Readers(log, wake=woken)

    first = readers.run()
    second = readers.run()

    assert (first.corrected, first.sampled) == (0, 1)
    assert (second.corrected, second.sampled) == (1, 1)
    assert woken.count == 1


def test_a_reader_that_moved_since_the_last_pass_is_not_counted(log: EventLog) -> None:
    first_id = log.publish("machine:events", {"n": 1})
    log.publish("machine:events", {"n": 2})
    log.checkpoints.save("machine:events", 0)
    woken = _Wakes()
    readers = Readers(log, wake=woken)
    readers.run()
    log.checkpoints.save("machine:events", first_id)

    outcome = readers.run()

    assert outcome.corrected == 0
    assert woken.count == 0


def test_a_reader_that_is_caught_up_is_sampled_and_never_counted(log: EventLog) -> None:
    head = log.publish("machine:events", {"n": 1})
    log.checkpoints.save("machine:events", head)
    readers = Readers(log, wake=_Wakes())
    readers.run()

    outcome = readers.run()

    assert (outcome.corrected, outcome.sampled) == (0, 1)


def test_a_checkpoint_that_is_no_stream_of_the_log_is_not_sampled(log: EventLog) -> None:
    log.publish("machine:events", {"n": 1})
    log.checkpoints.save("read-model:tasks", 0)

    assert Readers(log, wake=_Wakes()).run().sampled == 0
