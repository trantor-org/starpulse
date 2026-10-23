"""The page draws the Board from the read model when the feed is given one: live Tasks are a query, archived Tasks are
paged, and no Task is held in the feed."""

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine

from starpulse._internal.board.view import board_columns
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.machines.transitions import board_machine
from starpulse._internal.readmodel.projector import Projector
from starpulse._internal.readmodel.read_model import ReadModel
from starpulse._internal.store import EventStore, NewEvent


@pytest.fixture
def engine() -> Iterator[Engine]:
    with tempfile.TemporaryDirectory() as directory:
        built = EventLog(f"sqlite:///{Path(directory) / 'events.sqlite'}").engine
        yield built
        built.dispose()


def _new(type: str, **payload: object) -> NewEvent:
    return NewEvent(type=type, payload=payload, actor="adin", writer="operator")


def _append(engine: Engine, number: int, state: str, *, archived: bool = False) -> None:
    events = [_new("TaskCreated", title=f"Task {number}", description="", state=state, labels=["kind-execute"])]
    if archived:
        events.append(_new("Archived"))
    EventStore(engine).append("task", f"TASK-{number}", 0, events)


def _feed(engine: Engine, machines: dict | None = None) -> BoardFeed:
    Projector(engine, EventStore(engine)).catch_up()
    return BoardFeed(machines=machines, read_model=ReadModel(engine))


def _board(feed: BoardFeed) -> dict:
    return next(flow for flow in feed.snapshot()["flows"] if flow["name"] == "board")


def test_the_board_flow_draws_the_live_tasks_of_the_read_model(engine: Engine) -> None:
    _append(engine, 1, "Ready")
    _append(engine, 2, "In Progress")
    _append(engine, 3, "Done", archived=True)

    agents = _board(_feed(engine))["agents"]

    assert [(agent["id"], agent["title"], agent["state"]) for agent in agents] == [
        ("TASK-1", "Task 1", "ready"),
        ("TASK-2", "Task 2", "in_progress"),
    ]


def test_the_kanban_columns_hold_the_read_model_tasks_by_state_id(engine: Engine) -> None:
    _append(engine, 1, "To Do")
    _append(engine, 2, "In Progress")

    columns = board_columns(_feed(engine).snapshot(), lambda agent: True)["columns"]

    assert {column["state"]: [task["id"] for task in column["tasks"]] for column in columns if column["tasks"]} == {
        "to_do": ["TASK-1"],
        "in_progress": ["TASK-2"],
    }


def test_the_snapshot_lists_no_archived_task_and_the_archive_is_paged(engine: Engine) -> None:
    for number in range(1, 6):
        _append(engine, number, "Done", archived=True)
    feed = _feed(engine)

    assert feed.snapshot()["cold_done"] == []
    first, more = feed.cold_page(None, 2)
    assert len(first) == 2
    assert more
    rest, more = feed.cold_page(first[-1]["entered"], 10)
    assert {agent["id"] for agent in first + rest} == {f"TASK-{n}" for n in range(1, 6)}
    assert not more


def test_a_task_is_read_from_the_read_model_not_held(engine: Engine) -> None:
    _append(engine, 1, "Ready")
    feed = _feed(engine)

    task = feed.task("TASK-1")

    assert task is not None
    assert task["title"] == "Task 1"
    assert feed.task("TASK-9") is None


def _depending(engine: Engine, number: int, state: str, on: str) -> None:
    created = _new("TaskCreated", title=f"Task {number}", description="", state=state, labels=[], dependencies=[on])
    EventStore(engine).append("task", f"TASK-{number}", 0, [created])


def test_a_task_is_workable_once_its_dependencies_are_done(engine: Engine) -> None:
    _append(engine, 1, "Ready")
    _append(engine, 2, "done")
    _append(engine, 3, "Ready")
    _depending(engine, 4, "Ready", "TASK-1")
    _depending(engine, 5, "Ready", "TASK-2")

    agents = {agent["id"]: agent for agent in _board(_feed(engine))["agents"]}

    assert {task: agent["workable"] for task, agent in agents.items()} == {
        "TASK-1": True,
        "TASK-2": True,
        "TASK-3": True,
        "TASK-4": False,
        "TASK-5": True,
    }
    assert agents["TASK-4"]["workable_since"] is None
    assert agents["TASK-5"]["workable_since"] is not None


