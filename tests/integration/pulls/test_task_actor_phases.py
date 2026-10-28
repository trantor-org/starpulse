"""The task actor advances an In Progress phase when the phase's skill machine reaches the state its link exits on."""

import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from starpulse.board.board_feed import BoardFeed
from starpulse.machine_engine.model.transitions import board_machine
from starpulse.pulls.pulls import PullStore
from starpulse.pulls.task_actor import ACTOR
from starpulse.runtime import server
from starpulse.runtime.adapter_kit import task
from starpulse.runtime.config import load

from tests.machines import STATUSES, flow
from tests.task_actor_kit import MOVES, WAITS, Board, Pins, running, until

PARENT = "in-progress"
#: The phase machine links the way `.starpulse/machines/in-progress.yaml` declares them.
LINKS = [
    {"state": "build", "machine": "build", "exits": {"docs_reconciled": "BUILD_DONE"}},
    {"state": "deliver", "machine": "deliver", "exits": {"pr_ready": "DELIVER_DONE"}},
    {"state": "review_fix", "machine": "review_fix", "exits": {"review_recorded": "REVIEW_RECORDED"}},
]
DRAWN = {
    "board": board_machine(STATUSES),
    PARENT: flow("in-progress") | {"submachines": LINKS},
    **dict.fromkeys(("build", "deliver", "review_fix"), flow("authoring-skills")),
}


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def place(board: Board, flow: str, name: str, state: str) -> None:
    """The machine `flow` places `name` in `state`, as its `machine:events` entries do."""
    agent = {"id": name, "title": name, "model": "", "task": name, "state": state, "steps": 1, "trail": []}
    board.feed.move(flow, agent | {"active": time.time()})


def test_the_current_phases_skill_machine_reaching_its_exit_state_fires_the_exit_event(
    stop: threading.Event, store: PullStore
) -> None:
    board = Board(BoardFeed(machines=DRAWN), task("TASK-1", "In Progress"))
    fired: list[tuple[str, str, str]] = []
    running(board, store, stop, advance=lambda *event: fired.append(event))
    place(board, PARENT, "TASK-1", "build")
    place(board, "build", "TASK-1", "red_proven")
    assert not until(lambda: fired, within=0.1)

    place(board, "build", "TASK-1", "docs_reconciled")

    assert until(lambda: fired == [(PARENT, "TASK-1", "BUILD_DONE")])


def test_a_final_event_of_a_skill_machine_the_current_phase_does_not_link_advances_nothing(
    stop: threading.Event, store: PullStore
) -> None:
    board = Board(BoardFeed(machines=DRAWN), task("TASK-1", "In Progress"), task("TASK-2", "In Progress"))
    fired: list[tuple[str, str, str]] = []
    running(board, store, stop, advance=lambda *event: fired.append(event))
    place(board, PARENT, "TASK-1", "deliver")
    place(board, PARENT, "TASK-2", "deliver")

    place(board, "build", "TASK-1", "docs_reconciled")  # the earlier phase's skill ended after the phase left it
    place(board, "deliver", "TASK-2", "pr_ready")  # the barrier: events reach the actor in order

    assert until(lambda: fired == [(PARENT, "TASK-2", "DELIVER_DONE")])
    assert not until(lambda: len(fired) > 1, within=0.1)


def test_the_server_publishes_the_exit_event_to_the_machine_events_log_as_the_task_actor(
    stop: threading.Event, store: PullStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    feed = BoardFeed(machines=DRAWN)
    board = Board(feed, task("TASK-1", "In Progress"))
    published: list[tuple[str, str, str, str | None]] = []
    monkeypatch.setattr(server, "moves_of", lambda machine: MOVES)
    monkeypatch.setattr(
        server.machine_events,
        "publish",
        lambda machine, event, *, actor, task, log: published.append((machine, event, actor, task)),
    )
    delivery = SimpleNamespace(edit=board.edit, waits=WAITS, evaluate=None, holds=None, parked=None)
    config = replace(load(None), task_actor=True, pull_requests=False, release=None)
    actor, _ = server.start_delivery(config, delivery, feed, None, store, Pins(), stop)
    assert actor.ready.wait(5)
    place(board, PARENT, "TASK-1", "build")

    place(board, "build", "TASK-1", "docs_reconciled")

    assert until(lambda: published == [(PARENT, "BUILD_DONE", ACTOR, "TASK-1")])
