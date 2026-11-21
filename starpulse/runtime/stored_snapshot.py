"""The Board writer beside a feed, for a page served without `starpulse worker board`: a harness, a bench or a test."""

import threading

from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.feed.held import HeldSnapshot
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.snapshot_store import SnapshotStore
from starpulse.event_log.wake import StopEvent
from starpulse.views.adapters.inbound.snapshots import Snapshots
from starpulse.views.model.encoding import encode_snapshot


def stored_snapshots(feed: BoardFeed, log: EventLog, stop: StopEvent) -> Snapshots:
    """Keep `feed`'s snapshot stored in `log`'s database as the Board writer does, and the `Snapshots` the API serves it
    from; returns once the first snapshot is stored."""
    store = SnapshotStore(log.engine, encode_snapshot)
    held = HeldSnapshot(feed, store=store)
    writer = threading.Thread(target=held.run, args=(stop,), name="held-snapshot", daemon=True)
    writer.start()
    try:
        # adr-exempt: handshake
        if not held.started.wait(30):
            raise TimeoutError("the Board writer stored no snapshot in 30 s")
        snapshots = Snapshots(store, log, stop)
    except BaseException:
        stop.set()
        writer.join(30)
        raise
    snapshots.caught_up = held.caught_up
    snapshots.readers.append(writer)
    return snapshots
