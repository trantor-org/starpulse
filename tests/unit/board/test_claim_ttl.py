"""A claim not renewed within the claim TTL is released: StarPulse appends Released, the Task keeps its State and may be
claimed by another session, and the release names the last renewal (D6)."""

import json
import os
import threading
import time
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
from starpulse.board.adapters import claim_ttl
from starpulse.board.adapters.claim_ttl import live_session, sweep, transcript_halt
from starpulse.board.adapters.running_workflows import running_tasks
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import last_run_event
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.runtime.assembly import assemble
from starpulse.runtime.config import load

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

    assert [e.type for e in store.read("task", "task-5") if "ttl" in e.payload].count("Released") == 1


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


def test_a_harness_event_of_the_held_task_with_no_run_renews_the_claim(served) -> None:
    """A session on a task branch writes harness telemetry keyed by the task, with no run."""
    built, _, store, log = served
    claimed = _claim(built, store)
    history = HistoryStore("", {}, engine=log.engine)
    fields = {"task": "task-5", "machine": "harness", "event": "TOOL_USED", "time": claimed + 1700}
    history.record_machine("harness-2", fields)
    activity = partial(last_run_event, log.engine)

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 3400, activity=activity) == []
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 3501, activity=activity) == ["task-5"]


HALT = "Autocompact is thrashing: the context refilled to the limit within 3 turns of the previous compact."


def _transcript(root: Path, *entries: dict) -> None:
    """Writes session-1's Claude Code transcript under a project directory of `root`, one JSON line per entry."""
    project = root / "-home-agent-repo"
    project.mkdir(parents=True, exist_ok=True)
    (project / "session-1.jsonl").write_text("".join(json.dumps(entry) + "\n" for entry in entries))


def _turn(kind: str, at: float, text: str, *, halt: bool = False) -> dict:
    stamp = datetime.fromtimestamp(at, UTC).isoformat().replace("+00:00", "Z")
    message = {"role": kind, "model": "<synthetic>" if halt else "claude-opus-5-5", "content": [{"type": "text", "text": text}]}
    return {"type": kind, "timestamp": stamp, "isApiErrorMessage": halt, "message": message}


def test_a_claim_whose_transcript_ends_in_a_terminal_halt_releases_before_the_ttl(served, tmp_path: Path) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    _transcript(tmp_path / "projects", _turn("user", claimed + 5, "go"), _turn("assistant", claimed + 10, HALT, halt=True), {"type": "cost-state"})
    halted = partial(transcript_halt, tmp_path / "projects")

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 60, halted=halted) == ["task-5"]
    assert "terminal halt" in store.read("task", "task-5")[-1].payload["text"]
    assert "Autocompact is thrashing" in store.read("task", "task-5")[-1].payload["text"]


def test_a_claim_whose_transcript_ends_in_an_ordinary_turn_is_kept(served, tmp_path: Path) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    _transcript(tmp_path / "projects", _turn("user", claimed + 5, "go"), _turn("assistant", claimed + 10, "Done."))
    halted = partial(transcript_halt, tmp_path / "projects")

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 60, halted=halted) == []


def test_a_halted_session_with_activity_after_its_halt_keeps_its_claim(served, tmp_path: Path) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    _transcript(tmp_path / "projects", _turn("assistant", claimed + 10, HALT, halt=True))
    _renew(store, claimed + 30)
    halted = partial(transcript_halt, tmp_path / "projects")

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 60, halted=halted) == []


def test_a_halt_before_the_bounded_transcript_tail_is_not_read(served, tmp_path: Path) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    padding = [{"type": "cost-state", "pad": "x" * 1000}] * 100
    _transcript(tmp_path / "projects", _turn("assistant", claimed + 10, HALT, halt=True), *padding)
    halted = partial(transcript_halt, tmp_path / "projects", tail=4096)

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 60, halted=halted) == []


def test_a_released_claim_fires_the_boards_released_notice_for_its_task(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    noticed: list[str] = []

    assert sweep(replace(built, released=noticed.append), store, _rows(built), ttl=1800, now=claimed + 1801) == ["task-5"]

    assert noticed == ["task-5"]


def test_a_failing_released_notice_leaves_the_release_standing(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)

    def refuse(_task: str) -> None:
        raise ValueError("no start")

    assert sweep(replace(built, released=refuse), store, _rows(built), ttl=1800, now=claimed + 1801) == ["task-5"]


def test_a_task_with_a_running_workflow_keeps_its_claim_past_the_ttl_and_loses_it_once_the_workflow_ends(served) -> None:
    """A lifecycle workflow waiting on CI emits nothing for its task, yet its session is alive."""
    built, _, store, _ = served
    claimed = _claim(built, store)

    seen = {"task-5": claimed + 5000}  # the workflow was last seen running 83 minutes into the claim

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 5000, seen_running=seen) == []
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 6799, seen_running=seen) == []
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 6800, seen_running=seen) == ["task-5"]


def test_a_claim_whose_session_is_alive_is_kept_past_the_ttl_and_lost_once_the_session_ends(served) -> None:
    """A session that ended its turn on a background CI watch emits nothing, yet its process is alive."""
    built, _, store, _ = served
    claimed = _claim(built, store)
    alive = {"session-1"}

    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 5000, alive=lambda s: s in alive) == []
    alive.clear()
    assert sweep(built, store, _rows(built), ttl=1800, now=claimed + 5000, alive=lambda s: s in alive) == ["task-5"]


