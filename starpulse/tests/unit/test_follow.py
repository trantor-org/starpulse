"""`follow` reads one stream of the event log into a feed on a thread: the retained log first, then each new entry."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from starpulse.board_feed import follow
from starpulse.event_log import EventLog

STREAM = "backlog:projection"


class _Feed:
    """What `follow` needs of a feed, recording the calls it makes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def await_stream(self) -> None:
        self.calls.append(("await", ""))

    def expect(self, last_id: str) -> None:
        self.calls.append(("expect", last_id))


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


def _until(done: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not done():
        assert time.monotonic() < deadline, "follow never got there"
        time.sleep(0.01)


@pytest.fixture
def stop():
    event = threading.Event()
    yield event
    event.set()


def test_follow_replays_the_retained_stream_in_order_then_reads_what_is_appended(
    log: EventLog, stop: threading.Event
) -> None:
    log.append(STREAM, {"n": "1"})
    log.append("machine:events", {"n": "other stream"})
    log.append(STREAM, {"n": "2"})
    feed, seen = _Feed(), []

    follow(feed, log, STREAM, lambda entry_id, fields: seen.append((entry_id, fields["n"])), stop=stop, interval=0.01)
    _until(lambda: len(seen) == 2)
    log.append(STREAM, {"n": "3"})
    _until(lambda: len(seen) == 3)

    assert seen == [("1", "1"), ("3", "2"), ("4", "3")]


def test_follow_says_the_stream_is_not_reached_then_expects_the_last_entry_of_its_own_stream(
    log: EventLog, stop: threading.Event
) -> None:
    log.append(STREAM, {"n": "1"})
    last = log.append(STREAM, {"n": "2"})
    log.append("machine:events", {"n": "after it, on another stream"})
    feed = _Feed()

    follow(feed, log, STREAM, lambda *_: None, stop=stop, interval=0.01)
    _until(lambda: len(feed.calls) == 2)

    assert feed.calls == [("await", ""), ("expect", str(last))]


def test_follow_expects_the_empty_stream_id_when_the_log_holds_no_entry_of_it(
    log: EventLog, stop: threading.Event
) -> None:
    feed = _Feed()

    follow(feed, log, STREAM, lambda *_: None, stop=stop, interval=0.01)
    _until(lambda: len(feed.calls) == 2)

    assert feed.calls[1] == ("expect", "0-0")


def test_follow_keeps_trying_until_the_database_is_reachable(
    log: EventLog, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    log.append(STREAM, {"n": "1"})
    reachable, last, attempts = threading.Event(), log.last, []

    def gated(stream: str) -> int | None:
        attempts.append(stream)
        if not reachable.is_set():
            raise OSError("unable to open database file")
        return last(stream)

    monkeypatch.setattr(log, "last", gated)
    feed, seen = _Feed(), []

    follow(feed, log, STREAM, lambda entry_id, fields: seen.append(entry_id), stop=stop, interval=0.01)
    _until(lambda: len(attempts) >= 3)  # it asked again after each refusal
    assert feed.calls == [("await", "")]
    reachable.set()
    _until(lambda: seen == ["1"])

    assert feed.calls[1] == ("expect", "1")
