"""The actor a task write names reaches the board writer, so a rule's `unless_actor` and its refusal judge the same write
from the page and from an agent's CLI."""

import json
from collections.abc import Callable
from typing import Any

import pytest

from starpulse._internal.board.seam import Written
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.server.writes import archive_task, create_task, edit_task, start_task
from starpulse.contracts.adapters import Move
from starpulse.tests.machines import MACHINES


class _Writer:
    """A board writer that records how it was called."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Written:
        self.calls.append((args, kwargs))
        return Written(True, "PROJ-9")


def _feed() -> BoardFeed:
    feed = BoardFeed(machines=MACHINES, domains={}, run_safe=frozenset())
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
    return start_task(source, raw, feed, writer, lambda _: "http://session.test/1")


#: Each write route, a body that lands and the positional arguments its writer is called with.
ROUTES = {
    "edit": (
        _edit,
        {"task": "PROJ-3", "base": {"title": "Old"}, "changes": {"title": "New"}},
        ("PROJ-3", {"title": "New"}, ""),
    ),
    "archive": (_archive, {"task": "PROJ-3", "reason": "obsolete"}, ("PROJ-3", "obsolete")),
    "create": (_create, {"title": "New task"}, ("New task", {})),
    "start": (_start, {"task": "PROJ-3", "assignee": "@agent-deep-high"}, ("PROJ-3", "@agent-deep-high")),
}


@pytest.mark.parametrize("route", ROUTES)
def test_a_write_naming_an_actor_hands_it_to_the_writer(route: str) -> None:
    handler, body, args = ROUTES[route]
    writer = _Writer()

    status, _ = _post(handler, {**body, "actor": "dagu/bot"}, writer)

    assert status in (200, 201)
    assert writer.calls == [(args, {"actor": "dagu/bot"})]


@pytest.mark.parametrize("route", ROUTES)
def test_a_write_naming_no_actor_calls_a_writer_that_predates_actors(route: str) -> None:
    handler, body, args = ROUTES[route]
    writer = _Writer()

    status, _ = _post(handler, body, writer)

    assert status in (200, 201)
    assert writer.calls == [(args, {})]


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("actor", [7, "", ["agent"]])
def test_a_write_naming_an_actor_that_is_not_text_is_a_bad_request(route: str, actor: object) -> None:
    handler, body, _ = ROUTES[route]
    writer = _Writer()

    status, answer = _post(handler, {**body, "actor": actor}, writer)

    assert (status, writer.calls) == (400, [])
    assert "actor" in answer["error"]
