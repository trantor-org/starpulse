"""`GET /metrics` counts, per machine, the recorded moves that no declared transition allows."""

import threading
import time
import urllib.request
from pathlib import Path

from starpulse._internal.eventlog import events as machine_events
from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.conformance_monitor import Conformance
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, url
from starpulse.tests.machines import MACHINES

BOARD = {
    "states": [
        {"id": "to_do", "initial": True, "final": False},
        {"id": "in_progress", "initial": False, "final": False},
        {"id": "done", "initial": False, "final": True},
    ],
    "transitions": [
        {"source": "to_do", "target": "in_progress", "event": "CLAIM"},
        {"source": "in_progress", "target": "done", "event": "FINISH"},
    ],
}
REVIEW = {
    "states": [
        {"id": "open", "initial": True, "final": False},
        {"id": "merged", "initial": False, "final": False},
        {"id": "closed", "initial": False, "final": True},
    ],
    "transitions": [
        {"source": "open", "target": "merged", "event": "MERGE"},
        {"source": "merged", "target": "closed", "event": "CLOSE"},
    ],
}
VIOLATIONS = "starpulse_machine_conformance_violations_total"
JUDGED = "starpulse_machine_conformance_events_total"


def _scrape(monitor: Conformance, tmp_path: Path) -> list[str]:
    with serve(tmp_path, BoardFeed(machines=MACHINES), conformance_metrics=monitor.exposition) as server:
        with urllib.request.urlopen(url(server, "/metrics"), timeout=5) as resp:
            return resp.read().decode().splitlines()


def _lane(log: EventLog, task: str, lane: str, at: float) -> None:
    lane_events.append(log, f"{task}@{lane}@{at}", task, lane, at)


def test_the_history_the_log_holds_is_counted_per_machine_before_the_first_scrape(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'ic.sqlite'}")
    for task, lane, at in (
        ("T-1", "to_do", 1.0),
        ("T-1", "in_progress", 2.0),
        ("T-1", "done", 3.0),
        ("T-2", "to_do", 4.0),
        ("T-2", "done", 5.0),
    ):
        _lane(log, task, lane, at)
    for task in ("T-1", "T-1", "T-3"):
        machine_events.publish("review", "MERGE", actor="a", task=task, log=log)
    monitor = Conformance({"board": BOARD, "review": REVIEW, "idle": REVIEW})
    stop = threading.Event()
    monitor.follow(log, stop)

    lines = _scrape(monitor, tmp_path)
    stop.set()

    assert [line for line in lines if line.startswith((VIOLATIONS, JUDGED))] == [
        f'{VIOLATIONS}{{machine="board"}} 1',
        f'{VIOLATIONS}{{machine="review"}} 1',
        f'{VIOLATIONS}{{machine="idle"}} 0',
        f'{JUDGED}{{machine="board"}} 3',
        f'{JUDGED}{{machine="review"}} 3',
        f'{JUDGED}{{machine="idle"}} 0',
    ]


def test_a_move_appended_after_the_scrape_started_is_counted_live(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'ic.sqlite'}")
    monitor = Conformance({"board": BOARD})
    stop = threading.Event()
    monitor.follow(log, stop)

    _lane(log, "T-9", "to_do", 1.0)
    _lane(log, "T-9", "done", 2.0)
    counted = f'{VIOLATIONS}{{machine="board"}} 1'
    deadline = time.monotonic() + 5
    while counted not in monitor.exposition() and time.monotonic() < deadline:
        stop.wait(0.05)
    stop.set()

    assert f'{VIOLATIONS}{{machine="board"}} 1' in _scrape(monitor, tmp_path)
