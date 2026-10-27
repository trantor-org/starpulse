"""`serve` owns the Page API's listening socket and supervises `starpulse worker api`, which builds the page and reads
the Board from the read model."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest
from starpulse.runtime import assembly, server, worker
from starpulse.runtime.hold import STATIC_ENV
from starpulse.views.bin import api_worker

from tests import fake_board
from tests.conftest import FakeSupervisor
from tests.stores import migrate_config_store

BOARD = '[board]\ntype = "tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)
    monkeypatch.setattr(server, "stay_until_stopped", lambda: None)
    monkeypatch.setattr("starpulse.runtime.server.serve_until_stopped", lambda httpd, feed: None)
    path = tmp_path / "starpulse.toml"
    path.write_text(BOARD)
    migrate_config_store(path)
    return path


def test_serve_binds_the_socket_and_hands_it_to_the_api_child_it_supervises(
    config: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor]
) -> None:
    monkeypatch.setattr(api_worker, "page_app", lambda *args, **kwargs: pytest.fail("serve builds no page"))

    server.main(["--config", str(config), "--host", "127.0.0.1", "--port", "0", "--hours", "3"])

    [supervisor] = supervisors
    listening = supervisor.options["sockets"]["api"]
    assert isinstance(listening, socket.socket)
    assert listening.getsockname()[0] == "127.0.0.1"
    assert supervisor.commands["api"] == [
        sys.executable, "-m", "starpulse", "worker", "api", "--config", str(config), "--hours", "3.0",
    ]  # fmt: skip
    assert supervisor.started
    assert supervisor.stopped


def test_serve_binds_nothing_and_starts_no_api_child_for_a_true_api_worker_setting(
    config: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor]
) -> None:
    config.write_text("api_worker = true\n" + BOARD)

    server.main(["--config", str(config), "--port", "0"])

    assert "api" not in supervisors[0].commands
    assert supervisors[0].options["sockets"] == {}


def test_serve_refuses_an_unbuilt_page_before_it_starts_any_child(
    config: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor], tmp_path: Path
) -> None:
    monkeypatch.setattr(server, "_STATIC", tmp_path / "missing")

    with pytest.raises(SystemExit) as exited:
        server.main(["--config", str(config), "--port", "0"])

    assert exited.value.code == 1
    assert supervisors == []


def test_serve_stops_with_the_reason_when_the_config_builds_no_page_and_leaves_no_child_running(
    config: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor], capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(*args: object) -> None:
        raise ValueError("writers name workflows no configured adapter lists: ['bogus/actor']")

    monkeypatch.setattr(assembly, "assemble", refuse)

    with pytest.raises(SystemExit) as exited:
        server.main(["--config", str(config), "--port", "0"])

    assert exited.value.code == 1
    assert "no configured adapter lists: ['bogus/actor']" in capsys.readouterr().err
    assert all(supervisor.stopped for supervisor in supervisors)


def test_serve_hands_the_api_child_the_page_build_it_checked_and_the_child_serves_it(
    config: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor], tmp_path: Path
) -> None:
    handed = tmp_path / "static"  # the build `serve` checked, as the `config` fixture set it
    server.main(["--config", str(config), "--port", "0"])
    assert os.environ[STATIC_ENV] == str(handed)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", tmp_path / "unbuilt")  # the child's own checkout has no build
    monkeypatch.setenv(STATIC_ENV, str(elsewhere))
    monkeypatch.setattr(api_worker, "page_app", lambda *args, **kwargs: None)

    worker.main(["api", "--config", str(config), "--port", "0"])

    assert server._STATIC == elsewhere


def test_the_api_child_reads_the_board_from_the_read_model_and_starts_no_adapter_watcher(
    config: Path, monkeypatch: pytest.MonkeyPatch, supervisors: list[FakeSupervisor]
) -> None:
    handled: dict[str, object] = {}
    monkeypatch.setattr(api_worker, "page_app", lambda *args, **kwargs: handled.update(kwargs, args=args))

    worker.main(["api", "--config", str(config), "--port", "0"])

    feed = handled["args"][0]
    assert "FAKE-1" not in str(feed.snapshot())  # the adapter's `start` put its tasks on the feed; nothing did
    assert supervisors == []  # the child supervises nothing
