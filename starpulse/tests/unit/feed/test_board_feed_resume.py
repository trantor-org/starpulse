"""The Board a feed saves with the cursor it reflects, and what a restart does with what was saved."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.feed.snapshot import BoardSnapshot
from starpulse._internal.server.server import serve_until_stopped
from starpulse.contracts.adapters import BoardTask
from starpulse.event_log.event_log import EventLog

STREAM = "board:tasks"


class _Store:
    """The checkpoint table's two calls over a dict, counting writes."""

    def __init__(self, saved: dict[str, tuple[int, dict]] | None = None) -> None:
        self.saved = saved or {}
        self.writes = 0
        self.down = False

    def load(self, name: str, model: type[BaseModel] | None = None) -> tuple[int | None, BaseModel | None]:
        if name not in self.saved:
            return None, None
        position, state = self.saved[name]
        try:
            return position, model.model_validate(state)
        except ValidationError:
            return position, None

    def save(self, name: str, position: int, model: BaseModel | None = None, *, conn: object = None) -> None:
        if self.down:
            raise OSError("database is locked")
        self.writes += 1
        self.saved[name] = (position, model.model_dump(mode="json"))


def _feed_with_tasks() -> BoardFeed:
    feed = BoardFeed()
    feed.put(BoardTask(id="TASK-1", team="demo", title="open", lane="to_do", profile="opus", description="d"))
    feed.put(BoardTask(id="TASK-2", team="demo", title="gone", lane="done", settled="completed", profile="sonnet"))
    feed.seen("7-0")
    return feed


def _resumed(store: _Store, retained: bool = True) -> tuple[BoardFeed, int | None]:
    feed = BoardFeed()
    return feed, feed.resume(store, STREAM, lambda cursor: retained)


def test_a_saved_board_restores_its_tasks_assignees_and_cursor_and_is_ready_at_that_entry() -> None:
    store = _Store()
    first = _feed_with_tasks()
    first.resume(store, STREAM, lambda cursor: False)
    first.save()

    feed, cursor = _resumed(store)
    feed.expect("7-0")

    assert cursor == 7
    assert feed.snapshot()["flows"][0]["agents"] == first.snapshot()["flows"][0]["agents"]
    assert feed.snapshot()["settled"] == first.snapshot()["settled"]
    assert feed.ready.is_set()


def _start_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == "starpulse.board_feed"]


def test_a_start_with_saved_state_logs_the_cursor_it_resumes_after(caplog: pytest.LogCaptureFixture) -> None:
    store = _Store()
    first = _feed_with_tasks()
    first.resume(store, STREAM, lambda cursor: False)
    first.save()
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="starpulse.board_feed"):
        _resumed(store)

    assert _start_lines(caplog) == ["StarPulse: resuming after 7"]


@pytest.mark.parametrize(
    ("store", "retained", "reason"),
    [
        (_Store(), True, "no saved Board"),
        (_Store({STREAM: (7, {"open": {}, "settled": {}, "assignees": {}})}), False, "cursor 7 is no longer retained"),
        (_Store({STREAM: (7, {})}), True, "the saved Board cannot be read"),
    ],
)
def test_a_start_without_usable_state_logs_why_it_replays(
    caplog: pytest.LogCaptureFixture, store: _Store, retained: bool, reason: str
) -> None:
    with caplog.at_level(logging.INFO, logger="starpulse.board_feed"):
        _resumed(store, retained)

    assert _start_lines(caplog) == [f"StarPulse: replaying: {reason}"]


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

    feed.put(BoardTask(id="TASK-1", team="demo", title="open", lane="to_do", profile="opus", description="d"))

    assert deltas.empty()


@pytest.mark.parametrize(
    "saved",
    [
        None,
        (7, {"open": {}}),
        (7, {"open": 5, "settled": {}, "assignees": {}}),
        (7, {"open": {}, "settled": {"TASK-2": "completed"}, "assignees": {}}),
    ],
    ids=[
        "nothing saved",
        "a missing part",
        "a part of the wrong type",
        "a settled task saved as its state alone",
    ],
)
def test_a_board_that_cannot_be_restored_replays_and_keeps_the_feed_empty(saved: tuple[int, dict] | None) -> None:
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

    assert (store.writes, store.saved[STREAM][0]) == (2, 8)


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

    assert store.saved[STREAM][0] == 9


