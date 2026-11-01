"""Each lifecycle machine's tasks, read from `starpulse_machine_tasks`, and the API child's `move` deltas for them.

The Board child's projector folds `machine:events` into that table (`event_log/readmodel/projector.py`); a page reads
the rows per request. The API child keeps no machine state: it holds only a cursor on the table's `seq` and publishes
one `move` delta for each row folded past it, so an open stream hears a machine move as the snapshot draws it.
"""

from __future__ import annotations

import threading

from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.readmodel.read_model import ReadModel

#: How often the API child asks the table for rows folded since its cursor.
POLL_S = 0.5


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

    def follow(self, stop: threading.Event, interval: float = POLL_S) -> threading.Thread:
        """Publish changes on a thread until `stop`."""

        def run() -> None:
            while not stop.is_set():
                self.publish_changes()
                stop.wait(interval)

        thread = threading.Thread(target=run, name="machine-deltas", daemon=True)
        thread.start()
        return thread
