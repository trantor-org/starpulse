"""The scheduler's seam with `serve`: the worker keeps its status and takes wakes in the event log, `serve` writes the
settings through `Remote` and draws the worker's status."""

from __future__ import annotations

import queue
import threading
from pathlib import Path

import pytest

from starpulse._internal.config.config import load
from starpulse.board.board_feed import BoardFeed
from starpulse.scheduler.adapters.remote import Remote, follow_status, follow_wakes, publisher
from starpulse._internal.server.server import scheduler_remote
from starpulse.event_log.event_log import EventLog
from starpulse.harness_telemetry.harness import SESSION_MACHINES
from starpulse.tests.machines import MACHINES, ROLES

DEADLINE_S = 5.0
STATUS = {
    "enabled": False,
    "harness": "claude",
    "quietHours": None,
    "sampledAt": 7.0,
    "dimensions": [{"name": "cpu", "use": 1.0, "limit": 4.0}],
    "inFlight": [],
}


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def test_remote_answers_a_minimal_status_before_the_worker_has_published_one(log: EventLog, tmp_path: Path) -> None:
    assert Remote(log, tmp_path).served_status() == {
        "enabled": False,
        "harness": "claude",
        "quietHours": None,
        "sampledAt": None,
        "dimensions": [],
    }


def test_remote_settings_take_effect_in_the_store_and_over_the_workers_last_status(
    log: EventLog, tmp_path: Path
) -> None:
    remote = Remote(log, tmp_path)
    publisher(log, BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES}))("scheduler", STATUS)

    remote.set_enabled(True)
    remote.set_harness("cursor")

    served = remote.served_status()
    assert (served["enabled"], served["harness"], served["dimensions"], served["inFlight"]) == (
        True,
        "cursor",
        STATUS["dimensions"],
        [],
    )


def test_remote_refuses_what_the_runtime_refuses(log: EventLog, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="harness"):
        Remote(log, tmp_path).set_harness("")


def test_a_change_through_remote_wakes_the_worker(log: EventLog, tmp_path: Path) -> None:
    woken = threading.Event()
    stop = threading.Event()
    follow_wakes(log, woken.set, stop)

    Remote(log, tmp_path).set_quiet_hours(None)

    assert woken.wait(DEADLINE_S)
    stop.set()


def test_the_workers_status_reaches_the_serving_feed_as_an_scheduler_event(log: EventLog) -> None:
    worker_feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    serving = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    stop = threading.Event()
    follow_status(log, serving, stop)
    _, changes = serving.subscribe()

    publisher(log, worker_feed)("scheduler", STATUS)

    kind, data = _next_scheduler(changes)
    assert (kind, data) == ("scheduler", STATUS)
    stop.set()


def _next_scheduler(changes: queue.Queue) -> tuple[str, dict]:
    while True:
        kind, data = changes.get(timeout=DEADLINE_S)
        if kind == "scheduler":
            return kind, data


def test_a_served_scheduler_leaves_no_status_thread_once_its_stop_is_set(log: EventLog, tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines={**MACHINES, **SESSION_MACHINES})
    stop = threading.Event()
    (tmp_path / "starpulse.toml").write_text("")
    scheduler_remote(load(tmp_path / "starpulse.toml"), tmp_path, feed, log, stop)
    followers = [t for t in threading.enumerate() if t.name == "scheduler-status"]
    assert followers

    stop.set()
    for thread in followers:
        thread.join(DEADLINE_S)

    assert not any(thread.is_alive() for thread in followers)
