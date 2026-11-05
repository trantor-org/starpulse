"""Each lifecycle machine's tasks, read from `starpulse_machine_tasks`, and the API child's `move` deltas for them.

The Board child's projector folds `machine:events` into that table (`event_log/readmodel/projector.py`); a page reads
the rows per request. The API child keeps no machine state: it holds only a cursor on the table's `seq` and publishes
one `move` delta for each row folded past it, so an open stream hears a machine move as the snapshot draws it.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from starpulse.board.model.board_feed import BoardFeed
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import EventLog


class MachineDeltas:
    """Publishes each machine row folded past its cursor as a `move` delta; the cursor starts at the newest row, so a
    page that connects reads the rows it needs from its snapshot, never from a replay of the table."""

    def __init__(self, feed: BoardFeed, model: ReadModel) -> None:
        self._feed = feed
        self._model = model
        self._seq = model.machine_position()

    def publish_changes(self) -> int:
        """Publish every row folded past the cursor, oldest first; the number published."""
        changes = self._model.machine_changes(self._seq)
        for flow, agent, seq in changes:
            self._feed.publish_move(flow, agent)
            self._seq = seq
        return len(changes)

    def follow(self, stop: StopEvent, log: EventLog) -> threading.Thread:
        """Publish changes on a thread, on each wake of `log`, until `stop`."""
        thread = threading.Thread(
            target=log.run_on_wake,
            args=(stop, self.publish_changes, "machine deltas: the pass failed"),
            name="machine-deltas",
            daemon=True,
        )
        thread.start()
        return thread
