"""Worker state: what a worker keeps for others to read carries a version that rises on every write, so readers poll it."""

import threading
import time
from pathlib import Path

import pytest
from starpulse.event_log.event_log import EventLog


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def test_state_is_unkept_then_replaced_with_a_rising_version_and_deleted(log: EventLog) -> None:
    assert log.state("beat") == (0, None)

    log.put_state("beat", {"at": 1})
    log.put_state("beat", {"at": 2})
    assert log.state("beat") == (2, {"at": 2})

    log.delete_state("beat")
    assert log.state("beat") == (0, None)


def test_an_entry_is_merged_without_dropping_the_others(log: EventLog) -> None:
    log.put_state_entry("report", "dagu", {"dags": []})
    log.put_state_entry("report", "pushed", {"dags": [1]})
    log.put_state_entry("report", "dagu", {"dags": [2]})

    assert log.state("report") == (3, {"dagu": {"dags": [2]}, "pushed": {"dags": [1]}})


def test_following_applies_each_write_after_the_call_and_not_the_state_already_kept(log: EventLog) -> None:
    log.put_state("status", {"n": 0})
    applied = threading.Event()
    stop = threading.Event()
    calls: list[int] = []

    def apply() -> None:
        calls.append(log.state("status")[0])
        applied.set()

    thread = log.follow_state("status", apply, stop, interval=0.05, thread_name="test-follow")
    time.sleep(0.2)
    assert calls == []

    log.put_state("status", {"n": 1})
    assert applied.wait(5)
    stop.set()
    thread.join(5)
    assert calls == [2]
