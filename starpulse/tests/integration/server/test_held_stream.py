"""The stream a session reads its held tasks from: its own tasks, sent again only when they change."""

import time
import urllib.error
import urllib.request
from contextlib import ExitStack
from pathlib import Path

import pytest

from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.view import board_columns
from starpulse.runtime.adapter_kit import next_event as _next_event
from starpulse.runtime.adapter_kit import serve as _serve
from starpulse.runtime.adapter_kit import task
from starpulse.runtime.adapter_kit import url as _url
from starpulse.tests.machines import MACHINES, ROLES

DAY_S = 86400.0


def _held(document: dict) -> list[tuple[str, str]]:
    return [(t["id"], c["state"]) for c in document["columns"] for t in c["tasks"]]


def test_a_session_is_sent_its_tasks_then_only_a_change_to_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse.views.streams._HELD_SETTLE_S", 0)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "In Progress", assignee="session-1"))
    feed.put(task("PROJ-2", "In Progress", assignee="session-2"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/held?assignee=session-1"), timeout=5) as resp:
            head = (resp.status, resp.headers["Content-Type"], resp.headers["Cache-Control"])
            first = _next_event(resp)
            feed.put(task("PROJ-2", "Review", assignee="session-2"))  # another session's task: nothing to send
            feed.put(task("PROJ-3", "In Progress", assignee="session-1"))
            second = _next_event(resp)

    assert head == (200, "text/event-stream", "no-store")
    assert (first[0], _held(first[1])) == ("held", [("PROJ-1", "in_progress")])
    assert (second[0], _held(second[1])) == ("held", [("PROJ-1", "in_progress"), ("PROJ-3", "in_progress")])


def test_a_held_task_carries_what_starpulse_board_prints_of_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse.views.streams._HELD_SETTLE_S", 0)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "In Progress", assignee="session-1", profile="@agent-standard-high", milestone="m-7"))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/held?assignee=session-1"), timeout=5) as resp:
            _, document = _next_event(resp)

    (held,) = [t for c in document["columns"] for t in c["tasks"]]
    assert (held["id"], held["title"], held["assignee"], held["profile"], held["milestone"]) == (
        "PROJ-1",
        "Title of PROJ-1",
        "session-1",
        "@agent-standard-high",
        "m-7",
    )
    assert "holder" not in held
    assert held.keys() >= {"criteria", "pause_reason", "waiting_on", "prs", "moves"}


def test_a_held_task_does_not_wait_on_a_dependency_that_went_cold_in_done(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse.views.streams._HELD_SETTLE_S", 0)
    now = time.time()
    feed = BoardFeed(roles=ROLES, machines=MACHINES, clock=lambda: now)
    feed.expect("0-0")
    feed.put(task("PROJ-2", "Done", observed_at=now - 2 * DAY_S))
    feed.put(task("PROJ-1", "In Progress", assignee="session-1", dependencies=("PROJ-2",)))
    with _serve(tmp_path, feed) as server:
        with urllib.request.urlopen(_url(server, "/api/held?assignee=session-1"), timeout=5) as resp:
            _, document = _next_event(resp)

    (held,) = [t for c in document["columns"] for t in c["tasks"]]
    assert (held["dependencies"], held["waiting_on"]) == (["PROJ-2"], [])


def test_a_stream_without_a_holder_is_refused(tmp_path: Path) -> None:
    with _serve(tmp_path) as server:
        with pytest.raises(urllib.error.HTTPError) as refused:
            urllib.request.urlopen(_url(server, "/api/held"), timeout=5)

    assert refused.value.code == 400


def _lanes(document: dict) -> dict[str, list[str]]:
    return {c["state"]: [t["id"] for t in c["tasks"]] for c in document["columns"]}


def test_the_lanes_stream_sends_on_connect_and_again_only_on_a_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse.views.streams._HELD_SETTLE_S", 0)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "In Progress", assignee="session-1"))
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


def _builds_after_quiet(calls: list[int]) -> int:
    """The builds counted once no stream has built for a moment: a stream woken in error builds a beat after the others."""
    seen = -1
    while seen != len(calls):
        seen = len(calls)
        time.sleep(0.2)
    return seen


def test_held_and_lanes_streams_share_one_build_of_the_columns_per_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse.views.streams._HELD_SETTLE_S", 0)
    calls: list[int] = []

    def counted(*args: object, **kwargs: object) -> dict:
        calls.append(1)
        return board_columns(*args, **kwargs)

    monkeypatch.setattr("starpulse.views.column_stream.board_columns", counted)
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    sessions = [f"session-{n}" for n in range(4)]
    for n, session in enumerate(sessions):
        feed.put(task(f"PROJ-{n}", "In Progress", assignee=session))
    with _serve(tmp_path, feed) as server, ExitStack() as streams:
        held = [streams.enter_context(urllib.request.urlopen(_url(server, f"/api/held?assignee={s}"), timeout=5)) for s in sessions]
        lanes = streams.enter_context(urllib.request.urlopen(_url(server, "/api/lanes?state=in_progress"), timeout=5))
        for resp in [*held, lanes]:
            _next_event(resp)
        calls.clear()
        feed.put(task("PROJ-0", "In Progress", assignee="session-0", title="Renamed"))
        _next_event(held[0])
        _next_event(lanes)
        builds = _builds_after_quiet(calls)

    assert builds == 1
