"""The sweeper's lease row: one holder at a time, taken over only from a holder whose process is gone."""

from __future__ import annotations

from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog
from starpulse.sweeper.lease import LeaseHeld, acquire


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'log.sqlite'}")


def test_a_second_holder_is_refused_and_the_refusal_names_the_first(log: EventLog) -> None:
    first = acquire(log.engine, "sweeper", pid=4242, alive=lambda pid: True)

    with pytest.raises(LeaseHeld, match="pid 4242"):
        acquire(log.engine, "sweeper", pid=4343, alive=lambda pid: True)

    first.release()


def test_a_released_lease_can_be_taken_again(log: EventLog) -> None:
    acquire(log.engine, "sweeper", pid=1, alive=lambda pid: True).release()

    acquire(log.engine, "sweeper", pid=2, alive=lambda pid: True).release()


def test_a_lease_whose_holder_process_is_gone_is_taken_over(log: EventLog) -> None:
    acquire(log.engine, "sweeper", pid=1, alive=lambda pid: True)

    taken = acquire(log.engine, "sweeper", pid=2, alive=lambda pid: pid != 1)

    taken.release()


def test_releasing_a_lease_another_holder_took_over_leaves_theirs(log: EventLog) -> None:
    stale = acquire(log.engine, "sweeper", pid=1, alive=lambda pid: True)
    acquire(log.engine, "sweeper", pid=2, alive=lambda pid: pid != 1)

    stale.release()

    with pytest.raises(LeaseHeld, match="pid 2"):
        acquire(log.engine, "sweeper", pid=3, alive=lambda pid: True)
