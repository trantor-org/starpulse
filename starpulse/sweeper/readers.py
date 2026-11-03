"""The `readers` kind: a log reader with entries waiting and no progress since the last pass is woken and counted."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import func, select

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import checkpoints, events
from starpulse.sweeper.passes import Outcome


class Readers:
    """Samples each checkpoint named after a stream of the log (the other checkpoints count positions of their own).

    A reader whose checkpoint sits behind its stream's newest entry and was at the same place at the previous pass is
    stalled: it is counted as corrected and `wake` (the log's `committed`) rouses the readers of this process.
    """

    name = "readers"

    def __init__(self, log: EventLog, *, wake: Callable[[], None]) -> None:
        self._log = log
        self._wake = wake
        self._seen: dict[str, int] = {}

    def run(self) -> Outcome:
        newest = select(events.c.stream, func.max(events.c.id).label("newest")).group_by(events.c.stream).subquery()
        query = select(checkpoints.c.name, checkpoints.c.position, newest.c.newest).join(
            newest, newest.c.stream == checkpoints.c.name
        )
        with self._log.engine.connect() as db:
            rows = db.execute(query).all()
        stalled = sum(1 for name, position, newest_id in rows if newest_id > position and self._seen.get(name) == position)
        self._seen = {name: position for name, position, _ in rows}
        if stalled:
            self._wake()
        return Outcome(corrected=stalled, sampled=len(rows))
