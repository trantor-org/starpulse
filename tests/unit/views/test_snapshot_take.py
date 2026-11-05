"""Callers that arrive at one feed revision share one snapshot build, so a saturated host does not queue them on the
feed lock one build each."""

import json
import threading

from starpulse.board.model.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import task
from starpulse.views.adapters.inbound.snapshots import IDLE_REFRESH_S, Snapshots

from tests.machines import MACHINES, ROLES


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class CountingFeed(BoardFeed):
    """A feed that counts the snapshots taken from it."""

    taken = 0

    def snapshot_at(self):
        type(self).taken += 1
        return super().snapshot_at()


def counting() -> tuple[CountingFeed, Snapshots, Clock]:
    CountingFeed.taken = 0
    feed = CountingFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    clock = Clock()
    return feed, Snapshots(feed, clock=clock), clock


def test_takes_at_one_revision_share_one_snapshot() -> None:
    _, snapshots, _ = counting()

    first, second = snapshots.take(), snapshots.take()

    assert second is first
    assert CountingFeed.taken == 1


def test_a_take_after_a_change_reads_the_board_again() -> None:
    feed, snapshots, _ = counting()
    snapshots.take()

    feed.put(task("PROJ-1", "In Progress"))

    assert snapshots.take().rev == feed.rev
    assert CountingFeed.taken == 2


def test_a_take_after_the_idle_refresh_reads_the_board_again() -> None:
    _, snapshots, clock = counting()
    snapshots.take()

    clock.now += IDLE_REFRESH_S

    snapshots.take()
    assert CountingFeed.taken == 2


def test_takes_that_arrive_together_build_once() -> None:
    _, snapshots, _ = counting()
    start = threading.Barrier(8)
    served: list[object] = []

    def ask() -> None:
        start.wait()
        served.append(snapshots.take())

    threads = [threading.Thread(target=ask) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(served) == 8 and len({id(one) for one in served}) == 1
    assert CountingFeed.taken == 1


def test_the_full_body_is_encoded_once_per_snapshot() -> None:
    feed, snapshots, _ = counting()

    first = snapshots.full()

    assert snapshots.full() is first
    assert json.loads(first)["flows"][0]["agents"][0]["state"] == "to_do"
    feed.put(task("PROJ-1", "In Progress"))
    assert json.loads(snapshots.full())["flows"][0]["agents"][0]["state"] == "in_progress"
