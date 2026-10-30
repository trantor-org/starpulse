"""`read` answers from the held snapshot while the background rebuild catches up; a write makes the next one current."""

import threading
import time

from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import task
from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache

from tests.machines import MACHINES, ROLES


def _cache(ttl_s: float = 60, settle_s: float = 60) -> tuple[BoardFeed, SnapshotCache]:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    return feed, SnapshotCache(feed, ttl_s=ttl_s, settle_s=settle_s)


def test_a_read_after_a_change_serves_the_held_snapshot_instead_of_building_one() -> None:
    feed, cache = _cache()
    first = cache.get()
    feed.put(task("PROJ-1", "In Progress"))

    assert cache.read() is first


def test_a_read_after_a_write_includes_the_change_the_write_published() -> None:
    feed, cache = _cache()
    first = cache.get()
    feed.put(task("PROJ-1", "In Progress"))
    cache.require_current()

    served = cache.read()

    assert served is not first
    assert served.rev == feed.rev


class _QuietFeedWait:
    """Stands for `feed.revised` with no change published: once `go` is set the first wait ends on its timeout, the
    clock having moved that long, so the test reads no wall clock a loaded host could stretch."""

    def __init__(self, clock: list[float]) -> None:
        self.go = threading.Event()
        self.waited: list[float] = []
        self._clock = clock

    def wait(self, timeout: float) -> bool:
        if not self.waited:
            self.go.wait(5)
            self._clock[0] += timeout
        self.waited.append(timeout)
        if len(self.waited) > 1:
            threading.Event().wait(5)  # a second wait would be a second rebuild: end the test first
        return False

    def clear(self) -> None:
        pass


def test_the_background_rebuilds_before_the_ttl_so_no_request_finds_it_expired() -> None:
    clock = [0.0]
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    cache = SnapshotCache(feed, ttl_s=0.4, settle_s=0, clock=lambda: clock[0])
    quiet = _QuietFeedWait(clock)
    feed.revised = quiet  # type: ignore[assignment]
    first = cache.get()
    quiet.go.set()
    deadline = time.monotonic() + 30

    while cache._held is first and time.monotonic() < deadline:
        time.sleep(0.02)

    assert cache._held is not first
    assert cache._held.at - first.at < 0.4  # type: ignore[union-attr]


def test_the_background_does_not_rebuild_a_snapshot_a_request_built_while_it_waited() -> None:
    feed, cache = _cache(settle_s=0)
    taken = []
    started = threading.Event()
    release = threading.Event()
    snapshot_at = feed.snapshot_at

    def slow() -> tuple[int, int, dict]:
        taken.append(1)
        started.set()
        release.wait(5)
        return snapshot_at()

    feed.snapshot_at = slow  # type: ignore[method-assign]
    request = threading.Thread(target=cache.get)
    request.start()
    assert started.wait(5)
    time.sleep(0.2)  # the background thread reaches its check while the request still holds the build
    release.set()
    request.join(5)
    time.sleep(0.2)

    assert len(taken) == 1
