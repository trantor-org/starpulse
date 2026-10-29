"""A native write records its lane with the request's actor under the api and board workers' own wiring: the lane row and
the `board:lanes` entry both name the actor, where a worker that drops its lane log leaves both null (TASK-8917)."""

import threading
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.event_log import lane_events
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.runtime import assembly, server, worker
from starpulse.views.application.commands.writes import _record_written, _Who
from starpulse.views.bin import api_worker

from tests import fake_board
from tests.machines import MACHINES

BOARD = '[board]\ntype = "tests.fake_board"\nlanes = ["waiting", "ready", "done"]\nwrites = true\n'


@pytest.fixture
def held(monkeypatch: pytest.MonkeyPatch) -> list[threading.Event]:
    held: list[threading.Event] = []
    monkeypatch.setattr("starpulse.runtime.hold.hold", lambda event, reload: held.append(event))
    return held


def _config(tmp_path: Path, url: str, extra: str = "") -> Path:
    config = tmp_path / "starpulse.toml"
    config.write_text(f'database_url = "{url}"\n{extra}{BOARD}')
    return config


def _native_write(feed: BoardFeed) -> None:
    """A write made through the views, as a request names its actor."""
    written = Written(True, "Updated task T-1", lane="ready", at=110.0)
    _record_written(feed, "T-1", _Who("agent", "s1", "claude"), lambda: written)


def _assert_actor_recorded(url: str) -> None:
    steps = HistoryStore(url, MACHINES).lane_path("T-1")
    entries = [e for e in Tail.replay(EventLog(url), lane_events.STREAM).poll() if e.fields["lane"] == "ready"]

    assert [step.get("by") for step in steps] == ["agent"]  # the lane row
    assert [e.fields.get("actor") for e in entries] == ["agent"]  # the `board:lanes` entry


def test_the_api_worker_records_a_native_write_with_its_request_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html></html>")
    monkeypatch.setattr(server, "_STATIC", static)
    monkeypatch.setattr(server, "stay_until_stopped", lambda: None)
    monkeypatch.setattr("starpulse.runtime.server.serve_until_stopped", lambda httpd, feed: None)
    feeds: list[BoardFeed] = []
    monkeypatch.setattr(api_worker, "page_app", lambda feed, *args, **kwargs: feeds.append(feed))
    url = f"sqlite:///{tmp_path / 'events.sqlite'}"

    worker.main(["api", "--config", str(_config(tmp_path, url)), "--port", "0"])

    [feed] = feeds
    _native_write(feed)
    _assert_actor_recorded(url)


def test_the_board_worker_records_a_native_write_with_its_request_actor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, held: list[threading.Event]
) -> None:
    monkeypatch.setattr(fake_board, "BUILT", [])
    feeds: list[BoardFeed] = []
    build = assembly.assemble

    def assemble(*args, **kwargs):
        board, feed = build(*args, **kwargs)
        feeds.append(feed)
        return board, feed

    monkeypatch.setattr(assembly, "assemble", assemble)
    url = f"sqlite:///{tmp_path / 'events.sqlite'}"

    worker.main(["board", "--config", str(_config(tmp_path, url))])

    [feed] = feeds
    _native_write(feed)
    held[0].set()
    _assert_actor_recorded(url)
