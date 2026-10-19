"""The Board child publishes the Board it places to the event log; the other contexts read that replica."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import delete

from starpulse._internal.board import replica
from starpulse._internal.board.seam import Board
from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.eventlog.tables import events
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse.contracts import BoardTask

WAIT_S = 5.0
KEY = "board:replica@test"


def _eventually(ready: Callable[[], object]) -> bool:
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    stopping = threading.Event()
    yield stopping
    stopping.set()


def _task(task_id: str = "T-1", lane: str = "to_do", **fields: object) -> BoardTask:
    return BoardTask(id=task_id, team="demo", title="t", lane=lane, **fields)


def _child(log: EventLog) -> replica.Publisher:
    """A Board child's feed with the replica publisher the adapter reports to."""
    publisher = replica.Publisher(BoardFeed(clock=lambda: 100.0), log, KEY, clock=lambda: 100.0)
    publisher.begin()
    return publisher


def _reader(log: EventLog, stop: threading.Event) -> BoardFeed:
    feed = BoardFeed(clock=lambda: 100.0)  # the child's clock: a done task is hot on both sides
    feed.await_stream()
    replica.follow(feed, log, KEY, stop)
    return feed


def _states(feed: BoardFeed) -> dict[str, str]:
    return {agent["id"]: agent["state"] for agent in feed.snapshot()["flows"][0]["agents"]}


def _published(log: EventLog) -> list[dict]:
    """Every entry of the replica stream, oldest first."""
    tail = Tail(log, replica.REPLICA_STREAM)
    return [{**entry.fields, "entry": entry.id} for entry in tail.poll()]


def _deltas(log: EventLog) -> list[dict]:
    return [entry for entry in _published(log) if "ready" not in entry]


def test_a_reader_draws_the_tasks_the_child_places(log: EventLog, stop: threading.Event) -> None:
    child = _child(log)
    reader = _reader(log, stop)

    child.put(_task("T-1", "to_do"))
    child.put(_task("T-2", "in_progress"))

    assert _eventually(lambda: _states(reader) == {"T-1": "to_do", "T-2": "in_progress"})


def test_a_reader_follows_a_task_the_child_moves_and_one_it_retracts(log: EventLog, stop: threading.Event) -> None:
    child = _child(log)
    reader = _reader(log, stop)
    child.put(_task("T-1", "to_do"))
    child.put(_task("T-2", "to_do"))

    child.put(_task("T-1", "review"))
    child.retract("T-2")

    assert _eventually(lambda: _states(reader) == {"T-1": "review"})


def test_a_rescan_that_changes_nothing_publishes_nothing_and_a_change_publishes_once(
    log: EventLog,
) -> None:
    child = _child(log)
    child.put(_task("T-1", "to_do"))
    child.put(_task("T-2", "to_do"))
    first = _deltas(log)

    for _ in range(3):  # the adapter's rescan puts every task again
        child.put(_task("T-1", "to_do"))
        child.put(_task("T-2", "to_do"))
    assert _deltas(log) == first

    child.put(_task("T-1", "review"))
    child.put(_task("T-1", "review"))
    assert len(_deltas(log)) == len(first) + 1


def test_a_change_the_page_does_not_draw_is_published_for_the_search_index(
    log: EventLog,
) -> None:
    child = _child(log)
    child.put(_task("T-1", "to_do", description="before"))

    child.put(_task("T-1", "to_do", description="after"))

    assert len(_deltas(log)) == 2


