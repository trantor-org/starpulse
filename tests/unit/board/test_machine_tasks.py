"""The API child's `MachineDeltas` publishes each machine row the Board child folded past its cursor as one `move` delta."""

import time
from pathlib import Path

from starpulse.board.board_feed import BoardFeed
from starpulse.board.machine_tasks import MachineDeltas
from starpulse.event_log import events as machine_events
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore

from tests.machines import MACHINES


def test_a_row_folded_after_the_cursor_is_published_as_one_move(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
    projector = Projector(log.engine, EventStore(log.engine), log=log, drawn=MACHINES)
    model = ReadModel(log.engine)
    feed = BoardFeed(window_s=600, machines=MACHINES, read_model=model)
    deltas = MachineDeltas(feed, model)
    _, subscriber = feed.subscribe()

    machine_events.publish("in-progress", "WORKTREE_READY", actor="agent", task="PROJ-1", now=time.time(), log=log)
    projector.catch_up()

    assert deltas.publish_changes() == 1
    kind, data = subscriber.get_nowait()
    assert kind == "move"
    assert (data["machine"], data["id"], data["agent"]["state"]) == ("in-progress", "PROJ-1", "worktree_ready")
    assert deltas.publish_changes() == 0
