"""`serve` runs the task actor when `[board.actor]` is configured, and Unblocker's polling thread does not start."""

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from starpulse.runtime import server, worker
from starpulse.tests import fake_board

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'


class Actor:
    built: list["Actor"] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False
        Actor.built.append(self)

    def start(self, stop: object) -> None:
        self.started = True

    def pulls_changed(self) -> None:
        pass

    def store_changed(self) -> None:
        pass

    def timed_projection(self, project: Callable[[], None]) -> Callable[[], None]:
        return project

    def exposition(self) -> str:
        return "starpulse_task_actor_refusals_total 0\n"


class Polled(list[object]):
    """Unblocker calls; serve runs `_keep_unblocked` on a daemon thread, so `called` says when one landed."""

    def __init__(self) -> None:
        super().__init__()
        self.called = threading.Event()

    def record(self, *args: object) -> None:
        self.append(args)
        self.called.set()


def _serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, gh: bool = False) -> Polled:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda *args: None)
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}" if gh else None)
    monkeypatch.setattr(server, "TaskActor", Actor)
    monkeypatch.setattr(Actor, "built", [])
    polled = Polled()
    monkeypatch.setattr(server, "_keep_unblocked", polled.record)
    config = tmp_path / "starpulse.toml"
    config.write_text(text)

    worker.main(["pulls", "--config", str(config)])

    return polled


def test_the_actor_starts_and_unblockers_thread_does_not(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    polled = _serve(tmp_path, monkeypatch, f"[release]\n{BOARD}[board.actor]\n")

    assert [actor.started for actor in Actor.built] == [True]
    assert polled == []


def test_the_actor_is_given_the_boards_criteria_evaluator_and_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(tmp_path, monkeypatch, f"{BOARD}[board.actor]\n")

    assert {"evaluate", "holds"} <= Actor.built[0].kwargs.keys()


def test_without_the_table_unblockers_thread_starts_and_no_actor_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    polled = _serve(tmp_path, monkeypatch, f"[release]\n{BOARD}")

    assert Actor.built == []
    assert polled.called.wait(timeout=10)
    assert len(polled) == 1


class Sync:
    projects: list[object] = []

    def __init__(self, *args: object, project: object = None, **kwargs: object) -> None:
        Sync.projects.append(project)

    def run_forever(self) -> None:
        pass

    def request(self) -> None:
        pass

    def project(self) -> None:
        pass


class Projection:
    refreshed = 0

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def refresh(self) -> None:
        Projection.refreshed += 1


def test_each_pull_request_projection_tells_the_actor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "PullSync", Sync)
    monkeypatch.setattr(server, "PullRequests", Projection)
    monkeypatch.setattr(Sync, "projects", [])
    monkeypatch.setattr(Projection, "refreshed", 0)
    changed: list[bool] = []
    monkeypatch.setattr(Actor, "pulls_changed", lambda self: changed.append(True))

    _serve(tmp_path, monkeypatch, f"{BOARD}[board.actor]\n", gh=True)
    Sync.projects[0]()

    assert (Projection.refreshed, changed) == (1, [True])


def test_a_board_that_cannot_edit_refuses_the_actor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit):
        _serve(tmp_path, monkeypatch, BOARD.replace("writes = true\n", "") + "[board.actor]\n")

    assert Actor.built == []
