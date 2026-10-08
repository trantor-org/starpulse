"""Each lifecycle machine's tasks, held in memory from machine:events entries."""

import itertools
import json
import threading
import time
from pathlib import Path
from typing import Literal

import pytest

from starpulse.board_feed import BoardFeed, follow
from starpulse.contracts.adapters import BoardTask
from starpulse.domain.transitions import Table
from starpulse.machine_tasks import MachineTasks
from starpulse.store import events as machine_events
from starpulse.store.event_log import EventLog
from starpulse.tests.machines import FLOWS, MACHINES

_ids = itertools.count(1)


def _entry(machine: str, event: str, *, task: str | None = "PROJ-7", run: str | None = None, at: float | None = None):
    """`(stream id, fields)` as the consumer's handler receives a `machine_events.publish` entry."""
    fields = {
        "machine": machine,
        "event": event,
        "actor": "agent",
        "time": str(time.time() if at is None else at),
        "event_id": f"e{next(_ids)}",
        **({"task": task} if task and not run else {}),
        **({"run": run} if run else {}),
    }
    return f"{next(_ids)}-0", fields


def _feed(window_s: float | None = None) -> tuple[BoardFeed, MachineTasks]:
    feed = BoardFeed(window_s, machines=MACHINES)
    return feed, MachineTasks(feed)


def _agents(feed: BoardFeed, flow: str) -> list[dict]:
    return next(f["agents"] for f in feed.snapshot()["flows"] if f["name"] == flow)


def test_every_machine_level_is_in_the_snapshot_beside_the_board_with_its_tasks() -> None:
    feed, tasks = _feed()
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-1", at=100.0))
    tasks.handle_entry(*_entry("authoring-skills", "GUIDANCE_READ", task="PROJ-2", at=101.0))

    flows = feed.snapshot()["flows"]

    assert [f["name"] for f in flows] == list(FLOWS)
    assert [(a["id"], a["state"]) for a in _agents(feed, "in-progress")] == [("PROJ-1", "worktree_ready")]
    assert [a["id"] for a in _agents(feed, "authoring-skills")] == ["PROJ-2"]
    assert _agents(feed, "board") == []


def test_machines_given_to_the_placer_replace_the_feeds_and_one_it_was_not_given_places_nothing() -> None:
    feed = BoardFeed(machines=MACHINES)
    tasks = MachineTasks(feed, machines={name: m for name, m in MACHINES.items() if name != "in-progress"})
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-1", at=100.0))
    tasks.handle_entry(*_entry("authoring-skills", "GUIDANCE_READ", task="PROJ-2", at=101.0))

    assert (_agents(feed, "in-progress"), [a["id"] for a in _agents(feed, "authoring-skills")]) == ([], ["PROJ-2"])


def test_a_task_carries_its_step_count_and_the_trail_of_its_moves() -> None:
    feed, tasks = _feed()
    for at, event in ((100.0, "WORKTREE_READY"), (101.0, "AC_CHECKPOINTED"), (102.0, "DOCS_RECONCILED")):
        tasks.handle_entry(*_entry("in-progress", event, at=at))

    (agent,) = _agents(feed, "in-progress")

    assert (agent["id"], agent["task"], agent["state"], agent["steps"], agent["active"]) == (
        "PROJ-7",
        "PROJ-7",
        "docs_reconciled",
        3,
        102.0,
    )
    assert agent["trail"] == [
        {"state": "worktree_ready", "event": "WORKTREE_READY", "at": 100.0},
        {"state": "checkpointed", "event": "AC_CHECKPOINTED", "at": 101.0},
        {"state": "docs_reconciled", "event": "DOCS_RECONCILED", "at": 102.0},
    ]


def test_a_move_reaches_every_subscriber_as_a_delta_with_the_tasks_new_place() -> None:
    feed, tasks = _feed()
    _, changes = feed.subscribe()

    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", at=100.0))

    kind, delta = changes.get_nowait()
    assert kind == "move"
    assert (delta["flow"], delta["id"], delta["agent"]["state"]) == ("in-progress", "PROJ-7", "worktree_ready")
    assert changes.empty()


def test_a_trail_keeps_only_the_latest_steps() -> None:
    feed, tasks = _feed()
    for i in range(30):
        tasks.handle_entry(*_entry("in-progress", "AC_CHECKPOINTED", at=100.0 + i))

    (agent,) = _agents(feed, "in-progress")

    assert (agent["steps"], len(agent["trail"]), agent["trail"][-1]["at"]) == (30, 12, 129.0)