def test_a_publish_that_failed_is_made_by_the_next_put_of_the_task(
    log: EventLog, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = _child(log)
    appended = log.append
    down = iter([True])  # the first append finds the database locked

    def flaky(stream: str, fields: dict, **kwargs: object) -> int | None:
        return None if next(down, False) else appended(stream, fields, **kwargs)

    monkeypatch.setattr(log, "append", flaky)
    child.put(_task("T-1", "to_do"))
    assert _deltas(log) == []

    child.put(_task("T-1", "to_do"))  # the rescan

    assert len(_deltas(log)) == 1


def test_a_retract_that_failed_is_made_by_the_next_scan(
    log: EventLog, monkeypatch: pytest.MonkeyPatch, stop: threading.Event
) -> None:
    child = _child(log)
    reader = _reader(log, stop)
    child.put(_task("T-1", "to_do"))
    assert _eventually(lambda: _states(reader) == {"T-1": "to_do"})
    appended = log.append
    down = iter([True])

    def flaky(stream: str, fields: dict, **kwargs: object) -> int | None:
        return None if next(down, False) else appended(stream, fields, **kwargs)

    monkeypatch.setattr(log, "append", flaky)
    child.retract("T-1")
    child.keep_source({"files": {}})  # the adapter notes the scan it just finished

    assert _eventually(lambda: _states(reader) == {})


def test_a_reader_is_ready_once_the_child_has_read_its_board(log: EventLog, stop: threading.Event) -> None:
    child = _child(log)
    reader = _reader(log, stop)
    child.put(_task("T-1", "to_do"))
    assert not reader.ready.wait(0.3)  # the child is still on its first scan

    child.expect("0-0")

    assert reader.ready.wait(WAIT_S)
    assert _states(reader) == {"T-1": "to_do"}


def test_a_reader_started_after_the_child_is_ready_once_it_has_read_what_the_log_holds(
    log: EventLog, stop: threading.Event
) -> None:
    child = _child(log)
    child.put(_task("T-1", "to_do"))
    child.expect("0-0")

    reader = _reader(log, stop)

    assert reader.ready.wait(WAIT_S)
    assert _states(reader) == {"T-1": "to_do"}


def test_a_restarted_child_repeats_no_publish_and_a_reader_keeps_its_view(log: EventLog, stop: threading.Event) -> None:
    first = _child(log)
    reader = _reader(log, stop)
    first.put(_task("T-1", "to_do"))
    first.put(_task("T-2", "review"))
    first.expect("0-0")
    first.save()
    first.put(_task("T-3", "to_do"))  # published after the child's last save
    assert _eventually(lambda: len(_states(reader)) == 3)
    before = _published(log)

    second = _child(log)  # the restart: it resumes the saved Board and the deltas after its cursor
    for task in (_task("T-1", "to_do"), _task("T-2", "review"), _task("T-3", "to_do")):
        second.put(task)  # the adapter's first scan puts every task again
    second.expect("0-0")

    assert _deltas(log) == [entry for entry in before if "ready" not in entry]
    assert _states(reader) == {"T-1": "to_do", "T-2": "review", "T-3": "to_do"}
    second.put(_task("T-1", "done"))
    assert _eventually(lambda: _states(reader)["T-1"] == "done")


def test_a_restarted_child_publishes_a_task_that_changed_while_it_was_down(
    log: EventLog, stop: threading.Event
) -> None:
    first = _child(log)
    first.put(_task("T-1", "to_do"))
    first.expect("0-0")
    first.save()
    reader = _reader(log, stop)

    second = _child(log)
    second.put(_task("T-1", "review"))
    second.expect("0-0")

    assert _eventually(lambda: _states(reader) == {"T-1": "review"})


def test_a_reader_resumes_the_saved_board_when_the_log_no_longer_holds_its_deltas(
    log: EventLog, stop: threading.Event
) -> None:
    child = _child(log)
    child.put(_task("T-1", "to_do"))
    child.expect("0-0")
    child.save()
    with log.engine.begin() as db:  # the retention pruned the stream
        db.execute(delete(events))

    reader = _reader(log, stop)

    assert reader.ready.wait(WAIT_S)
    assert _states(reader) == {"T-1": "to_do"}


def test_a_reader_never_writes_the_saved_board(log: EventLog, stop: threading.Event) -> None:
    child = _child(log)
    child.put(_task("T-1", "to_do"))
    child.expect("0-0")
    child.save()
    saved = log.load_board_state(KEY)
    reader = _reader(log, stop)
    assert reader.ready.wait(WAIT_S)
    child.put(_task("T-2", "to_do"))
    assert _eventually(lambda: len(_states(reader)) == 2)

    reader.save()

    assert log.load_board_state(KEY) == saved


def test_the_child_saves_nothing_before_it_has_read_its_board(log: EventLog) -> None:
    child = _child(log)
    child.put(_task("T-1", "to_do"))

    child.save()

    assert log.load_board_state(KEY) is None


def test_the_child_hands_the_adapter_the_source_it_kept_and_not_its_own_bookkeeping(
    log: EventLog,
) -> None:
    child = _child(log)
    child.put(_task("T-1", "to_do"))
    child.keep_source({"files": {"a.md": "fp"}})
    child.expect("0-0")
    child.save()

    restarted = _child(log)

    assert restarted.source() == {"files": {"a.md": "fp"}}


class Lanes:
    """A history that keeps every lane change it is handed."""

    def __init__(self) -> None:
        self.recorded: list[str] = []

    def record_lane(self, event_id: str, task: str, status: str, at: float, *, event: object = None) -> bool:
        self.recorded.append(event_id)
        return True


def test_a_feed_that_is_not_live_records_no_lane_as_it_places_but_still_repairs_the_history() -> None:
    lanes = Lanes()
    feed = BoardFeed(clock=lambda: 100.0)
    feed.record_lanes(lanes, live=False)

    feed.put(_task("T-1", "to_do"))
    assert lanes.recorded == []

    assert feed.reconcile_lanes([("T-1@review@50.0", "T-1", "review", 50.0)]) == 1


def test_a_live_feed_records_the_lane_it_places() -> None:
    lanes = Lanes()
    feed = BoardFeed(clock=lambda: 100.0)
    feed.record_lanes(lanes)

    feed.put(_task("T-1", "to_do"))

    assert lanes.recorded == ["T-1@to_do@100.0"]


CONFIG = load(None)


def _board(starts: list, attached: list, state_key: str = "projection") -> Board:
    return Board(
        machines=lambda qualify, workflows: {},
        start=lambda feed, group, log: starts.append((feed, group, log)),
        state_key=lambda: state_key,
        attach=attached.append,
    )


def test_the_checkpoint_key_follows_the_projection_the_adapter_names() -> None:
    same = replica.key(_board([], []), CONFIG)

    assert replica.key(_board([], []), CONFIG) == same
    assert replica.key(_board([], [], "another projection"), CONFIG) != same
    assert same.startswith(f"{replica.REPLICA_STREAM}@")


def test_a_reading_context_attaches_to_the_log_and_follows_the_replica_instead_of_starting_the_board(
    log: EventLog, stop: threading.Event
) -> None:
    starts: list = []
    attached: list = []
    board = _board(starts, attached)
    feed = BoardFeed()

    replica.read(board, feed, "starpulse-runs", log, CONFIG, stop, local=False)
    child = replica.Publisher(BoardFeed(), log, replica.key(board, CONFIG))
    child.begin()
    child.put(_task("T-1", "to_do"))
    child.expect("0-0")

    assert feed.ready.wait(WAIT_S)
    assert _states(feed) == {"T-1": "to_do"}
    assert starts == []
    assert attached == [log]


def test_a_context_with_a_local_board_starts_the_adapter_on_its_own_feed(log: EventLog, stop: threading.Event) -> None:
    starts: list = []
    feed = BoardFeed()

    replica.read(_board(starts, []), feed, "starpulse-runs", log, CONFIG, stop, local=True)

    assert starts == [(feed, "starpulse-runs", log)]
    assert not feed.ready.is_set()  # nothing follows the replica


def test_the_board_child_starts_the_adapter_on_a_publisher_that_has_resumed(
    log: EventLog,
) -> None:
    starts: list = []
    board = _board(starts, [])

    publisher = replica.publish(board, BoardFeed(), "starpulse-board", log, CONFIG)

    [(started, group, _)] = starts
    assert started is publisher
    assert group == "starpulse-board"
    publisher.put(_task("T-1", "to_do"))
    assert len(_deltas(log)) == 1


def test_replica_legacy_key_entry_is_applied_with_the_holder_as_assignee(log: EventLog, stop: threading.Event) -> None:
    retained = _task("T-1", "review", profile="agent-a", assignee="s-1").model_dump(mode="json")
    retained["assignee"], retained["holder"] = retained["profile"], retained.pop("assignee")
    del retained["profile"]
    log.append(replica.REPLICA_STREAM, {"id": "T-1", "digest": "d", "task": json.dumps(retained)})
    log.append(replica.REPLICA_STREAM, {"id": "T-2", "digest": "d", "task": '{"unknown_key": 1}'})
    reader = _reader(log, stop)

    assert _eventually(lambda: _states(reader) == {"T-1": "review"})
    assert reader.snapshot()["flows"][0]["agents"][0]["assignee"] == "s-1"
