"""A move's standing verdict names who a guard refuses and who it exempts, so `task moves` agrees with `task move`."""

import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import Engine
from starpulse.board.adapters import native
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model import rules
from starpulse.contracts.adapters import Move
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, NewEvent
from starpulse.views.application.commands.tasks import task_record

from tests.unit.board.test_native import native_root, write_task

QUESTION = {
    "on": {"from": "Needs attention", "to": "Ready"},
    "require": {"section": {"heading": "Needs attention", "not_matching": r"\?"}},
    "unless_actor": ["operator"],
    "reason": "only the operator answers the question",
}
NEEDS_PROFILE = {
    "on": {"to": "Ready"},
    "require": {"field": {"field": "profile", "matches": "."}},
    "reason": "a Ready task needs an agent profile",
}
ASKING = "\n## Needs attention\nWhich one?\n"


def _asking(tmp_path: Path, guards: list[dict[str, Any]], **fields: object) -> native.Board:
    """A native board with `guards` holding `task-1` in Needs attention, asking the operator a question."""
    root = native_root(tmp_path)
    root.mkdir(parents=True)
    statuses = ["Needs attention", "Ready", "Done"]
    (root / "config.yml").write_text(yaml.safe_dump({"project_name": "demo", "statuses": statuses, "task_prefix": "task"}))
    path = write_task(tmp_path, "task-1", "Needs attention", **fields)
    path.write_text(path.read_text() + ASKING)
    return native.board({"guards": guards}, tmp_path)


def test_a_standing_refusal_for_an_actor_leaves_out_only_the_rules_that_exempt_it() -> None:
    front = {"status": "Needs attention"}
    guards = rules.load([QUESTION])

    assert rules.standing_refusal(guards, front, ASKING, "ready").reason == QUESTION["reason"]  # type: ignore[union-attr]
    assert rules.standing_refusal(guards, front, ASKING, "ready", "operator") is None


def test_the_board_names_the_verdict_each_exempt_actor_meets(tmp_path: Path) -> None:
    built = _asking(tmp_path, [QUESTION, NEEDS_PROFILE], profile="'@agent-standard-high'")

    assert built.standing is not None
    verdict = built.standing("task-1", "ready")

    assert verdict == {
        "allowed": False,
        "reason": QUESTION["reason"],
        "skill": "",
        "actors": {"operator": {"allowed": True, "reason": "", "skill": ""}},
    }


def test_an_exempt_actor_still_meets_a_rule_that_does_not_exempt_it(tmp_path: Path) -> None:
    built = _asking(tmp_path, [QUESTION, NEEDS_PROFILE])

    assert built.standing is not None
    verdict = built.standing("task-1", "ready")

    assert verdict is not None
    assert verdict["actors"]["operator"] == {"allowed": False, "reason": NEEDS_PROFILE["reason"], "skill": ""}


def test_a_move_no_guard_refuses_has_no_standing_verdict(tmp_path: Path) -> None:
    built = _asking(tmp_path, [NEEDS_PROFILE], profile="'@agent-standard-high'")

    assert built.standing is not None
    assert built.standing("task-1", "ready") is None


def test_a_move_is_refused_to_the_agent_and_lifted_for_the_actor_a_guard_exempts() -> None:
    move = Move.model_validate(
        {"allowed": False, "reason": "asks", "actors": {"operator": {"allowed": True}}, "writers": []}
    )

    assert (move.for_actor("agent").allowed, move.for_actor("agent").reason) == (False, "asks")
    assert move.for_actor("operator").allowed


@pytest.fixture
def engine() -> Iterator[Engine]:
    with tempfile.TemporaryDirectory() as directory:
        built = EventLog(f"sqlite:///{Path(directory) / 'events.sqlite'}").engine
        yield built
        built.dispose()


def test_a_read_model_task_offers_the_moves_with_the_boards_standing_verdict(engine: Engine) -> None:
    created = NewEvent(
        type="TaskCreated",
        payload={"title": "T", "description": "", "state": "To Do", "labels": []},
        actor="adin",
        writer="operator",
    )
    EventStore(engine).append("task", "TASK-1", 0, [created])
    Projector(engine, EventStore(engine)).catch_up()
    asked: list[tuple[str, str]] = []

    def standing(task: str, lane: str) -> dict[str, Any]:
        asked.append((task, lane))
        return {"allowed": False, "reason": "asks", "skill": "", "actors": {"operator": {"allowed": True}}}

    feed = BoardFeed(read_model=ReadModel(engine), standing=standing)

    moves = {lane: Move.model_validate(move) for lane, move in feed.task("TASK-1")["moves"].items()}  # type: ignore[index]

    assert moves
    assert {lane for _, lane in asked} == set(moves)
    assert {move.for_actor("agent").allowed for move in moves.values()} == {False}
    assert {move.for_actor("operator").allowed for move in moves.values()} == {True}


def test_a_task_record_reads_the_task_file_as_often_as_one_read_of_it_not_once_per_lane(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = native_root(tmp_path)
    root.mkdir(parents=True)
    (root / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": ["To Do", "Ready", "Done"], "task_prefix": "task"})
    )
    write_task(tmp_path, "TASK-1", "To Do")
    built = native.board({"guards": [NEEDS_PROFILE]}, tmp_path)
    created = NewEvent(
        type="TaskCreated",
        payload={"title": "T", "description": "", "state": "To Do", "labels": []},
        actor="adin",
        writer="operator",
    )
    EventStore(engine).append("task", "TASK-1", 0, [created])
    Projector(engine, EventStore(engine)).catch_up()
    feed = BoardFeed(read_model=ReadModel(engine), standing=built.standing)
    opened: list[str] = []
    real = Path.read_text

    def counting(self: Path, *args: Any, **kwargs: Any) -> str:
        opened.append(self.name)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counting)
    assert built.read is not None
    built.read("TASK-1")
    once, opened[:] = len(opened), []

    status, _ = task_record(feed, built.read, "TASK-1")

    assert status == 200
    assert len(opened) == once
