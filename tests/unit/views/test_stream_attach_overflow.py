"""A stream attach whose warm snapshot the feed log can no longer replay gets a rebuilt one, never the same."""

from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import task
from starpulse.views.adapters.inbound.api.streams import Streams
from starpulse.views.adapters.inbound.snapshots import Snapshots

from tests.machines import MACHINES, ROLES

OVERFLOW = 600  # more publishes than the feed's sent log holds


class Spy(Snapshots):
    def __init__(self, feed: BoardFeed) -> None:
        super().__init__(feed, refresh_s=2.0, clock=lambda: 1000.0)
        self.calls = 0

    def build(self, fresh: bool = False):
        self.calls += 1
        assert self.calls <= 3, "attach spins on the same warm snapshot"
        return super().build(fresh)


def test_attach_after_the_sent_log_overflowed_since_the_warm_snapshot_rebuilds_once() -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    snapshots = Spy(feed)
    warm_served, _ = Snapshots.build(snapshots)
    for n in range(OVERFLOW):
        feed.put(task("PROJ-1", "In Progress" if n % 2 else "To Do"))

    stream = Streams(feed, snapshots)._events(False)

    assert snapshots.calls == 2
    assert stream is not None
    assert feed.rev > warm_served.rev
