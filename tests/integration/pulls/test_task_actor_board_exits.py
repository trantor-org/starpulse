import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from starpulse.event_log.wake import StopEvent
from starpulse.board.machine_tasks import MachineDeltas
from starpulse.contracts.adapters import BoardTask, MachineEvent
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model.snapshot import describe
from starpulse.machine_engine.model.transitions import board_machine
from starpulse.pulls.adapters.inbound.task_actor import ACTOR
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime.adapter_kit import task

from tests.machine_feed import MachineFeed
from tests.machines import flow
from tests.task_actor_kit import MOVES, Board, running, until

#: The Board's links the way `.starpulse/machines/board.yaml` declares them: `verify` exits on events the task actor
#: writes, `in-progress` on events a board command writes.
LINKS = [
    {"state": "in_progress", "machine": "in-progress", "exits": {"review_recorded": "REVIEW"}},
    {"state": "verifying", "machine": "verify", "exits": {"pr_ready": "POST_MERGE_QA_PASSED", "docs_reconciled": "SEND_BACK"}},
]
WRITERS = {
    "REVIEW": [{"actor": "agent", "trigger": "./.venv/bin/backlog-task review"}],
    "POST_MERGE_QA_PASSED": [{"actor": ACTOR, "trigger": "every post-merge QA item passes"}],
    "SEND_BACK": [{"actor": ACTOR, "trigger": "./.venv/bin/backlog-task verify-miss"}],
}
DRAWN = {
    "board": board_machine(("Ready", "In Progress", "Verifying", "Done")) | {"submachines": LINKS, "writers": WRITERS},
    "in-progress": flow("phase-skill"),
    "verify": flow("phase-skill"),
}
#: `phase-skill` draws no `passed` or `missed`: its `pr_ready` stands for a pass and `docs_reconciled` for a miss.


class _Board(Board):
    def __init__(self, machine: MachineFeed, *tasks: BoardTask) -> None:
        super().__init__(machine.feed)
        self.machine = machine
        self.deltas = MachineDeltas(machine.feed, ReadModel(machine.log.engine))
        for each in tasks:
            self.tasks[each.id] = each
            machine.put_task(
                each.id,
                {"title": each.title, "state": each.lane, "type": each.type, "dependencies": list(each.dependencies)},
            )

    def edit(self, name, changes, comment, /, actor=""):
        """The kit's write, folded into the read model as the board's poll places it."""
        written = super().edit(name, changes, comment, actor)
        if written.ok and "status" in changes:
            self.machine.put_task(name, {"state": changes["status"]})
        return written


@pytest.fixture
def machine(tmp_path: Path) -> MachineFeed:
    return MachineFeed(tmp_path / "events.sqlite", DRAWN)


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[StopEvent]:
    event = StopEvent()
    yield event
    event.set()


def place(board: _Board, flow_name: str, name: str, state: str, *, ago: float = 0) -> None:
    board.machine.put(MachineEvent(machine=flow_name, event=state.upper(), task=name, time=time.time() - ago))
    board.deltas.publish_changes()


#: The Verifying moves the Board draws for the exits its Verify link names.
VERIFYING_MOVES = {**MOVES, ("verifying", "POST_MERGE_QA_PASSED"): "done", ("verifying", "SEND_BACK"): "in_progress"}


def test_a_verify_exit_the_task_actor_writes_moves_the_board_lane(
    machine: MachineFeed, stop: threading.Event, store: PullStore
) -> None:
    board = _Board(machine, task("TASK-1", "Verifying"), task("TASK-2", "Verifying"))
    running(board, store, stop, moves=VERIFYING_MOVES, advance=lambda *event: None)
    place(board, "verify", "TASK-1", "pr_ready")
    place(board, "verify", "TASK-2", "docs_reconciled")

    assert until(lambda: sorted(board.moved()) == [("TASK-1", "done"), ("TASK-2", "in_progress")])


