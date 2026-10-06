"""The Board a feed saves with the cursor it reflects, and what a restart does with what was saved."""

from __future__ import annotations

import os
import signal
import threading
import time
from pathlib import Path

import pytest

from starpulse.board_feed import BoardFeed
from starpulse.contracts import BoardTask
from starpulse.event_log import EventLog
from starpulse.server import serve_until_stopped

STREAM = "board:tasks"


class _Store:
    """A store holding one saved Board per stream, counting its writes."""

    def __init__(self, saved: dict[str, tuple[str, dict]] | None = None) -> None:
        self.saved = saved or {}
        self.writes = 0
        self.down = False

    def load_board_state(self, stream: str) -> tuple[str, dict] | None:
        return self.saved.get(stream)

    def save_board_state(self, stream: str, cursor: str, state: dict) -> None:
        if self.down:
            raise OSError("database is locked")
        self.writes += 1
        self.saved[stream] = (cursor, state)


def _feed_with_tasks() -> BoardFeed:
    feed = BoardFeed()
    feed.put(BoardTask(id="TASK-1", title="open", lane="to_do", assignee="opus", description="d"))
    feed.put(BoardTask(id="TASK-2", title="gone", lane="done", settled="completed", assignee="sonnet"))
    feed.seen("7-0")
    return feed


def _resumed(store: _Store, retained: bool = True) -> tuple[BoardFeed, str | None]:
    feed = BoardFeed()
    return feed, feed.resume(store, STREAM, lambda cursor: retained)


def test_a_saved_board_restores_its_tasks_assignees_and_cursor_and_is_ready_at_that_entry() -> None:
    store = _Store()
    first = _feed_with_tasks()
    first.resume(store, STREAM, lambda cursor: False)
    first.save()

    feed, cursor = _resumed(store)
    feed.expect("7-0")

    assert cursor == "7-0"
    assert feed.snapshot()["flows"][0]["agents"] == first.snapshot()["flows"][0]["agents"]
    assert feed.snapshot()["settled"] == {"TASK-2": "completed"}
    assert feed.ready.is_set()


def test_a_saved_board_is_not_ready_until_the_entries_after_its_cursor_are_read() -> None:
    store = _Store()
    first = _feed_with_tasks()
    first.resume(store, STREAM, lambda cursor: False)
    first.save()
    feed, _ = _resumed(store)

    feed.expect("9-0")
    assert not feed.ready.is_set()
    feed.seen("9-0")

    assert feed.ready.is_set()


def test_a_restored_task_read_again_is_no_delta() -> None:
    store = _Store()
    first = _feed_with_tasks()
    first.resume(store, STREAM, lambda cursor: False)
    first.save()
    feed, _ = _resumed(store)
    _, deltas = feed.subscribe()

    feed.put(BoardTask(id="TASK-1", title="open", lane="to_do", assignee="opus", description="d"))

    assert deltas.empty()


@pytest.mark.parametrize(
    "saved",
    [
        None,
        ("7-0", {"open": {}}),
        ("7-0", {"open": 5, "settled": {}, "assignees": {}}),
        ("not-a-cursor", {"open": {}, "settled": {}, "assignees": {}}),
    ],
    ids=["nothing saved", "a missing part", "a part of the wrong type", "a cursor that is no entry id"],
)
def test_a_board_that_cannot_be_restored_replays_and_keeps_the_feed_empty(saved: tuple[str, dict] | None) -> None:
    feed, cursor = _resumed(_Store({STREAM: saved} if saved else {}))

    assert (cursor, feed.snapshot()["flows"][0]["agents"], feed.snapshot()["settled"]) == (None, [], {})


def test_a_board_the_stream_no_longer_covers_is_not_restored() -> None:
    first = _feed_with_tasks()
    store = _Store()
    first.resume(store, STREAM, lambda cursor: False)
    first.save()

    feed, cursor = _resumed(store, retained=False)

    assert (cursor, feed.snapshot()["flows"][0]["agents"]) == (None, [])


def test_the_board_is_saved_again_only_after_the_feed_read_a_newer_entry() -> None:
    store = _Store()
    feed = _feed_with_tasks()
    feed.resume(store, STREAM, lambda cursor: False)

    feed.save()
    feed.save()
    feed.seen("8-0")
    feed.save()

    assert (store.writes, store.saved[STREAM][0]) == (2, "8-0")


def test_a_feed_that_has_read_nothing_saves_nothing() -> None:
    store = _Store()
    feed = BoardFeed()
    feed.resume(store, STREAM, lambda cursor: False)

    feed.save()

    assert store.writes == 0


def test_a_feed_with_no_store_saves_nothing() -> None:
    _feed_with_tasks().save()  # nothing to assert beyond not raising


def test_a_store_that_cannot_be_written_is_tried_again_at_the_next_save(caplog: pytest.LogCaptureFixture) -> None:
    store = _Store()
    feed = _feed_with_tasks()
    feed.resume(store, STREAM, lambda cursor: False)
    store.down = True

    feed.save()
    store.down = False
    feed.save()

    assert (store.writes, "cannot save the Board" in caplog.text) == (1, True)


def test_a_feed_kept_saved_writes_on_each_interval_and_once_more_when_stopped() -> None:
    store = _Store()
    feed = _feed_with_tasks()
    feed.resume(store, STREAM, lambda cursor: False)
    stop = threading.Event()
    saver = threading.Thread(target=feed.keep_saved, args=(stop, 0.01))
    saver.start()
    while store.writes < 1:
        stop.wait(0.01)
    feed.seen("9-0")  # read just before the stop, after the last interval
    stop.set()
    saver.join(5)

    assert store.saved[STREAM][0] == "9-0"


def test_the_event_log_keeps_one_saved_board_per_stream_and_the_oldest_row_it_holds(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    assert (log.oldest(), log.load_board_state(STREAM)) == (None, None)

    first = log.append(STREAM, {"n": "1"})
    log.append(STREAM, {"n": "2"})
    log.save_board_state(STREAM, "1-0", {"open": {}})
    log.save_board_state(STREAM, "2-0", {"open": {"TASK-1": {"id": "TASK-1"}}})
    log.save_board_state("other", "5-0", {})

    assert log.oldest() == first
    assert log.load_board_state(STREAM) == ("2-0", {"open": {"TASK-1": {"id": "TASK-1"}}})


class _Server:
    """A server that runs until a signal ends it."""

    def serve_forever(self) -> None:
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(5)  # the handler leaves before this ends
        raise AssertionError("SIGTERM did not stop the server")


def test_a_stopped_server_saves_the_board_before_it_exits() -> None:
    store = _Store()
    feed = _feed_with_tasks()
    feed.resume(store, STREAM, lambda cursor: False)
    before = signal.getsignal(signal.SIGTERM)
    try:
        with pytest.raises(SystemExit):
            serve_until_stopped(_Server(), feed)  # type: ignore[arg-type]
    finally:
        signal.signal(signal.SIGTERM, before)

    assert store.saved[STREAM][0] == "7-0"
