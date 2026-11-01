import threading
import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from starpulse.board.machine_tasks import MachineDeltas
from starpulse.contracts.adapters import BoardTask, MachineEvent
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.machine_engine.model.transitions import board_machine
from starpulse.pulls.adapters.inbound.task_actor import ACTOR
from starpulse.pulls.adapters.outbound.pulls import PullStore
from starpulse.runtime import server
from starpulse.runtime.adapter_kit import task
from starpulse.runtime.config import load

from tests.machine_feed import MachineFeed
from tests.machines import STATUSES, flow
from tests.task_actor_kit import MOVES, WAITS, Board, Pins, running, until

PARENT = "in-progress"
#: The phase machine links the way `.starpulse/machines/in-progress.yaml` declares them.
LINKS = [
    {
        "state": "build",
        "machine": "build",
        "exits": {"docs_reconciled": "BUILD_DONE"},
        "routes": {"qa": "BUILD_QA"},
    },
    {"state": "deliver", "machine": "deliver", "exits": {"pr_ready": "DELIVER_DONE"}},
    {"state": "review_fix", "machine": "review_fix", "exits": {"review_recorded": "REVIEW_RECORDED"}},
]
DRAWN = {
    "board": board_machine(STATUSES),
    PARENT: flow("phase-procedure") | {"submachines": LINKS},
    **dict.fromkeys(("build", "deliver", "review_fix"), flow("phase-skill")),
}


class _Board(Board):
    """A board whose status writes land on the read model, as the board's poll folds a written file."""

    def __init__(self, machine: MachineFeed, *tasks: BoardTask) -> None:
        super().__init__(machine.feed)
        self.machine = machine
        #: The Board child's follow of the machine rows: the actor hears each row a placement folds, as the server's does.
        self.deltas = MachineDeltas(machine.feed, ReadModel(machine.log.engine))
        for each in tasks:
            self.put(each)

    def put(self, each: BoardTask) -> None:
        self.tasks[each.id] = each
        self.machine.put_task(each.id, {"title": each.title, "state": each.lane, "type": each.type})


@pytest.fixture
def machine(tmp_path: Path) -> MachineFeed:
    return MachineFeed(tmp_path / "events.sqlite", DRAWN)


@pytest.fixture
def store(tmp_path: Path) -> PullStore:
    return PullStore(create_engine(f"sqlite:///{tmp_path / 'pulls.sqlite'}"))


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def place(board: _Board, flow: str, name: str, state: str) -> None:
    """The machine `flow` places `name` in `state`: a `machine:events` entry whose event leads there."""
    board.machine.put(MachineEvent(machine=flow, event=state.upper(), task=name, time=time.time()))
    board.deltas.publish_changes()


def test_the_current_phases_skill_machine_reaching_its_exit_state_fires_the_exit_event(
    machine: MachineFeed, stop: threading.Event, store: PullStore
) -> None:
    board = _Board(machine, task("TASK-1", "In Progress"))
    fired: list[tuple[str, str, str]] = []
    running(board, store, stop, advance=lambda *event: fired.append(event))
    place(board, PARENT, "TASK-1", "build")
    place(board, "build", "TASK-1", "red_proven")
    assert not until(lambda: fired, within=0.1)

    place(board, "build", "TASK-1", "docs_reconciled")

    assert until(lambda: fired == [(PARENT, "TASK-1", "BUILD_DONE")])


def test_a_final_event_of_a_skill_machine_the_current_phase_does_not_link_advances_nothing(
    machine: MachineFeed, stop: threading.Event, store: PullStore
) -> None:
    board = _Board(machine, task("TASK-1", "In Progress"), task("TASK-2", "In Progress"))
    fired: list[tuple[str, str, str]] = []
    running(board, store, stop, advance=lambda *event: fired.append(event))
    place(board, PARENT, "TASK-1", "deliver")
    place(board, PARENT, "TASK-2", "deliver")

    place(board, "build", "TASK-1", "docs_reconciled")  # the earlier phase's skill ended after the phase left it
    place(board, "deliver", "TASK-2", "pr_ready")  # the barrier: events reach the actor in order

    assert until(lambda: fired == [(PARENT, "TASK-2", "DELIVER_DONE")])
    assert not until(lambda: len(fired) > 1, within=0.1)


def test_the_server_publishes_the_exit_event_to_the_machine_events_log_as_the_task_actor(
    machine: MachineFeed, stop: threading.Event, store: PullStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    board = _Board(machine, task("TASK-1", "In Progress"))
    published: list[tuple[str, str, str, str | None]] = []
    monkeypatch.setattr(server, "moves_of", lambda machine: MOVES)
    monkeypatch.setattr(
        server.machine_events,
        "publish",
        lambda machine, event, *, actor, task, log: published.append((machine, event, actor, task)),
    )
    delivery = SimpleNamespace(
        edit=board.edit,
        waits=WAITS,
        evaluate=None,
        holds=None,
        read=None,
        unfinished=None,
        create=None,
        parked=None,
        closed=None,
        released=None,
        delivered=None,
    )
    config = replace(load(None), task_actor=True, pull_requests=False, release=None)
    actor, _ = server.start_delivery(config, delivery, machine.feed, None, store, Pins(), stop)
    assert actor.ready.wait(5)
    place(board, PARENT, "TASK-1", "build")

    place(board, "build", "TASK-1", "docs_reconciled")

    assert until(lambda: published == [(PARENT, "BUILD_DONE", ACTOR, "TASK-1")])


@pytest.mark.parametrize(
    ("kind", "event"),
    [("story", "BUILD_QA"), ("spike", "BUILD_DONE"), ("chore", "BUILD_QA"), ("retro", "BUILD_DONE")],
)
def test_a_phase_exits_on_the_route_its_task_types_sequence_names_next(
    machine: MachineFeed, stop: threading.Event, store: PullStore, kind: str, event: str
) -> None:
    sequences = {
        "story": ("build", "qa", "deliver"),
        "chore": ("build", "qa", "deliver"),
        "default": ("build", "deliver"),
        "spike": ("build", "deliver"),
    }
    board = _Board(machine, task("TASK-1", "In Progress", type=kind))
    fired: list[tuple[str, str, str]] = []
    running(board, store, stop, advance=lambda *sent: fired.append(sent), sequences=sequences)
    place(board, PARENT, "TASK-1", "build")

    place(board, "build", "TASK-1", "docs_reconciled")

    assert until(lambda: fired == [(PARENT, "TASK-1", event)])