def test_a_live_task_is_held_and_an_archived_one_is_not(engine: Engine) -> None:
    _append(engine, 1, "Ready")
    _append(engine, 2, "Done", archived=True)
    feed = _feed(engine)

    held = feed.held("TASK-1")

    assert held is not None
    assert held["title"] == "Task 1"
    assert feed.held("TASK-2") is None
    assert feed.held("TASK-9") is None


class _Counting(ReadModel):
    snapshots = 0

    def snapshot(self, state: str | None = None) -> list:
        type(self).snapshots += 1
        return super().snapshot(state)


def test_the_board_is_queried_once_per_change_of_the_read_model(engine: Engine) -> None:
    _Counting.snapshots = 0
    _append(engine, 1, "Ready")
    Projector(engine, EventStore(engine)).catch_up()
    feed = BoardFeed(read_model=_Counting(engine))

    _board(feed)
    _board(feed)
    assert _Counting.snapshots == 1

    _append(engine, 2, "Ready")
    Projector(engine, EventStore(engine)).catch_up()

    assert [agent["id"] for agent in _board(feed)["agents"]] == ["TASK-1", "TASK-2"]
    assert _Counting.snapshots == 2


def test_a_task_is_done_when_the_read_model_has_it_in_the_done_state_archived_or_not(engine: Engine) -> None:
    _append(engine, 1, "Ready")
    _append(engine, 2, "done")
    _append(engine, 3, "done", archived=True)
    feed = _feed(engine)

    assert [feed.is_done(f"TASK-{n}") for n in (1, 2, 3, 9)] == [False, True, True, False]


def _deltas(subscriber: object) -> list[tuple[str, dict]]:
    return [subscriber.get_nowait() for _ in range(subscriber.qsize())]  # type: ignore[attr-defined]


def test_the_tasks_the_read_model_changed_are_published_as_deltas_once(engine: Engine) -> None:
    _append(engine, 1, "Ready")
    feed = _feed(engine)
    _, subscriber = feed.subscribe()
    _append(engine, 2, "Ready")
    _append(engine, 3, "Done", archived=True)
    Projector(engine, EventStore(engine)).catch_up()

    assert feed.follow_read_model() == 2
    assert feed.follow_read_model() == 0

    published = {data["id"]: data["agent"] for kind, data in _deltas(subscriber) if kind == "task"}
    assert set(published) == {"TASK-2", "TASK-3"}
    assert published["TASK-2"]["state"] == "ready"
    assert published["TASK-3"] is None


def test_a_ready_task_offers_the_board_machines_move_to_in_progress(engine: Engine) -> None:
    _append(engine, 1, "Ready")
    feed = _feed(engine, {"board": board_machine(("Ready", "In Progress", "Done"))})

    task = feed.task("TASK-1")

    assert task is not None
    assert task["moves"]["in_progress"]["allowed"] is True


def test_a_move_the_machine_writes_to_one_actor_offers_only_that_actor(engine: Engine) -> None:
    _append(engine, 1, "Ready")
    machine = board_machine(("Ready", "In Progress", "Done"))
    machine["writers"] = {"to_in_progress": [{"actor": "operator", "trigger": "claim"}]}
    feed = _feed(engine, {"board": machine})

    task = feed.task("TASK-1")

    assert task is not None
    assert task["moves"]["in_progress"]["writers"] == ("operator",)


def test_a_done_task_offers_no_moves(engine: Engine) -> None:
    _append(engine, 1, "Done")
    feed = _feed(engine, {"board": board_machine(("Ready", "In Progress", "Done"))})

    task = feed.task("TASK-1")

    assert task is not None
    assert task["moves"] == {}
