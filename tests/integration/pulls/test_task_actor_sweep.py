"""The task actor's Waiting sweep: a settled dependency releases the task, and a wait nothing can end is flagged once."""

import threading
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.seam import FLAGGED
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime.adapter_kit import task

from tests.task_actor_kit import GATED, ROLES, WAITS, Board, Criteria, running, until

#: The kit's roles with the lane a task waits in until the operator promotes it.
PROPOSING = StateRoles({**ROLES.roles, "proposed": "proposed"}, WAITS, ("done",))


@pytest.fixture
def store(tmp_path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def test_a_waiting_task_whose_only_dependency_is_archived_is_released(store: PullStore, stop: threading.Event) -> None:
    board = Board(
        BoardFeed(),
        task("TASK-1", "Archived", settled="archived"),
        task("TASK-2", "Waiting", dependencies=("TASK-1",)),
    )

    running(board, store, stop)

    assert until(lambda: board.moved() == [("TASK-2", "ready")])


def test_the_sweep_derives_each_waiting_task_again_with_no_event(store: PullStore, stop: threading.Event) -> None:
    board = Board(BoardFeed(), task("TASK-1", "In Progress"), task("TASK-2", "Waiting", dependencies=("TASK-1",)))
    actor = running(board, store, stop, sweep_s=0.01)
    seen = actor.derivations["TASK-2"]

    assert until(lambda: actor.derivations["TASK-2"] >= seen + 3)
    assert board.writes == []


def test_the_sweep_flags_a_wait_nothing_can_end_once_and_leaves_every_other_task(
    store: PullStore, stop: threading.Event
) -> None:
    board = Board(
        BoardFeed(roles=PROPOSING),
        task("TASK-1", "In Progress"),
        task("TASK-2", "Proposed"),
        task("TASK-3", "Waiting", dependencies=("TASK-1",)),  # an open dependency: left
        task("TASK-4", "Waiting", dependencies=("TASK-2",)),  # a Proposed dependency: flagged
        task("TASK-5", "Waiting", dependencies=("TASK-404",)),  # a dependency the board does not hold: flagged
        task("TASK-6", "Waiting", description=GATED),  # an unmet criterion: left
        task("TASK-7", "Needs Attention", dependencies=("TASK-404",)),  # never touched
    )
    actor = running(board, store, stop, evaluate=Criteria("unmet"), sweep_s=0.01)
    seen = actor.derivations["TASK-4"]

    assert until(lambda: {name for name, _ in board.comments()} == {"TASK-4", "TASK-5"})
    assert until(lambda: actor.derivations["TASK-4"] >= seen + 3)  # more sweeps pass

    flagged = dict(board.comments())
    assert all(text.startswith(FLAGGED) for text in flagged.values())
    assert "TASK-2" in flagged["TASK-4"]
    assert "TASK-404" in flagged["TASK-5"]
    assert len(board.comments()) == 2
    assert board.moved() == []
