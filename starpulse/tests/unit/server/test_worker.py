"""`starpulse worker pulls` runs the Delivery context alone, and keeps what `serve` draws in the event log."""

import threading
from pathlib import Path

import pytest

from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.pulls import delivery
from starpulse._internal.server import server, worker
from starpulse.tests import fake_board

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
CONFIG = f"delivery_worker = true\n[release]\n{BOARD}[board.actor]\n"
WAIT_S = 5.0


class Actor:
    made: list[Actor] = []

    def __init__(self, feed: object, *args: object, **kwargs: object) -> None:
        self.feed = feed
        self.started = False
        Actor.made.append(self)

    def start(self, stop: object) -> None:
        self.started = True

    def pulls_changed(self) -> None:
        pass

    def exposition(self) -> str:
        return "starpulse_task_actor_refusals_total 0\n"


class Sync:
    made: list[Sync] = []

    def __init__(self, *args: object, project: object = None, **kwargs: object) -> None:
        self.project = project
        self.ran = threading.Event()
        self.asked: list[tuple[str, int]] = []
        self.asked_event = threading.Event()
        Sync.made.append(self)

    def run_forever(self) -> None:
        self.ran.set()

    def request(self, repo: str, number: int) -> bool:
        self.asked.append((repo, number))
        self.asked_event.set()
        return True

    def tracked(self) -> list[str]:
        return ["acme/widgets"]


class Projection:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def refresh(self) -> None:
        pass


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`worker.main` on `text`, holding returns at once; yields the log the worker shares with `serve`."""
    monkeypatch.setattr(fake_board, "BUILT", [])
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(server, "TaskActor", Actor)
    monkeypatch.setattr(server, "PullSync", Sync)
    monkeypatch.setattr(server, "PullRequests", Projection)
    monkeypatch.setattr(Actor, "made", [])
    monkeypatch.setattr(Sync, "made", [])
    held: list[threading.Event] = []
    monkeypatch.setattr(worker, "hold", lambda stop, reload: held.append(stop))

    def start(text: str = CONFIG) -> EventLog:
        config = tmp_path / "starpulse.toml"
        config.write_text(text)
        worker.main(["pulls", "--config", str(config)])
        return EventLog(f"sqlite:///{(tmp_path / 'starpulse-history.sqlite').resolve()}")

    yield start
    for stop in held:
        stop.set()


def test_the_worker_starts_the_actor_and_the_pull_store_sync(run) -> None:
    run()

    assert [a.started for a in Actor.made] == [True]
    assert Sync.made[0].ran.wait(WAIT_S)


def test_each_projection_is_kept_in_the_log_for_serve(run) -> None:
    log = run()

    Sync.made[0].project()

    assert log.setting(delivery.PROJECTION) is not None


def test_a_refresh_serve_queued_reaches_the_pull_sync(run) -> None:
    log = run()

    delivery.request_refresh(log, Sync.made[0].tracked)("acme/widgets", 3)

    assert Sync.made[0].asked_event.wait(WAIT_S)
    assert Sync.made[0].asked == [("acme/widgets", 3)]


def _eventually(ready) -> bool:
    wait = threading.Event()
    for _ in range(100):
        if ready():
            return True
        wait.wait(0.05)
    return False


def test_the_actors_metrics_are_kept_in_the_log_for_serve(run) -> None:
    log = run()

    assert _eventually(delivery.metrics_of(log))
    assert delivery.metrics_of(log)() == "starpulse_task_actor_refusals_total 0\n"


def test_the_actors_notes_reach_serve_through_the_log(run) -> None:
    log = run()
    seen: list[str] = []

    class Serving:
        def note_actor(self, task: str, actor: str | None, session: str = "", harness: str = "") -> None:
            seen.append(task)

    delivery.follow_notes(log, Serving(), threading.Event())
    Actor.made[0].feed.note_actor("TASK-1", "task-actor")

    assert _eventually(lambda: seen)
    assert seen == ["TASK-1"]


def test_a_board_that_cannot_edit_refuses_the_actor(run) -> None:
    with pytest.raises(SystemExit):
        run(CONFIG.replace("writes = true\n", ""))


def _config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "starpulse.toml"
    path.write_text(text)
    return path


def test_a_reload_with_an_invalid_config_keeps_the_running_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    execs: list[object] = []
    monkeypatch.setattr(worker.os, "execv", lambda *args: execs.append(args))
    path = _config(tmp_path, "delivery_worker = true\n")
    running = load(path)
    path.write_text("delivery_worker = 3\n")

    worker.reload_config(path, running)

    assert execs == []


def test_a_reload_that_changes_no_delivery_block_does_not_restart_the_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execs: list[object] = []
    monkeypatch.setattr(worker.os, "execv", lambda *args: execs.append(args))
    path = _config(tmp_path, "delivery_worker = true\nslow_read_seconds = 1.0\n")
    running = load(path)
    path.write_text("delivery_worker = true\nslow_read_seconds = 2.0\n")

    worker.reload_config(path, running)

    assert execs == []


def test_a_reload_that_changes_a_delivery_block_restarts_the_loops_in_the_same_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execs: list[object] = []
    monkeypatch.setattr(worker.os, "execv", lambda *args: execs.append(args))
    path = _config(tmp_path, "delivery_worker = true\npull_requests = true\n")
    running = load(path)
    path.write_text("delivery_worker = true\npull_requests = false\n")

    worker.reload_config(path, running)

    assert len(execs) == 1
