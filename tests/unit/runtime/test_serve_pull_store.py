"""`serve` keeps the pull request store unless its config turns it off."""

import threading
from pathlib import Path

import pytest
from starpulse.runtime import read_model_follow, server, worker

from tests import fake_board


class Sync:
    built: list[Sync] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        Sync.built.append(self)

    def run_forever(self) -> None:
        pass

    def request(self, repo: str, number: int) -> None:
        pass

    def project(self) -> None:
        pass


@pytest.mark.parametrize(("line", "kept"), [("", True), ("pull_requests = false\n", False)])
def test_serve_starts_the_pull_store_only_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, line: str, kept: bool
) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda *args: None)
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(server, "PullSync", Sync)
    monkeypatch.setattr(Sync, "built", [])
    config = tmp_path / "starpulse.toml"
    config.write_text(line + '[board]\ntype = "tests.fake_board"\nlanes = ["open", "shut"]\n')

    worker.main(["pulls", "--config", str(config)])

    assert len(Sync.built) == int(kept)


def test_a_worker_stops_what_it_started_once_its_hold_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])
    held: list[threading.Event] = []
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda stop, reload: held.append(stop))
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(server, "PullSync", Sync)
    config = tmp_path / "starpulse.toml"
    config.write_text('[board]\ntype = "tests.fake_board"\nlanes = ["open", "shut"]\n')

    worker.main(["pulls", "--config", str(config)])

    [stop] = held
    assert stop.is_set()


def test_a_worker_whose_start_is_refused_stops_the_follower_it_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])
    stops: list[threading.Event] = []
    monkeypatch.setattr(read_model_follow, "follow", lambda projector, feed, stop: stops.append(stop))
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}")
    config = tmp_path / "starpulse.toml"
    config.write_text('[release]\n[board]\ntype = "tests.fake_board"\nlanes = ["open", "shut"]\n[board.actor]\n')

    with pytest.raises(SystemExit):
        worker.main(["pulls", "--config", str(config)])

    [stop] = stops
    assert stop.is_set()
