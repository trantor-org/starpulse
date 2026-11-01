"""The page draws each machine's tasks from `starpulse_machine_tasks`: a machine event the Board child folded shows in the
snapshot's machine lane while it is inside `window_s`, and not after."""

import time
from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.event_log import events as machine_events
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore

from tests.machines import MACHINES

WINDOW_S = 600.0


def _lane(snapshot: dict, flow: str) -> list[dict]:
    return next(f["agents"] for f in snapshot["flows"] if f["name"] == flow)


def _feed(log: EventLog) -> BoardFeed:
    Projector(log.engine, EventStore(log.engine), log=log, drawn=MACHINES).catch_up()
    return BoardFeed(window_s=WINDOW_S, machines=MACHINES, read_model=ReadModel(log.engine))


def test_a_folded_machine_event_draws_its_lane_within_window_s(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    machine_events.publish(
        "in-progress", "WORKTREE_READY", actor="agent", task="PROJ-1", now=time.time() - 10, log=log
    )

    lane = _lane(_feed(log).snapshot(), "in-progress")

    assert [(agent["id"], agent["state"]) for agent in lane] == [("PROJ-1", "worktree_ready")]


def test_a_folded_machine_event_older_than_window_s_is_not_drawn(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    machine_events.publish(
        "in-progress", "WORKTREE_READY", actor="agent", task="PROJ-1", now=time.time() - 2 * WINDOW_S, log=log
    )

    assert _lane(_feed(log).snapshot(), "in-progress") == []
