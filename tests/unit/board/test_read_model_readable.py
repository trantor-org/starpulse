"""A read-model card carries the verdict of the board's `readable` rules, so the page draws the badge on a pre-rule description."""

import time
from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, NewEvent

from tests.machines import MACHINES, ROLES

BROKEN = "Missing the Outcome heading"


def _verdict(front: dict, body: str) -> str:
    return "" if "## Outcome" in body else BROKEN


def _agents(tmp_path: Path, readable=_verdict) -> dict[str, dict]:
    engine = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine
    store = EventStore(engine)
    for number, description in ((1, "Just prose."), (2, "## Outcome\nIt works.")):
        payload = {"title": f"Task {number}", "state": "Ready", "description": description}
        store.append("task", f"TASK-{number}", 0, [NewEvent("TaskCreated", payload, "adin", "operator")])
    Projector(engine, store).catch_up()
    feed = BoardFeed(roles=ROLES, machines=MACHINES, read_model=ReadModel(engine), readable=readable, clock=lambda: time.time() + 86_400)
    snapshot = {agent["id"]: agent for agent in feed.snapshot()["flows"][0]["agents"]}
    snapshot["opened"] = feed.task("TASK-1")
    return snapshot


def test_a_snapshot_card_carries_the_verdict_of_a_description_that_breaks_a_rule(tmp_path: Path) -> None:
    agents = _agents(tmp_path)

    assert (agents["TASK-1"]["readable"], agents["TASK-2"]["readable"]) == (BROKEN, "")


def test_an_opened_task_carries_the_same_verdict_as_its_snapshot_card(tmp_path: Path) -> None:
    agents = _agents(tmp_path)

    assert agents["opened"]["readable"] == BROKEN
