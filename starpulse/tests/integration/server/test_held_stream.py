"""The stream a session reads its held tasks from: its own tasks, sent again only when they change."""

import urllib.error
import urllib.request
from pathlib import Path

import pytest

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import next_event as _next_event
from starpulse._internal.kit.adapter_kit import serve as _serve
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.kit.adapter_kit import url as _url
from starpulse.tests.machines import MACHINES


def _held(document: dict) -> list[tuple[str, str]]:
    return [(t["id"], c["state"]) for c in document["columns"] for t in c["tasks"]]


def test_a_session_is_sent_its_tasks_then_only_a_change_to_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse._internal.server.server._HELD_SETTLE_S", 0)
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "In Progress", holder="session-1"))
    feed.put(task("PROJ-2", "In Progress", holder="session-2"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/held?holder=session-1"), timeout=5) as resp:
            head = (resp.status, resp.headers["Content-Type"], resp.headers["Cache-Control"])
            first = _next_event(resp)
            feed.put(task("PROJ-2", "Review", holder="session-2"))  # another session's task: nothing to send
            feed.put(task("PROJ-3", "In Progress", holder="session-1"))
            second = _next_event(resp)

    assert head == (200, "text/event-stream", "no-store")
    assert (first[0], _held(first[1])) == ("held", [("PROJ-1", "in_progress")])
    assert (second[0], _held(second[1])) == ("held", [("PROJ-1", "in_progress"), ("PROJ-3", "in_progress")])


def test_a_held_task_carries_what_starpulse_board_prints_of_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse._internal.server.server._HELD_SETTLE_S", 0)
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "In Progress", holder="session-1", milestone="m-7"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/held?holder=session-1"), timeout=5) as resp:
            _, document = _next_event(resp)

    (held,) = [t for c in document["columns"] for t in c["tasks"]]
    assert (held["id"], held["title"], held["holder"], held["milestone"]) == ("PROJ-1", "Title of PROJ-1", "session-1", "m-7")
    assert held.keys() >= {"criteria", "pause_reason", "waiting_on", "prs", "moves"}


def test_a_stream_without_a_holder_is_refused(tmp_path: Path) -> None:
    with _serve(tmp_path) as server:
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(_url(server, "/api/held"), timeout=5)

    assert refused.value.code == 400


def _lanes(document: dict) -> dict[str, list[str]]:
    return {c["state"]: [t["id"] for t in c["tasks"]] for c in document["columns"]}


def test_the_lanes_stream_sends_on_connect_and_again_only_on_a_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse._internal.server.server._HELD_SETTLE_S", 0)
    feed = BoardFeed(machines=MACHINES)
    feed.put(task("PROJ-1", "In Progress", holder="session-1"))
    feed.put(task("PROJ-2", "Ready"))
    feed.put(task("PROJ-9", "Done"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/lanes?state=in_progress&state=ready"), timeout=5) as resp:
            head = (resp.status, resp.headers["Content-Type"], resp.headers["Cache-Control"])
            first = _next_event(resp)
            feed.put(task("PROJ-9", "Archived"))  # a lane the stream was not asked for: nothing to send
            feed.put(task("PROJ-2", "Review"))
            second = _next_event(resp)

    assert head == (200, "text/event-stream", "no-store")
    assert (first[0], _lanes(first[1])) == ("lanes", {"in_progress": ["PROJ-1"], "ready": ["PROJ-2"]})
    assert (second[0], _lanes(second[1])) == ("lanes", {"in_progress": ["PROJ-1"], "ready": []})