def test_a_board_exit_a_board_command_writes_is_not_sent_by_the_task_actor(
    machine: MachineFeed, stop: threading.Event, store: PullStore
) -> None:
    board = _Board(machine, task("TASK-1", "In Progress"))
    fired: list[tuple[str, str, str]] = []
    running(board, store, stop, advance=lambda *event: fired.append(event))
    place(board, "in-progress", "TASK-1", "review_recorded")

    assert not until(lambda: fired, within=0.3)


def test_a_verify_exit_from_before_the_task_entered_the_lane_is_not_sent(
    machine: MachineFeed, stop: threading.Event, store: PullStore
) -> None:
    """A task sent back and merged again re-enters Verifying with the last round's final verify state."""
    board = _Board(machine, task("TASK-1", "Verifying"))
    fired: list[tuple[str, str, str]] = []
    running(board, store, stop, advance=lambda *event: fired.append(event))
    place(board, "verify", "TASK-1", "docs_reconciled", ago=60)

    assert not until(lambda: fired, within=0.3)


REAL_LINKS = [
    {"state": "verifying", "machine": "verify", "exits": {"passed": "POST_MERGE_QA_PASSED", "missed": "SEND_BACK"}},
]
VERIFY_YAML = """name: Verify
states:
  merged: {initial: true, role: resting}
  applied: {role: resting}
  pin_moved: {role: resting}
  passed: {final: true}
  missed: {final: true}
events:
  APPLY_FINISHED:
    - {from: merged, to: applied}
  PIN_MOVED:
    - {from: applied, to: pin_moved}
  QA_PASSED:
    - {from: [merged, applied, pin_moved], to: passed}
  QA_MISSED:
    - {from: [merged, applied, pin_moved], to: missed}
"""


def real_drawn(tmp_path: Path) -> dict:
    path = tmp_path / "verify.yaml"
    path.write_text(VERIFY_YAML)
    board = board_machine(("Ready", "In Progress", "Verifying", "Done"))
    return {"board": board | {"submachines": REAL_LINKS, "writers": WRITERS}, "verify": describe(load_machine(path).machine)}


def send(board: _Board, name: str, event: str, *, ago: float = 0) -> None:
    board.machine.put(MachineEvent(machine="verify", event=event, task=name, time=time.time() - ago))
    board.deltas.publish_changes()


def test_a_recorded_verdict_of_the_real_verify_machine_moves_the_board_lane(tmp_path: Path, stop: threading.Event, store: PullStore) -> None:
    feed = MachineFeed(tmp_path / "real.sqlite", real_drawn(tmp_path))
    board = _Board(feed, task("TASK-1", "Verifying"), task("TASK-2", "Verifying"))
    running(board, store, stop, moves=VERIFYING_MOVES, advance=lambda *event: None)
    send(board, "TASK-1", "APPLY_FINISHED")
    send(board, "TASK-1", "QA_PASSED")
    send(board, "TASK-2", "APPLY_FINISHED")
    send(board, "TASK-2", "QA_MISSED")

    assert until(lambda: sorted(board.moved()) == [("TASK-1", "done"), ("TASK-2", "in_progress")])


def test_a_task_waiting_on_a_verifying_task_waits_for_its_pass_and_is_released_by_it(
    tmp_path: Path, stop: threading.Event, store: PullStore
) -> None:
    """Verifying is no Done: a miss keeps the dependent waiting, and the pass that closes the task releases it."""
    feed = MachineFeed(tmp_path / "real.sqlite", real_drawn(tmp_path))
    dependent = task("TASK-2", "Waiting", dependencies=("TASK-1",))
    board = _Board(feed, task("TASK-1", "Verifying"), dependent)
    running(board, store, stop, moves=VERIFYING_MOVES, advance=lambda *event: None)

    assert not until(lambda: ("TASK-2", "ready") in board.moved(), within=0.3)
    send(board, "TASK-1", "QA_PASSED")

    assert until(lambda: board.moved() == [("TASK-1", "done"), ("TASK-2", "ready")])