@pytest.mark.parametrize(
    ("events", "state"),
    [
        (["PUSHED"], "pushed"),  # the earlier events fell out of the stream's retention
        (["WORKTREE_READY", "COMMITTED"], "committed"),  # the lint steps were never run
        (["WORKTREE_READY", "LINT_RED"], "worktree_ready"),  # an event that only loops leaves the task where it is
        (
            ["WORKTREE_READY", "REVIEW_RECORDED", "WORKTREE_READY"],
            "worktree_ready",
        ),  # work begins again after a final state
    ],
)
def test_an_event_the_task_cannot_take_from_its_state_still_places_it_where_the_event_leads(
    events: list[str], state: str
) -> None:
    feed, tasks = _feed()
    for i, event in enumerate(events):
        tasks.handle_entry(*_entry("in-progress", event, at=100.0 + i))

    assert [a["state"] for a in _agents(feed, "in-progress")] == [state]


def test_a_loop_the_state_allows_counts_as_a_step_and_a_delta_without_moving_the_task() -> None:
    feed, tasks = _feed()
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", at=100.0))
    _, changes = feed.subscribe()

    tasks.handle_entry(*_entry("in-progress", "RED_WRONG", at=101.0))

    assert _agents(feed, "in-progress")[0]["state"] == "worktree_ready"
    assert changes.get_nowait()[1]["agent"]["steps"] == 2


@pytest.mark.parametrize(
    "entry",
    [
        _entry("board", "READY"),
        _entry("pull-request", "PUSHED"),
        _entry("in-progress", "NOT_AN_EVENT"),
        _entry("in-progress", "WORKTREE_READY", task=None, run="s-1"),
        ("1-0", {"machine": "in-progress", "event": "WORKTREE_READY", "task": "PROJ-7", "time": "soon"}),
        ("1-0", {"machine": "in-progress", "task": "PROJ-7", "time": "1"}),
        ("1-0", {}),
    ],
    ids=["board", "machine-the-view-lacks", "event-the-machine-lacks", "run-keyed", "bad-time", "no-event", "empty"],
)
def test_an_entry_that_is_no_task_event_of_a_drawn_machine_is_dropped(entry: tuple) -> None:
    feed, tasks = _feed()
    _, changes = feed.subscribe()

    tasks.handle_entry(*entry)

    assert all(not f["agents"] for f in feed.snapshot()["flows"])
    assert changes.empty()


def test_a_task_whose_latest_move_is_older_than_the_window_is_left_out_of_a_snapshot() -> None:
    feed, tasks = _feed(window_s=3600)
    now = time.time()
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-1", at=now - 7200))
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-2", at=now - 60))

    assert [a["id"] for a in _agents(feed, "in-progress")] == ["PROJ-2"]


def test_tasks_fed_from_the_event_log_replay_its_retained_machine_events_then_follow_new_ones_and_turn_ready(
    tmp_path: Path,
) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    _, fields = _entry("in-progress", "WORKTREE_READY", task="PROJ-1")
    log.append(machine_events.STREAM, fields)
    log.append("runs:events", {"phase": "start"})  # another stream's row
    feed, tasks = _feed()
    stop = threading.Event()

    follow(tasks, log, machine_events.STREAM, tasks.handle_entry, stop=stop, interval=0.01)
    assert tasks.ready.wait(5)
    log.append(machine_events.STREAM, _entry("in-progress", "RED_PROVEN", task="PROJ-1")[1])
    deadline = time.monotonic() + 5
    while [a["state"] for a in _agents(feed, "in-progress")] != ["red_proven"]:
        assert time.monotonic() < deadline, "the new event never reached the tasks"
        time.sleep(0.01)
    stop.set()

    assert [a["id"] for a in _agents(feed, "in-progress")] == ["PROJ-1"]


def test_the_tasks_become_ready_once_the_last_entry_held_at_start_has_been_read() -> None:
    _, tasks = _feed()
    first, second = _entry("in-progress", "WORKTREE_READY"), _entry("in-progress", "AC_CHECKPOINTED")

    tasks.expect(second[0])
    tasks.handle_entry(*first)
    assert not tasks.ready.is_set()
    tasks.handle_entry(*second)

    assert tasks.ready.is_set()


@pytest.mark.parametrize(("last_id", "ready"), [("0-0", True), ("1-0", False), ("0-1", False)])
def test_nothing_has_been_read_before_the_first_entry_so_only_an_empty_stream_is_ready(
    last_id: str, ready: bool
) -> None:
    _, tasks = _feed()

    tasks.expect(last_id)

    assert tasks.ready.is_set() is ready