def test_the_event_log_keeps_one_saved_board_per_stream_and_the_oldest_row_it_holds(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    assert (log.oldest(), log.checkpoints.load(STREAM, BoardSnapshot)) == (None, (None, None))

    first = log._append(STREAM, {"n": "1"})
    log._append(STREAM, {"n": "2"})
    log.checkpoints.save(STREAM, 1, BoardSnapshot(open={}, settled={}, assignees={}))
    log.checkpoints.save(STREAM, 2, BoardSnapshot(open={"TASK-1": {"id": "TASK-1"}}, settled={}, assignees={}))
    log.checkpoints.save("other", 5, BoardSnapshot(open={}, settled={}, assignees={}))

    assert log.oldest() == first
    assert log.checkpoints.load(STREAM, BoardSnapshot)[0] == 2


def test_a_restarted_feed_resumes_from_the_checkpoint_tables_integer_position(tmp_path: Path) -> None:
    checkpoints = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").checkpoints
    first = _feed_with_tasks()
    first.resume(checkpoints, STREAM, lambda cursor: False)
    first.save()

    feed, cursor = _resumed(checkpoints)

    assert (cursor, checkpoints.load(STREAM)[0], len(feed.snapshot()["flows"][0]["agents"])) == (7, 7, 1)


def test_a_saved_board_of_another_schema_version_is_replayed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    checkpoints = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").checkpoints
    first = _feed_with_tasks()
    first.resume(checkpoints, STREAM, lambda cursor: False)
    first.save()
    monkeypatch.setattr(BoardSnapshot, "SCHEMA_VERSION", BoardSnapshot.SCHEMA_VERSION + 1)
    caplog.clear()

    with caplog.at_level(logging.INFO, logger="starpulse.board_feed"):
        feed, cursor = _resumed(checkpoints)

    assert (cursor, feed.snapshot()["flows"][0]["agents"], _start_lines(caplog)) == (
        None,
        [],
        ["StarPulse: replaying: the saved Board cannot be read"],
    )


class _Server:
    """A server that has served until it was stopped."""

    def run(self) -> None:
        pass


def test_a_stopped_server_saves_the_board_before_it_exits() -> None:
    store = _Store()
    feed = _feed_with_tasks()
    feed.resume(store, STREAM, lambda cursor: False)
    serve_until_stopped(_Server(), feed)  # type: ignore[arg-type]

    assert store.saved[STREAM][0] == 7


PULL = {"number": 7, "url": "https://github.com/acme/widgets/pull/7", "checks": "pass", "merged": False, "stale": False}


def test_a_saved_boards_pull_requests_are_in_the_first_snapshot_before_github_is_read() -> None:
    store = _Store()
    first = _feed_with_tasks()
    first.resume(store, STREAM, lambda cursor: False)
    first.set_pulls({"TASK-1": [PULL]}, {"records": {PULL["url"]: PULL}})
    first.save()

    feed, _ = _resumed(store)
    feed.expect("7-0")

    assert feed.snapshot()["pulls"] == {"TASK-1": [PULL]}
    assert feed.pull_answers() == {"records": {PULL["url"]: PULL}}


def test_new_pull_requests_are_saved_even_when_no_board_entry_was_read_since_the_last_save() -> None:
    store = _Store()
    first = _feed_with_tasks()
    first.resume(store, STREAM, lambda cursor: False)
    first.save()
    first.set_pulls({"TASK-1": [PULL]})
    first.save()

    assert store.saved[STREAM][1]["pulls"] == {"TASK-1": [PULL]}


def test_a_board_saved_before_pull_requests_were_kept_still_resumes_with_none() -> None:
    store = _Store({STREAM: (7, {"open": {}, "settled": {}, "assignees": {}})})

    feed, cursor = _resumed(store)

    assert cursor == 7
    assert feed.pull_answers() == {}


class _Lanes:
    def __init__(self) -> None:
        self.recorded: list[tuple[str, str]] = []

    def record_lane(self, event_id: str, task: str, status: str, at: float, *, event: object = None) -> bool:
        self.recorded.append((task, status))
        return True


def test_a_restored_task_that_drops_a_dependency_is_placed_and_its_lane_change_recorded() -> None:
    store = _Store()
    first = BoardFeed()
    first.put(BoardTask(id="TASK-1", team="demo", title="waits", lane="in_progress", dependencies=("TASK-0",)))
    first.put(BoardTask(id="TASK-2", team="demo", title="waits too", lane="in_progress", dependencies=("TASK-0",)))
    first.seen("7-0")
    first.resume(store, STREAM, lambda cursor: False)
    first.save()
    feed, _ = _resumed(store)
    lanes = _Lanes()
    feed.record_lanes(lanes)

    feed.put(BoardTask(id="TASK-1", team="demo", title="waits", lane="review", dependencies=()))
    feed.put(BoardTask(id="TASK-2", team="demo", title="waits too", lane="done"))

    assert lanes.recorded == [("TASK-1", "review"), ("TASK-2", "done")]
    assert {a["id"]: a["state"] for a in feed.snapshot()["flows"][0]["agents"]} == {
        "TASK-1": "review",
        "TASK-2": "done",
    }
