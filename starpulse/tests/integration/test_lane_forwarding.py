"""A Board lane change travels from an IC to a hub's level: BoardFeed, event log, Forwarder, hub ingest, hub history.

The IC and the hub are SQLite files; the forwarder's transport is the hub's real `ForwardIngest`, called in process.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starpulse.adapters.runs.ingest import ForwardIngest
from starpulse.api.forward import OPT_IN_FILE, Forwarder, OptIn
from starpulse.contracts import BoardTask
from starpulse.domain.level import Level, Orbit, Terminal
from starpulse.domain.level_metrics import level_metrics
from starpulse.projections.board_feed import BoardFeed
from starpulse.settings.config import Forward
from starpulse.store import lane_events
from starpulse.store.event_log import EventLog, Tail
from starpulse.store.history import HistoryStore
from starpulse.tests.machines import MACHINES

H = 3600.0
T0 = 1_000_000.0
TOKEN = "ana-secret"
LEVEL = Level(
    "board",
    "done",
    (Terminal("done", "goal"),),
    gates=("review",),
    orbit=Orbit("working", ("in_progress", "review")),
)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now


class Site:
    """An IC with a Board feed, its log and store, and a hub's log, store and ingest, joined by one forwarder."""

    def __init__(self, tmp_path: Path) -> None:
        self.clock = Clock()
        self.ic_url = f"sqlite:///{tmp_path / 'ic.sqlite'}"
        self.hub_url = f"sqlite:///{tmp_path / 'hub.sqlite'}"
        self.ic_log, self.ic_store = EventLog(self.ic_url), HistoryStore(self.ic_url, MACHINES)
        self.hub_log, self.hub_store = EventLog(self.hub_url), HistoryStore(self.hub_url, MACHINES)
        self.feed = BoardFeed(machines=MACHINES, clock=self.clock)
        self.feed.record_lanes(self.ic_store, self.ic_log)
        self.ingest = ForwardIngest({"ana": TOKEN}, self.hub_log)
        self.opt_in = OptIn(tmp_path / OPT_IN_FILE)
        self.bodies: list[dict[str, Any]] = []

    def move(self, task: str, lane: str, *, at: float, assignee: str = "") -> None:
        self.clock.now = T0 + at
        self.feed.put(BoardTask(id=task, team="demo", title=f"secret title of {task}", lane=lane, assignee=assignee))

    def send(self, _url: str, token: str, body: bytes) -> tuple[int, dict[str, Any]]:
        self.bodies.append(json.loads(body))
        return self.ingest(f"Bearer {token}", body)

    def forwarder(self, clock: Callable[[], float] = time.time) -> Forwarder:
        store = HistoryStore(self.ic_url, MACHINES)
        return Forwarder(
            self.ic_log, store, Forward("http://hub", "HUB", 50), TOKEN, self.opt_in, send=self.send, clock=clock
        )

    def drain(self, forwarder: Forwarder) -> None:
        while forwarder.step():
            pass

    def fold(self) -> None:
        """The hub's lane reader, one pass."""
        for entry in Tail(self.hub_log, lane_events.STREAM, after=self.hub_store.cursor(lane_events.STREAM)).poll():
            self.hub_store.record_lane_entry(entry.event_id, entry.fields, cursor=entry.id)

    def at(self, log: EventLog) -> list[str]:
        return [e.event_id for e in Tail(log, lane_events.STREAM).poll()]


def test_a_lane_change_the_board_applies_is_counted_in_the_hubs_wip_and_throughput(tmp_path: Path) -> None:
    site = Site(tmp_path)
    site.move("T-1", "to_do", at=0)
    site.move("T-1", "in_progress", at=1 * H)
    site.move("T-1", "done", at=30 * H)
    site.move("T-2", "to_do", at=0)
    site.move("T-2", "in_progress", at=2 * H)

    site.drain(site.forwarder())

    assert site.at(site.hub_log) == [f"ana/{event_id}" for event_id in site.at(site.ic_log)]
    assert len(site.at(site.hub_log)) == 5
    site.fold()
    runs = site.hub_store.level_runs("board")
    assert {(run.source, run.task) for run in runs} == {("ana", "T-1"), ("ana", "T-2")}
    answer = level_metrics(LEVEL, MACHINES["board"], runs, now=T0 + 48 * H, window_s=24 * H)
    assert answer["wip"] == {"count": 1, "states": {"in_progress": 1}}  # T-2, in progress since 2h
    assert answer["throughput"]["count"] == 1  # T-1 reached done at 30h, inside the last 24h


