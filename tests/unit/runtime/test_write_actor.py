"""The actor a task write names reaches the board writer, so a rule's `unless_actor` and its refusal judge the same write
from the page and from an agent's CLI."""

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import Written
from starpulse.contracts.adapters import Move
from starpulse.event_log import lane_events
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.flow_metrics.history import HistoryStore
from starpulse.runtime.adapter_kit import task
from starpulse.views.writes import archive_task, create_task, edit_task, start_task

from tests.machines import MACHINES, ROLES


class _Writer:
    """A board writer that records how it was called."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Written:
        self.calls.append((args, kwargs))
        return Written(True, "PROJ-9")


def _feed() -> BoardFeed:
    feed = BoardFeed(roles=ROLES, machines=MACHINES, domains={}, run_safe=frozenset())
    feed.put(task("PROJ-3", "Ready", moves={"in_progress": Move(allowed=True)}))
    return feed


def _post(handler: Callable[..., tuple[int, dict[str, Any]]], body: dict[str, Any], writer: _Writer) -> tuple[int, Any]:
    raw = json.dumps(body).encode()
    return handler("127.0.0.1", raw, _feed(), writer)


def _edit(source: str, raw: bytes, feed: BoardFeed, writer: _Writer) -> tuple[int, dict[str, Any]]:
    return edit_task(source, raw, feed, lambda _: {"title": "Old"}, writer)


def _archive(source: str, raw: bytes, feed: BoardFeed, writer: _Writer) -> tuple[int, dict[str, Any]]:
    return archive_task(source, raw, feed, writer)


def _create(source: str, raw: bytes, feed: BoardFeed, writer: _Writer) -> tuple[int, dict[str, Any]]:
    return create_task(source, raw, writer)


def _start(source: str, raw: bytes, feed: BoardFeed, writer: _Writer) -> tuple[int, dict[str, Any]]:
    return start_task(source, raw, feed, writer, lambda task, **_: "http://session.test/1")


#: Each write route, a body that lands and the positional arguments its writer is called with.
ROUTES = {
    "edit": (
        _edit,
        {"task": "PROJ-3", "base": {"title": "Old"}, "changes": {"title": "New"}},
        ("PROJ-3", {"title": "New"}, ""),
    ),
    "archive": (_archive, {"task": "PROJ-3", "reason": "obsolete"}, ("PROJ-3", "obsolete")),
    "create": (_create, {"title": "New task"}, ("New task", {"created_by": "anonymous"})),
    "start": (
        _start,
        {"task": "PROJ-3", "assignee": "@agent-deep-high", "harness": "claude"},
        ("PROJ-3", "@agent-deep-high"),
    ),
}


@pytest.mark.parametrize("route", ROUTES)
def test_a_write_naming_an_actor_hands_it_to_the_writer(route: str) -> None:
    handler, body, args = ROUTES[route]
    writer = _Writer()

    status, _ = _post(handler, {**body, "actor": "dagu/bot"}, writer)

    assert status in (200, 201)
    assert writer.calls == [(args, {"actor": "dagu/bot"})]


@pytest.mark.parametrize("route", ROUTES)
def test_a_write_naming_no_actor_is_handed_to_the_writer_as_anonymous(route: str) -> None:
    handler, body, args = ROUTES[route]
    writer = _Writer()

    status, _ = _post(handler, body, writer)

    assert status in (200, 201)
    assert writer.calls == [(args, {} if route == "start" else {"actor": "anonymous"})]  # a start names its own actor


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("actor", [7, "", ["agent"]])
def test_a_write_naming_an_actor_that_is_not_text_is_a_bad_request(route: str, actor: object) -> None:
    handler, body, _ = ROUTES[route]
    writer = _Writer()

    status, answer = _post(handler, {**body, "actor": actor}, writer)

    assert (status, writer.calls) == (400, [])
    assert "actor" in answer["error"]


def test_a_create_the_watch_places_before_the_create_answers_still_names_its_writer(tmp_path: Path) -> None:
    """A create learns its task's id only from the write, and the watch could place the new task first: TASK-5549
    entered Ready at 18:05:47 on 2026-10-14 with no actor. The create holds the feed's placing until it has recorded
    its lane, so the placement finds it recorded under the writer."""
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.record_lanes(HistoryStore(f"sqlite:///{tmp_path / 'events.sqlite'}", MACHINES), log)
    watch: list[threading.Thread] = []

    def create(title: str, details: Any, /, actor: str = "operator") -> Written:
        placed = threading.Thread(target=feed.put, args=(task("PROJ-9", "Ready"),))  # the watch sees the file land
        watch.append(placed)
        placed.start()
        placed.join(0.5)  # blocked: the create holds the feed's placing until its lane is recorded
        return Written(True, "PROJ-9", lane="Ready", at=100.0)

    body = {"title": "t", "actor": "agent", "session": "s1", "harness": "claude"}
    status, _ = create_task("127.0.0.1", json.dumps(body).encode(), create, feed)
    for placed in watch:
        placed.join()

    entries = Tail.replay(log, lane_events.STREAM).poll()

    assert (status, [(e.fields.get("actor"), e.fields.get("session")) for e in entries]) == (201, [("agent", "s1")])