def test_a_task_is_placed_with_the_whole_agent_the_page_overlays_the_board_fields_on() -> None:
    feed, tasks = _feed()
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-9", at=100.0))

    assert _agents(feed, "in-progress") == [
        {
            "id": "PROJ-9",
            "title": "PROJ-9",
            "model": "",
            "task": "PROJ-9",
            "state": "worktree_ready",
            "steps": 1,
            "trail": [{"state": "worktree_ready", "event": "WORKTREE_READY", "at": 100.0}],
            "active": 100.0,
        }
    ]


def test_a_task_active_exactly_at_the_window_edge_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("starpulse.board_feed.time.time", lambda: 1000.0)
    feed, tasks = _feed(window_s=100)
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", at=900.0))

    assert [a["id"] for a in _agents(feed, "in-progress")] == ["PROJ-7"]


def _machine() -> dict:
    """a (initial) -> b -> c; c loops; d and e lead on; f is final; JUMP leads from a to b and from c to d."""
    edges = [
        ("GO", "a", "b"),
        ("NEXT", "b", "c"),
        ("SPLIT", "b", "c"),
        ("SPLIT", "b", "d"),
        ("LOOP", "c", "c"),
        ("ONLY", "c", "e"),
        ("JUMP", "a", "b"),
        ("JUMP", "c", "d"),
        ("DONE", "e", "f"),
    ]
    return {
        "states": [
            {"id": s, "name": s, "initial": s == "a", "final": s == "f"} for s in ("a", "b", "c", "d", "e", "f")
        ],
        "transitions": [{"source": s, "target": t, "event": e} for e, s, t in edges],
    }


def test_a_table_holds_the_initial_state_the_final_ones_and_each_events_targets_by_source() -> None:
    table = Table(_machine())

    assert (table.initial, table.finals) == ("a", {"f"})
    assert {event: dict(sources) for event, sources in table.moves.items()} == {
        "GO": {"a": {"b"}},
        "NEXT": {"b": {"c"}},
        "SPLIT": {"b": {"c", "d"}},
        "LOOP": {"c": {"c"}},
        "ONLY": {"c": {"e"}},
        "JUMP": {"a": {"b"}, "c": {"d"}},
        "DONE": {"e": {"f"}},
    }


@pytest.mark.parametrize(
    ("current", "event", "target"),
    [
        ("a", "GO", "b"),  # an event the state allows leads where the machine says
        (None, "GO", "b"),  # a task not yet placed begins at the initial state
        ("b", "SPLIT", None),  # an event with two targets from the state leaves it nowhere definite
        ("f", "JUMP", "b"),  # a task in a final state begins again from the initial one
        ("e", "JUMP", None),  # not allowed from here, and it leads to two different states from the others
        ("a", "ONLY", "e"),  # not allowed from here, and it leads to one state from the others
        ("a", "LOOP", "a"),  # an event that only loops leaves the task where it is
        (None, "LOOP", "a"),  # and a task not yet placed at the initial state
        ("a", "NOT_AN_EVENT", None),
    ],
)
def test_a_table_places_a_task_by_the_event_and_the_state_it_is_in(
    current: str | None, event: str, target: str | None
) -> None:
    assert Table(_machine()).target(current, event) == target


def test_a_snapshot_is_json_the_page_can_read() -> None:
    feed, tasks = _feed()
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY"))

    json.dumps(feed.snapshot())


@pytest.mark.parametrize("settled", ["completed", "archived"])
def test_a_machine_task_keeps_the_assignee_of_its_board_task_once_that_task_is_settled(
    settled: Literal["completed", "archived"],
) -> None:
    feed, tasks = _feed()
    feed.put(BoardTask(id="PROJ-9", team="demo", title="t", lane="in_progress", assignee="@agent-deep-medium"))
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-9", at=100.0))
    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-8", at=100.0))

    feed.put(
        BoardTask(id="PROJ-9", team="demo", title="t", lane="done", assignee="@agent-deep-medium", settled=settled)
    )
    feed.put(
        BoardTask(id="PROJ-8", team="demo", title="t", lane="done", assignee="@agent-standard-high", settled=settled)
    )

    models = {a["id"]: a["model"] for a in _agents(feed, "in-progress")}
    assert models == {"PROJ-9": "@agent-deep-medium", "PROJ-8": "@agent-standard-high"}


def test_a_move_delta_carries_the_assignee_of_a_settled_board_task() -> None:
    feed, tasks = _feed()
    feed.put(
        BoardTask(
            id="PROJ-9", team="demo", title="t", lane="done", assignee="@agent-standard-high", settled="completed"
        )
    )
    _, changes = feed.subscribe()

    tasks.handle_entry(*_entry("in-progress", "WORKTREE_READY", task="PROJ-9", at=100.0))

    kind, data = changes.get_nowait()
    assert (kind, data["agent"]["model"]) == ("move", "@agent-standard-high")
