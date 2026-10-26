"""A claim not renewed within the claim TTL is released: StarPulse appends Released, the Task keeps its State and may be
claimed by another session, and the release names the last renewal (D6)."""

import threading
import time
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

from starpulse.runtime.config import load
from starpulse.board.adapters import claim_ttl
from starpulse.board.adapters.claim_ttl import sweep
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import last_run_event
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.flow_metrics.history import HistoryStore
from starpulse.runtime.assembly import assemble

FILE = """---
id: task-5
title: Draw the board
status: To Do
labels:
  - ui
priority: high
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Draw it.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 It draws
- [ ] #2 It scrolls
<!-- AC:END -->
"""


@pytest.fixture
def served(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Board, BoardFeed, EventStore, EventLog]:
    """The default native board holding `task-5` written before any History, started over an event log."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    built, feed = assemble(load(None), tmp_path, None, ())
    (tmp_path / ".starpulse" / "board" / "tasks" / "task-5 - Draw.md").write_text(FILE)
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    built.start(feed, "test", log)
    return built, feed, EventStore(log.engine), log


def _claim(built: Board, store: EventStore) -> float:
    assert built.writer("task-5", "In Progress", "agent", "session-1").ok
    return store.read("task", "task-5")[-1].at


def _rows(built: Board) -> list[dict]:
    return [{"id": "task-5", "state": "In Progress", "assignee": "session-1"}]


def _scanned(base: Path, feed: BoardFeed) -> list[dict]:
    """The feed's open tasks once the poller has read the task files again."""
    UpstreamBacklog(base / ".starpulse" / "board", feed.put).scan()
    return feed.open_tasks()


def _renew(store: EventStore, at: float) -> None:
    head = store.head("task", "task-5")
    store.append("task", "task-5", head, [NewEvent("CommentAdded", {"text": "progress"}, "session-1", "test")], at=at)


def test_a_claim_releases_at_the_ttl_not_before(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 1799) == []
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 1801) == ["task-5"]

    types = [event.type for event in store.read("task", "task-5")]
    assert "Released" in types
    assert built.read("task-5")["status"] == "In Progress"


def test_an_event_by_the_assignee_renews_the_claim(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    _renew(store, claimed + 1000)

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 2500) == []
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 2801) == ["task-5"]


def test_a_held_task_serves_renewal_plus_ttl_as_its_claim_expiry(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    _renew(store, claimed + 1000)
    expiries: dict[str, float] = {}

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 2500, expiries=expiries) == []
    assert expiries == {"task-5": claimed + 1000 + 1800}


def test_an_unheld_task_serves_no_claim_expiry(served) -> None:
    built, _, store, _ = served
    _claim(built, store)
    rows = [{"id": "task-5", "state": "In Progress", "assignee": ""}]
    expiries: dict[str, float] = {}

    sweep(built, store, rows, ttl=1800, now=time.time(), expiries=expiries)

    assert expiries.get("task-5") is None


def test_a_task_released_on_the_pass_serves_no_claim_expiry(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    expiries: dict[str, float] = {}

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 1801, expiries=expiries) == ["task-5"]
    assert expiries.get("task-5") is None


def test_the_feed_serves_the_latest_pass_expiry_on_the_task(served, tmp_path: Path) -> None:
    built, feed, store, _ = served
    claimed = _claim(built, store)
    _scanned(tmp_path, feed)
    feed.serve_expiries({"task-5": claimed + 1800})

    task = next(row for row in _scanned(tmp_path, feed) if row["id"] == "task-5")
    assert task["claim_expires_at"] == claimed + 1800


def test_the_release_names_the_last_renewal_of_a_silent_session(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    _renew(store, claimed + 600)

    sweep(built, store, _rows(built), ttl=1800, now=claimed + 5000)

    note = store.read("task", "task-5")[-1]
    assert note.type == "CommentAdded"
    assert "session-1" in note.payload["text"]
    assert str(int(claimed + 600)) in note.payload["text"] or "last renewal" in note.payload["text"]


def test_a_harness_event_of_the_assignee_session_renews_the_claim(served) -> None:
    """A session working in its own worktree writes no task Event, only harness telemetry keyed by its session id."""
    built, _, store, log = served
    claimed = _claim(built, store)
    history = HistoryStore("", {}, engine=log.engine)
    fields = {"run": "session-1", "machine": "harness", "event": "TOOL_USED", "time": claimed + 1700}
    history.record_machine("harness-1", fields)
    activity = partial(last_run_event, log.engine)

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 3400, activity=activity) == []
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 3501, activity=activity) == ["task-5"]


