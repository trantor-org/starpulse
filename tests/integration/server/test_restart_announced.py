"""What /api/events tells a page about the server's page build and its restart, so the page can say what its connection is doing."""

import time
import urllib.request
from http.client import HTTPResponse
from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import next_event, serve, task, url

from tests.machines import MACHINES, ROLES


def _open(server) -> HTTPResponse:
    return urllib.request.urlopen(url(server, "/api/events"), timeout=5)


def _build_of(server) -> str:
    with _open(server) as resp:
        assert next_event(resp, connection=True)[0] == "snapshot"
        name, data = next_event(resp, connection=True)
    assert name == "build"
    return data["id"]


def test_each_stream_names_the_page_build_right_after_its_snapshot(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES)) as server:
        first = _build_of(server)
        second = _build_of(server)

    assert first
    assert first == second


def test_a_rebuilt_page_is_named_by_a_different_build(tmp_path: Path) -> None:
    with serve(tmp_path, BoardFeed(roles=ROLES, machines=MACHINES)) as server:
        before = _build_of(server)
        (tmp_path / "static" / "index.html").write_text(
            '<!doctype html><script src="/assets/index-def456.js"></script>'
        )
        after = _build_of(server)

    assert before != after


def test_sigterm_tells_every_open_stream_the_server_is_restarting_before_the_process_exits(tmp_path: Path) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1"))
    with serve(tmp_path, feed) as server, _open(server) as one, _open(server) as two:
        for resp in (one, two):
            assert next_event(resp, connection=True)[0] == "snapshot"
            assert next_event(resp, connection=True)[0] == "build"
        server.stopping = lambda: feed.announce("restarting", {"at": time.time()})
        server.stop()
        server.join()

        # the frame is already in each socket: the server waited for every stream to write it before it let go
        assert [next_event(resp, connection=True)[0] for resp in (one, two)] == ["restarting", "restarting"]