def test_a_lane_entry_leaves_without_assignee_until_opt_in_and_never_carries_a_title(tmp_path: Path) -> None:
    site = Site(tmp_path)
    site.move("T-1", "in_progress", at=0, assignee="bob-the-assignee")
    forwarder = site.forwarder()

    site.drain(forwarder)

    sent = site.bodies[0]["events"][0]
    assert sent["stream"] == lane_events.STREAM
    assert sent["fields"] == {"task": "T-1", "lane": "in_progress", "time": T0, "team": "demo"}
    [stored] = Tail(site.hub_log, lane_events.STREAM).poll()
    assert "assignee" not in stored.fields

    site.opt_in.set(True)
    site.move("T-1", "review", at=H, assignee="bob-the-assignee")
    site.drain(forwarder)

    named = site.bodies[-1]["events"][0]["fields"]
    assert named["assignee"] == "bob-the-assignee"
    assert all("assignee" not in e["fields"] for body in site.bodies[:-1] for e in body["events"])
    assert all("secret title" not in json.dumps(body) for body in site.bodies)
    assert all("secret title" not in json.dumps(e.fields) for e in Tail(site.hub_log, lane_events.STREAM).poll())


def test_the_start_snapshot_gives_the_hub_a_tasks_lane_with_no_move_after_forwarding_began(tmp_path: Path) -> None:
    site = Site(tmp_path)
    site.ic_store.record_lane("T-1@in_progress@1000100.0", "T-1", "in_progress", T0 + 100)  # moved before any lane log
    site.ic_store.record_lane("T-2@to_do@1000050.0", "T-2", "to_do", T0 + 50)
    site.ic_store.record_lane("T-2@review@1000200.0", "T-2", "review", T0 + 200)
    assert site.at(site.ic_log) == []

    site.drain(site.forwarder())
    site.fold()

    held = {(task, status) for task, _, _, status in site.hub_store.lane_rows()}
    assert held == {("T-1", "in_progress"), ("T-2", "review")}  # each task's current lane, no more
    assert {run.task: run.steps[-1][1] for run in site.hub_store.level_runs("board")} == {
        "T-1": "in_progress",
        "T-2": "review",
    }


def test_a_repeated_snapshot_adds_no_lane_change_row(tmp_path: Path) -> None:
    site = Site(tmp_path)
    site.ic_store.record_lane("T-1@in_progress@1000100.0", "T-1", "in_progress", T0 + 100)
    clock = Clock()
    forwarder = site.forwarder(clock)
    site.drain(forwarder)
    site.fold()
    first = site.hub_store.lane_rows()
    sent = len(site.bodies)

    site.drain(forwarder)  # the same day: no second snapshot
    assert len(site.bodies) == sent

    clock.now += 25 * H  # a day on: the snapshot goes again, from the same forwarder and from a restarted one
    site.drain(forwarder)
    site.drain(site.forwarder(clock))
    site.fold()

    assert len(site.bodies) == sent + 2
    assert site.hub_store.lane_rows() == first
    assert len(site.at(site.hub_log)) == 1


def test_a_replay_puts_the_stored_lane_changes_in_the_log_once_and_adds_no_row_at_the_hub(tmp_path: Path) -> None:
    site = Site(tmp_path)
    site.ic_store.record_lane("T-1@to_do@1000000.0", "T-1", "to_do", T0)
    site.ic_store.record_lane("T-1@in_progress@1000100.0", "T-1", "in_progress", T0 + 100)

    assert lane_events.replay(site.ic_store, site.ic_log) == 2
    assert lane_events.replay(site.ic_store, site.ic_log) == 0  # once

    assert site.at(site.ic_log) == ["T-1@to_do@1000000.0", "T-1@in_progress@1000100.0"]
    site.drain(site.forwarder())
    site.fold()
    assert [(task, old, new) for task, _, old, new in site.hub_store.lane_rows()] == [
        ("T-1", None, "to_do"),
        ("T-1", "to_do", "in_progress"),
    ]
    site.hub_store.record_lane_entry("ana/T-1@in_progress@1000100.0", {"task": "T-1", "lane": "in_progress", "time": T0 + 100})
    assert len(site.hub_store.lane_rows()) == 2


def test_lane_forwarding_continues_after_a_restart_when_a_restored_task_drops_a_dependency(tmp_path: Path) -> None:
    site = Site(tmp_path)
    before = BoardFeed(machines=MACHINES, clock=site.clock)
    before.put(BoardTask(id="T-1", team="demo", title="t", lane="in_progress", dependencies=("T-0",)))
    before.seen("7-0")
    before.resume(site.ic_log, "board:tasks", lambda cursor: False)
    before.save()
    site.feed = BoardFeed(machines=MACHINES, clock=site.clock)
    assert site.feed.resume(site.ic_log, "board:tasks", lambda cursor: True) == "7-0"
    site.feed.record_lanes(site.ic_store, site.ic_log)

    site.move("T-1", "review", at=H)  # the move that dropped T-0 from T-1's dependencies
    site.move("T-2", "in_progress", at=2 * H)
    site.drain(site.forwarder())
    site.fold()

    held = {(task, status) for task, _, _, status in site.hub_store.lane_rows()}
    assert held == {("T-1", "review"), ("T-2", "in_progress")}