def test_an_expired_claim_keeps_the_state_and_frees_the_task_for_another_session(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 1801) == ["task-5"]

    assert built.read("task-5")["status"] == "In Progress"
    assert [event.type for event in store.read("task", "task-5")].count("Transitioned") == 1
    assert built.writer("task-5", "In Progress", "agent", "session-2").ok


def test_a_stale_row_never_moves_a_task_the_board_moved_on(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    assert built.writer("task-5", "Done", "agent").ok

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 1801) == []

    assert built.read("task-5")["status"] == "Done"
    assert "Released" not in [event.type for event in store.read("task", "task-5")]


def test_a_stale_row_never_releases_a_claim_twice(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 1801) == ["task-5"]

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 3700) == []

    assert [event.type for event in store.read("task", "task-5")].count("Released") == 1


def test_the_feed_rows_show_a_task_the_board_moved_on_and_nothing_is_released(served, tmp_path: Path) -> None:
    built, feed, store, _ = served
    claimed = _claim(built, store)
    assert built.writer("task-5", "Done", "agent").ok

    assert sweep(built, store, _scanned(tmp_path, feed), ttl=1800, now=claimed + 1801) == []

    assert built.read("task-5")["status"] == "Done"


def test_the_feed_rows_carry_a_live_claim_the_sweep_releases(served, tmp_path: Path) -> None:
    built, feed, store, _ = served
    claimed = _claim(built, store)

    assert sweep(built, store, _scanned(tmp_path, feed), ttl=1800, now=claimed + 1801) == ["task-5"]


def test_the_running_sweeper_judges_the_feed_when_no_read_model_folds(served, tmp_path: Path) -> None:
    """With `read_model = false` nothing folds the read model, so a sweeper reading it would never see this claim."""
    built, feed, store, log = served
    _claim(built, store)
    _scanned(tmp_path, feed)

    claim_ttl.start(built, feed, log, {"claim_ttl": 0.3})
    deadline = time.monotonic() + 5
    while "Released" not in [event.type for event in store.read("task", "task-5")] and time.monotonic() < deadline:
        time.sleep(0.05)

    assert "Released" in [event.type for event in store.read("task", "task-5")]


def test_serve_follows_the_claim_expiry_the_sweep_pass_saved(served, tmp_path: Path) -> None:
    built, feed, store, _ = served
    claimed = _claim(built, store)
    expiries: dict[str, float] = {}
    assert sweep(built, store, _scanned(tmp_path, feed), ttl=1800, now=claimed + 1, expiries=expiries) == []
    history = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", {})
    history.save_claim_expiries(expiries)
    stopped = threading.Event()
    stopped.set()  # one pass, then it ends

    feed.follow_expiries(history, stopped)

    assert feed.task("task-5")["claim_expires_at"] == claimed + 1800


def test_the_board_sweep_saves_its_pass_expiry_that_serve_follows(served, tmp_path: Path, monkeypatch) -> None:
    built, feed, store, log = served
    claimed = _claim(built, store)
    _scanned(tmp_path, feed)
    history = HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", {})
    passes = []
    monkeypatch.setattr(BoardFeed, "spawn", lambda self, target, name: passes.append(target))

    built.sweep(feed, log, history.save_claim_expiries)  # the board worker's call
    waits = iter([False, True])  # one pass, then the sweeper stops
    passes[-1](SimpleNamespace(wait=lambda _timeout: next(waits)))

    assert history.claim_expiries() == {"task-5": claimed + 1800}
    stopped = threading.Event()
    stopped.set()
    feed.follow_expiries(history, stopped)
    assert feed.task("task-5")["claim_expires_at"] == claimed + 1800


def test_stopping_the_feed_ends_the_running_sweeper(served) -> None:
    built, feed, _store, log = served
    before = set(threading.enumerate())
    claim_ttl.start(built, feed, log, {"claim_ttl": 0.3})
    sweeper = next(thread for thread in threading.enumerate() if thread.name == "claim-ttl" and thread not in before)

    feed.stop()

    sweeper.join(5)
    assert not sweeper.is_alive()
