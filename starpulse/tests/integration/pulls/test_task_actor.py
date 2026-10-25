"""The task actor moves a task on the facts its lane waits on, as `starpulse/task-actor`, through the board's editor."""

import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine

from starpulse._internal.config.config import load
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse._internal.pulls.pull_events import RecordProjection
from starpulse._internal.pulls.pulls import PullStore
from starpulse._internal.pulls.task_actor import ACTOR, TaskActor
from starpulse._internal.server import server
from starpulse._internal.server.assembly import assemble
from starpulse.event_log.event_log import Entry, EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.tests.machines import MACHINES, ROLES
from starpulse.tests.task_actor_kit import (
    CHILD,
    CHILD_PR,
    GATED,
    MOVES,
    PARENT,
    PR_ONE,
    PR_TWO,
    REPOS,
    SHA,
    WAITS,
    WITHIN_S,
    Board,
    Criteria,
    Pins,
    pull,
    running,
    until,
)


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def test_a_review_task_whose_only_pr_merged_moves_to_done_and_no_other_task_is_derived(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Review", references=(PR_ONE,)),
        task("TASK-2", "Review", references=(PR_TWO,)),
        task("TASK-3", "Ready"),
    )
    store.save([pull(1, state="OPEN"), pull(2, state="OPEN")])
    actor = running(board, store, stop)
    derived = dict(actor.derivations)
    store.save([pull(1, state="MERGED")])

    projected = time.monotonic()
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-1", "done")])
    assert time.monotonic() - projected < WITHIN_S
    name, changes, comment, actor_name = board.writes[0]
    assert (changes, actor_name) == ({"status": "done"}, ACTOR)
    assert f"acme/trantor#1 merged as {SHA}" in str(comment)
    assert {name: count - derived[name] for name, count in actor.derivations.items()} == {
        "TASK-1": 1,
        "TASK-2": 0,
        "TASK-3": 0,
    }


def test_a_waiting_task_moves_to_ready_when_its_last_dependency_enters_done(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Done"),
        task("TASK-2", "In Progress"),
        task("TASK-3", "Waiting", dependencies=("TASK-1", "TASK-2")),
    )
    running(board, store, stop)
    assert board.moved() == []

    board.put(task("TASK-2", "Done"))

    assert until(lambda: board.moved() == [("TASK-3", "ready")])
    assert board.writes[0][3] == ACTOR


def test_a_review_task_stays_while_its_parent_pr_is_open_after_its_child_pr_closes(
    store: PullStore, stop: threading.Event
) -> None:
    feed = BoardFeed()
    board = Board(feed, task("TASK-1", "Review", references=(PR_ONE, PR_TWO)))
    store.save([pull(1, state="OPEN"), pull(2, state="CLOSED")])  # a poll read the child closed before the event
    actor = running(board, store, stop)
    event = {"event_id": "e1", "machine": "github-pull-request", "event": "PR_CLOSED", "task": "TASK-1"}
    event |= {"time": str(time.time() + 60), "repository": "acme/trantor", "pr": "2"}

    RecordProjection(store, feed).handle(Entry(1, "machine:events", "e1", event, time.time()))
    actor.pulls_changed()

    assert [record["state"] for record in store.find(repo="acme/trantor", number=1)] == ["OPEN"]
    assert board.moved() == []


def test_a_ready_task_with_an_unresolved_dependency_moves_to_waiting(store: PullStore, stop: threading.Event) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "In Progress"),
        task("TASK-2", "Ready", dependencies=("TASK-1",)),
        task("TASK-3", "Ready"),
    )

    running(board, store, stop)

    assert until(lambda: board.moved() == [("TASK-2", "waiting")])