def test_a_kept_claim_serves_a_claim_expiry_of_now_plus_the_ttl(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    expiries: dict[str, float] = {}

    sweep(built, store, _rows(built), ttl=1800, now=claimed + 5000, alive=lambda _s: True, expiries=expiries)

    assert expiries == {"task-5": claimed + 5000 + 1800}


def _register(root: Path, pid: int, session: str, *, proc_start: str | None = None, bridge: str = "") -> None:
    """A Claude Code session registry entry, `<root>/<pid>.json`, for the process `pid`."""
    if proc_start is None:
        proc_start = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    entry = {"pid": pid, "sessionId": session, "bridgeSessionId": bridge, "procStart": proc_start}
    (root / f"{pid}.json").write_text(json.dumps(entry))


def test_live_session_is_true_for_a_registered_session_or_bridge_id_whose_process_runs(tmp_path: Path) -> None:
    _register(tmp_path, os.getpid(), "uuid-1", bridge="session_abc")

    assert live_session(tmp_path, "uuid-1")
    assert live_session(tmp_path, "session_abc")
    assert not live_session(tmp_path, "uuid-2")
    assert not live_session(tmp_path, "")


def test_live_session_is_false_for_a_process_that_ended_or_whose_pid_was_reused(tmp_path: Path) -> None:
    _register(tmp_path, 2**22 + 7, "gone", proc_start="1")
    _register(tmp_path, os.getpid(), "reused", proc_start="1")

    assert not live_session(tmp_path, "gone")
    assert not live_session(tmp_path, "reused")


def test_live_session_ignores_a_missing_registry_and_unreadable_entries(tmp_path: Path) -> None:
    (tmp_path / "1.json").write_text("{not json")

    assert not live_session(tmp_path, "uuid-1")
    assert not live_session(tmp_path / "absent", "uuid-1")


def test_running_tasks_names_each_task_of_a_running_workflow_across_pages() -> None:
    pages = {
        "": {"executions": [{"execution": {"workflowId": "task-lifecycle/TASK-9902"}}], "nextPageToken": "next"},
        "next": {"executions": [{"execution": {"workflowId": "task-lifecycle/TASK-9013"}}]},
    }

    def get(url: str) -> dict:
        assert "query=ExecutionStatus%3D%22Running%22" in url
        return pages["next" if "nextPageToken=next" in url else ""]

    assert running_tasks("http://temporal:8233/", get=get) == {"task-9902", "task-9013"}


def test_a_sweep_pass_that_cannot_read_temporal_releases_nothing(served, monkeypatch) -> None:
    built, feed, store, log = served
    claimed = _claim(built, store)
    passes = []
    monkeypatch.setattr(BoardFeed, "spawn", lambda self, target, name: passes.append(target))
    monkeypatch.setattr(claim_ttl, "running_tasks", lambda *_args: (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setattr(claim_ttl.time, "time", lambda: claimed + 99999)
    saved: list[dict] = []

    claim_ttl.start(built, feed, log, {"workflows": "http://temporal:8233"}, persist=saved.append)
    waits = iter([False, True])
    passes[-1](SimpleNamespace(wait=lambda _timeout: next(waits)))

    assert saved == []
    assert [event for event in store.read("task", "task-5") if event.type == "Released"] == []


def _released(built: Board, store: EventStore, claimed: float) -> float:
    released_at = claimed + 1801
    assert sweep(built, store, _rows(built), ttl=1800, now=released_at) == ["task-5"]
    return released_at


def _unheld() -> list[dict]:
    return [{"id": "task-5", "state": "In Progress", "assignee": ""}]


def test_a_session_whose_claim_was_released_holds_the_task_again_once_it_acts(served) -> None:
    built, _, store, _ = served
    released_at = _released(built, store, _claim(built, store))
    resumed = released_at + 30

    assert sweep(built, store, _unheld(), ttl=1800, now=resumed + 1, activity=lambda _s, _t: resumed) == []

    last = store.read("task", "task-5")[-1]
    assert (last.type, last.payload["assignee"]) == ("Claimed", "session-1")


def test_a_released_claim_whose_session_has_not_acted_since_stays_released(served) -> None:
    built, _, store, _ = served
    claimed = _claim(built, store)
    released_at = _released(built, store, claimed)
    head = store.head("task", "task-5")

    sweep(built, store, _unheld(), ttl=1800, now=released_at + 60, activity=lambda _s, _t: released_at - 1)

    assert store.head("task", "task-5") == head


def test_a_released_claim_is_not_taken_back_from_the_session_that_holds_the_task(served) -> None:
    built, _, store, _ = served
    released_at = _released(built, store, _claim(built, store))
    held = [{"id": "task-5", "state": "In Progress", "assignee": "session-2"}]
    head = store.head("task", "task-5")

    sweep(built, store, held, ttl=1800, now=released_at + 60, activity=lambda _s, _t: released_at + 30)

    assert store.head("task", "task-5") == head
