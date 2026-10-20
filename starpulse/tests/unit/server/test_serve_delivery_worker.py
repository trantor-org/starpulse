"""`serve` starts none of the Delivery context's threads and draws what the worker projects."""

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from starpulse._internal.server import server
from starpulse._internal.server import worker as api_child
from starpulse.tests import fake_board

BOARD = '[board]\ntype = "starpulse.tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'
CONTEXT = f'refresh_token_env = "PULL_REFRESH_TOKEN"\n[release]\n{BOARD}[board.actor]\n'


class Built:
    """A stand-in for a class `serve` builds: records that it was, and that its thread was started."""

    made: list[Built] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.started = False
        type(self).made.append(self)

    def start(self, stop: object) -> None:
        self.started = True

    def run_forever(self) -> None:
        self.started = True

    def pulls_changed(self) -> None:
        pass

    def store_changed(self) -> None:
        pass

    def timed_projection(self, project: Callable[[], None]) -> Callable[[], None]:
        return project

    def refresh(self) -> None:
        pass

    def exposition(self) -> str:
        return ""

    def tracked(self) -> list[str]:
        return ["acme/widgets"]


class Actor(Built):
    made: list[Built] = []


class Sync(Built):
    made: list[Built] = []

    def request(self, repo: str, number: int) -> bool:
        return True


class Projection(Built):
    made: list[Built] = []


class Refresh(Built):
    made: list[Built] = []


class Follower:
    """Records the stop events `Projected.follow` was started with."""

    started: list[object] = []

    def __init__(self, *args: object) -> None:
        pass

    def follow(self, stop: threading.Event) -> threading.Thread:
        Follower.started.append(stop)
        return threading.Thread()


def _serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, text: str, *, gh: bool = True) -> list[object]:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)
    monkeypatch.setattr(server, "serve_until_stopped", lambda httpd, feed: None)
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}" if gh else None)
    monkeypatch.setenv("PULL_REFRESH_TOKEN", "secret")
    for name, cls in (("TaskActor", Actor), ("PullSync", Sync), ("PullRequests", Projection), ("PullRefresh", Refresh)):
        monkeypatch.setattr(server, name, cls)
        monkeypatch.setattr(cls, "made", [])
    monkeypatch.setattr(Follower, "started", [])
    monkeypatch.setattr(server, "Projected", Follower)
    polled: list[object] = []
    monkeypatch.setattr(server, "_keep_unblocked", lambda *args: polled.append(args))
    config = tmp_path / "starpulse.toml"
    config.write_text(text)

    api_child.main(["api", "--config", str(config), "--port", "0"])

    return polled


def test_serve_starts_none_of_the_delivery_threads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    polled = _serve(tmp_path, monkeypatch, CONTEXT)

    # the one PullSync built only answers which repositories the store tracks
    assert (Actor.made, [sync.started for sync in Sync.made], Projection.made, polled) == ([], [False], [], [])


def test_serve_follows_the_projection_the_worker_keeps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(tmp_path, monkeypatch, CONTEXT)

    assert len(Follower.started) == 1


def test_a_refresh_is_queued_for_the_worker_when_serve_has_no_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve(tmp_path, monkeypatch, CONTEXT, gh=False)

    assert [refresh.args[0] for refresh in Refresh.made] == ["secret"]
