"""`starpulse worker pulls` runs the Delivery context alone, and keeps what `serve` draws in the event log."""

import os
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


class Loops:
    """`worker.start_delivery` stood in: records each build's config and stop event."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.built: list[tuple[object, threading.Event]] = []
        self.refuse: set[bool] = set()
        monkeypatch.setattr(worker, "start_delivery", self.start)

    def start(self, config, board, feed, log, pulls, pins, stop, **kwargs):
        if config.pull_requests in self.refuse:
            raise ValueError("refused")
        self.built.append((config, stop))
        return None, None


def _delivery(path: Path) -> worker.Delivery:
    delivery = worker.Delivery(load(path), None, None, None, None, None)
    delivery.start()
    return delivery


def test_a_reload_with_an_invalid_config_keeps_the_running_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loops = Loops(monkeypatch)
    path = _config(tmp_path, "delivery_worker = true\n")
    delivery = _delivery(path)
    path.write_text("delivery_worker = 3\n")

    delivery.reload(path)

    assert [stop.is_set() for _, stop in loops.built] == [False]


def test_a_reload_that_changes_no_delivery_block_keeps_the_running_loops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loops = Loops(monkeypatch)
    path = _config(tmp_path, "delivery_worker = true\nslow_read_seconds = 1.0\n")
    delivery = _delivery(path)
    path.write_text("delivery_worker = true\nslow_read_seconds = 2.0\n")

    delivery.reload(path)

    assert [stop.is_set() for _, stop in loops.built] == [False]


def test_a_reload_that_changes_a_delivery_block_rebuilds_the_loops_in_the_same_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loops = Loops(monkeypatch)
    monkeypatch.setattr(os, "execv", lambda *args: pytest.fail("re-executed the worker"))
    path = _config(tmp_path, "delivery_worker = true\npull_requests = true\n")
    delivery = _delivery(path)
    path.write_text("delivery_worker = true\npull_requests = false\n")

    delivery.reload(path)

    assert [(config.pull_requests, stop.is_set()) for config, stop in loops.built] == [(True, True), (False, False)]


def test_a_changed_delivery_block_the_loops_cannot_build_leaves_the_old_loops_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loops = Loops(monkeypatch)
    path = _config(tmp_path, "delivery_worker = true\npull_requests = true\n")
    delivery = _delivery(path)
    loops.refuse = {False}
    path.write_text("delivery_worker = true\npull_requests = false\n")

    delivery.reload(path)

    assert [(config.pull_requests, stop.is_set()) for config, stop in loops.built] == [(True, True), (True, False)]


def test_a_reload_after_a_rebuild_compares_with_the_rebuilt_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loops = Loops(monkeypatch)
    path = _config(tmp_path, "delivery_worker = true\npull_requests = true\n")
    delivery = _delivery(path)
    path.write_text("delivery_worker = true\npull_requests = false\n")
    delivery.reload(path)

    delivery.reload(path)

    assert len(loops.built) == 2


def test_a_changed_board_or_database_is_left_to_a_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loops = Loops(monkeypatch)
    path = _config(tmp_path, "delivery_worker = true\n")
    delivery = _delivery(path)
    path.write_text('delivery_worker = true\ndatabase_url = "sqlite:///other.sqlite"\n')

    delivery.reload(path)

    assert [stop.is_set() for _, stop in loops.built] == [False]


def test_stopping_the_delivery_stops_its_loops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loops = Loops(monkeypatch)
    delivery = _delivery(_config(tmp_path, "delivery_worker = true\n"))

    delivery.stop()

    assert loops.built[0][1].is_set()