def test_a_pin_bump_rule_holds_the_dependent_until_the_pin_bump_merge_projects(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Done", references=(CHILD_PR,)),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )
    store.save([pull(10, state="MERGED", repo="acme/starpulse", sha=CHILD)])
    actor = running(board, store, stop, repos=REPOS, pin_rule="pin-bump", pins=Pins())
    assert board.moved() == []
    assert "\nstarpulse_task_actor_pin_held 1\n" in actor.exposition()

    store.save([pull(11, state="MERGED", sha=PARENT, files=("starpulse",))])
    actor.pulls_changed()

    assert until(lambda: board.moved() == [("TASK-2", "ready")])
    assert "\nstarpulse_task_actor_pin_held 0\n" in actor.exposition()


def test_a_review_task_whose_pr_merged_while_the_server_was_down_moves_on_start(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Review", references=(PR_ONE,)), task("TASK-2", "Review"))
    store.save([pull(1, state="MERGED")])

    actor = running(board, store, stop)

    assert board.moved() == [("TASK-1", "done")]
    assert actor.derivations["TASK-2"] == 1  # every open task is derived once on start


def test_criteria_move_a_gated_task_both_ways_each_time_the_evaluators_result_goes_stale(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(BoardFeed(), task("TASK-1", "Waiting", description=GATED), task("TASK-2", "Waiting"))
    evaluate = Criteria("unmet")
    running(board, store, stop, evaluate=evaluate, fresh_s=0.05)
    assert board.moved() == []

    evaluate.status = "met"

    assert until(lambda: board.moved() == [("TASK-1", "ready")])
    assert board.writes[0][3] == ACTOR
    evaluate.status = "unmet"
    assert until(lambda: board.moved() == [("TASK-1", "ready"), ("TASK-1", "waiting")])
    assert "TASK-2" not in evaluate.asked  # a task with no Start Criteria is never evaluated


def test_an_adapter_hold_withholds_deps_done_with_its_reason_until_a_task_is_created(
    store: PullStore, stop: threading.Event
) -> None:
    held = {"TASK-2": ['"Slice three" has no task']}
    board = Board(BoardFeed(), task("TASK-1", "Done"), task("TASK-2", "Waiting", dependencies=("TASK-1",)))
    running(board, store, stop, holds=lambda name: held.get(name, []))
    assert board.moved() == []
    assert board.comments() == [("TASK-2", 'Held from Ready: "Slice three" has no task.')]

    held.clear()
    board.put(task("TASK-3", "Ready", title="Slice three"))

    assert until(lambda: board.moved() == [("TASK-2", "ready")])
    assert len(board.comments()) == 1  # the reason is written once, not on every derivation


def test_a_restarted_actor_does_not_write_the_hold_comment_the_task_already_holds(
    store: PullStore, stop: threading.Event, tmp_path: Path
) -> None:
    tasks = tmp_path / ".starpulse" / "board" / "tasks"
    tasks.mkdir(parents=True)
    (tasks.parent / "config.yml").write_text("project_name: Trantor\n")
    path = tasks / "task-2 - Held.md"
    path.write_text(
        "---\nid: task-2\ntitle: Held\nstatus: Waiting\ndependencies:\n  - task-1\n---\n\n## Description\n\nHeld.\n"
    )
    edit = assemble(load(None), tmp_path, None, ())[0].edit
    reason = ['"Slice three" has no task']

    for _ in range(2):  # the second pass is the restart: a new actor, an empty in-memory memo
        board = Board(BoardFeed(), task("task-1", "Done"), task("task-2", "Waiting", dependencies=("task-1",)))
        actor = TaskActor(board.feed, store, edit, WAITS, MOVES, holds=lambda name: reason)
        actor.start(stop)
        assert actor.ready.wait(WITHIN_S)

    assert path.read_text().count('Held from Ready: "Slice three" has no task.') == 1


class _BlockedProjection:
    """`PullRequests` whose refresh is a pin walk that has not returned."""

    release = threading.Event()

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def refresh(self) -> None:
        self.release.wait(WITHIN_S * 10)


class _Sync:
    projects: list[Callable[[], None]] = []

    def __init__(self, *args: object, project: Callable[[], None], **kwargs: object) -> None:
        self.projects.append(project)

    def run_forever(self) -> None:
        pass


def test_a_store_save_moves_the_task_while_the_projection_is_still_blocked(
    store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    board = Board(feed, task("TASK-1", "Review", references=(PR_ONE,)))
    store.save([pull(1, state="OPEN")])
    delivery = SimpleNamespace(edit=board.edit, waits=WAITS, evaluate=None, holds=None)
    monkeypatch.setattr(server.shutil, "which", lambda name: name)
    monkeypatch.setattr(server, "moves_of", lambda machine: MOVES)
    monkeypatch.setattr(server, "PullRequests", _BlockedProjection)
    monkeypatch.setattr(server, "PullSync", _Sync)
    monkeypatch.setattr(_Sync, "projects", [])
    monkeypatch.setattr(_BlockedProjection, "release", threading.Event())
    actor, _ = server.start_delivery(replace(load(None), task_actor=True), delivery, feed, None, store, Pins(), stop)
    assert actor.ready.wait(WITHIN_S)
    projection = threading.Thread(target=_Sync.projects[0], daemon=True)
    projection.start()

    store.save([pull(1, state="MERGED")])

    moved = until(lambda: board.moved() == [("TASK-1", "done")])
    still_projecting = projection.is_alive()
    _BlockedProjection.release.set()
    assert (moved, still_projecting) == (True, True)


def test_a_merge_of_a_pr_added_after_startup_moves_the_task_to_done(
    tmp_path: Path, store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine
    events = EventStore(engine)
    created = NewEvent(
        type="TaskCreated", payload={"title": "Task", "state": "Review"}, actor="adin", writer="operator"
    )
    events.append("task", "TASK-1", 0, [created])
    Projector(engine, events).catch_up()
    feed = BoardFeed(roles=ROLES, machines=MACHINES, read_model=ReadModel(engine))
    board = Board(feed)
    store.save([pull(1, state="OPEN")])
    delivery = SimpleNamespace(edit=board.edit, waits=WAITS, evaluate=None, holds=None)
    monkeypatch.setattr(server.shutil, "which", lambda name: name)
    monkeypatch.setattr(server, "moves_of", lambda machine: MOVES)
    monkeypatch.setattr(server, "PullRequests", _BlockedProjection)
    monkeypatch.setattr(server, "PullSync", _Sync)
    monkeypatch.setattr(_Sync, "projects", [])
    monkeypatch.setattr(_BlockedProjection, "release", threading.Event())
    actor, _ = server.start_delivery(replace(load(None), task_actor=True), delivery, feed, None, store, Pins(), stop)
    assert actor.ready.wait(WITHIN_S)
    projection = threading.Thread(target=_Sync.projects[0], daemon=True)
    projection.start()

    referenced = NewEvent(
        type="FieldsEdited", payload={"changes": {"references": [PR_ONE]}}, actor="adin", writer="operator"
    )
    events.append("task", "TASK-1", 1, [referenced])
    Projector(engine, events).catch_up()
    feed.follow_read_model()  # the page's follow publishes the changed task to the actor, as the server does
    store.save([pull(1, state="MERGED")])

    moved = until(lambda: board.moved() == [("TASK-1", "done")])
    still_projecting = projection.is_alive()
    _BlockedProjection.release.set()
    assert (moved, still_projecting) == (True, True)


def test_a_read_model_task_whose_cited_pr_merged_before_startup_moves_to_done(
    tmp_path: Path, store: PullStore, stop: threading.Event, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine
    events = EventStore(engine)
    created = NewEvent(
        type="TaskCreated", payload={"title": "Task", "state": "Review"}, actor="adin", writer="operator"
    )
    referenced = NewEvent(
        type="FieldsEdited", payload={"changes": {"references": [PR_ONE]}}, actor="adin", writer="operator"
    )
    events.append("task", "TASK-1", 0, [created, referenced])
    Projector(engine, events).catch_up()
    feed = BoardFeed(roles=ROLES, machines=MACHINES, read_model=ReadModel(engine))
    board = Board(feed)
    store.save([pull(1, state="MERGED")])
    delivery = SimpleNamespace(edit=board.edit, waits=WAITS, evaluate=None, holds=None)
    monkeypatch.setattr(server.shutil, "which", lambda name: name)
    monkeypatch.setattr(server, "moves_of", lambda machine: MOVES)
    monkeypatch.setattr(server, "PullRequests", _BlockedProjection)
    monkeypatch.setattr(server, "PullSync", _Sync)
    monkeypatch.setattr(_Sync, "projects", [])
    monkeypatch.setattr(_BlockedProjection, "release", threading.Event())
    _BlockedProjection.release.set()
    server.start_delivery(replace(load(None), task_actor=True), delivery, feed, None, store, Pins(), stop)

    assert until(lambda: board.moved() == [("TASK-1", "done")])
