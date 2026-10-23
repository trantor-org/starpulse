"""A claim not renewed within the claim TTL is released: StarPulse appends Released and the Task returns to its resting
State, and the release names the last renewal (D6)."""

from functools import partial
from pathlib import Path

import pytest

from starpulse._internal.board.claim_ttl import sweep
from starpulse._internal.board.seam import Board
from starpulse._internal.board.upstream_backlog import UpstreamBacklog
from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.history import HistoryStore, last_run_event
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.server.assembly import assemble
from starpulse._internal.store import EventStore, NewEvent

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


def _renew(store: EventStore, at: float) -> None:
    head = store.head("task", "task-5")
    store.append("task", "task-5", head, [NewEvent("CommentAdded", {"text": "progress"}, "session-1", "test")], at=at)


def test_a_claim_releases_at_the_ttl_not_before(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 1799) == []
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 1801) == ["task-5"]

    types = [event.type for event in store.read("task", "task-5")]
    assert {"Released", "Transitioned"} <= set(types)
    assert built.read("task-5")["status"] == "To Do"


def test_an_event_by_the_assignee_renews_the_claim(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    _renew(store, claimed + 1000)

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 2500) == []
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 2801) == ["task-5"]


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
