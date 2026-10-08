"""A restarted Board reader resumes from the state the last run saved, on SQLite and on Postgres."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator

import pytest
from sqlalchemy import delete

from starpulse.contracts.adapters import BoardTask
from starpulse.projections.board_feed import BoardFeed, follow
from starpulse.store.event_log import EventLog
from starpulse.store.tables import events

STREAM = "board:tasks"


@pytest.fixture
def log(database_url: str) -> EventLog:
    return EventLog(database_url)


@pytest.fixture
def run() -> Iterator[Callable[[BoardFeed, EventLog], list[str]]]:
    """Follow the stream into a feed until the feed is ready; the list is the entry ids its handler was given."""
    stops: list[threading.Event] = []

    def run(feed: BoardFeed, log: EventLog) -> list[str]:
        handled: list[str] = []

        def handle(entry_id: str, fields: dict) -> None:
            handled.append(entry_id)
            feed.put(BoardTask(id=fields["id"], team="demo", title=fields["id"], lane=fields["lane"]))
            feed.seen(entry_id)

        stops.append(threading.Event())
        follow(feed, log, STREAM, handle, stop=stops[-1], interval=0.01)
        assert feed.ready.wait(5), "the feed never became ready"
        return handled

    yield run
    for stop in stops:
        stop.set()


def _place(log: EventLog, task: str, lane: str) -> int:
    cursor = log.append(STREAM, {"id": task, "lane": lane})
    assert cursor is not None
    return cursor


def _lanes(feed: BoardFeed) -> dict[str, str]:
    return {agent["id"]: agent["state"] for agent in feed.snapshot()["flows"][0]["agents"]}


def _until(done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not done():
        assert time.monotonic() < deadline, "the reader never got there"
        time.sleep(0.01)


def test_a_restart_reads_only_the_entries_after_the_saved_cursor(log: EventLog, run: Callable) -> None:
    _place(log, "TASK-1", "to_do")
    _place(log, "TASK-2", "to_do")
    first = BoardFeed()
    run(first, log)
    first.save()
    moved = _place(log, "TASK-2", "in_progress")

    second = BoardFeed()
    handled = run(second, log)
    _until(lambda: handled == [str(moved)])

    assert _lanes(second) == {"TASK-1": "to_do", "TASK-2": "in_progress"}


def test_a_restart_with_nothing_new_is_ready_without_reading_an_entry(log: EventLog, run: Callable) -> None:
    _place(log, "TASK-1", "to_do")
    first = BoardFeed()
    run(first, log)
    first.save()

    second = BoardFeed()
    handled = run(second, log)

    assert (handled, _lanes(second)) == ([], {"TASK-1": "to_do"})


def test_a_restart_with_no_saved_state_replays_everything_the_log_retains(log: EventLog, run: Callable) -> None:
    first, second = _place(log, "TASK-1", "to_do"), _place(log, "TASK-2", "to_do")

    feed = BoardFeed()
    handled = run(feed, log)
    _until(lambda: len(handled) == 2)

    assert (handled, _lanes(feed)) == ([str(first), str(second)], {"TASK-1": "to_do", "TASK-2": "to_do"})


def test_a_restart_whose_saved_cursor_was_pruned_replays_the_retained_log(log: EventLog, run: Callable) -> None:
    _place(log, "TASK-1", "to_do")
    _place(log, "TASK-2", "to_do")
    first = BoardFeed()
    run(first, log)
    first.save()
    _place(log, "TASK-3", "to_do")
    kept = _place(log, "TASK-4", "to_do")
    with log.engine.begin() as db:
        db.execute(delete(events).where(events.c.id < kept))  # the retention took everything before TASK-4

    second = BoardFeed()
    handled = run(second, log)
    _until(lambda: handled == [str(kept)])

    assert _lanes(second) == {"TASK-4": "to_do"}  # the saved Board was not trusted across the gap
