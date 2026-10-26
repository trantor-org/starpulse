"""`read` answers from the held snapshot while the background rebuild catches up; a write makes the next one current."""

import threading
import time

from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import task
from starpulse.tests.machines import MACHINES, ROLES
from starpulse.views.snapshot_cache import SnapshotCache


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


def test_the_background_rebuilds_before_the_ttl_so_no_request_finds_it_expired() -> None:
    _, cache = _cache(ttl_s=0.4, settle_s=0)
    first = cache.get()
    deadline = time.monotonic() + 5

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
