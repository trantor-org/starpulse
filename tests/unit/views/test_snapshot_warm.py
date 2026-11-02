"""A warm Snapshots serves the last encoded snapshot while it is current, so a request pays no build (TASK-10790)."""

import json
import threading

from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import task
from starpulse.views.adapters.inbound.snapshots import IDLE_REFRESH_S, Snapshots

from tests.machines import MACHINES, ROLES

REFRESH_S = 2.0


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def warm() -> tuple[BoardFeed, Snapshots, Clock]:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    clock = Clock()
    return feed, Snapshots(feed, refresh_s=REFRESH_S, clock=clock), clock


def titles(encoded) -> list[str]:
    board = json.loads(encoded.body)["flows"][0]["agents"]
    return [agent["id"] + ":" + agent["state"] for agent in board]


def test_without_a_refresh_every_build_reads_the_board_again() -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    snapshots = Snapshots(feed)
    first = snapshots.build()[1]

    feed.put(task("PROJ-1", "In Progress"))

    assert snapshots.build()[1] is not first
    assert titles(snapshots.build()[1]) == ["PROJ-1:in_progress"]


def test_a_build_while_the_feed_is_unchanged_serves_the_held_snapshot() -> None:
    _, snapshots, clock = warm()
    served, first = snapshots.build()
    clock.now += IDLE_REFRESH_S - 1

    again_served, again = snapshots.build()

    assert again is first and again_served is served


def test_a_build_after_a_change_serves_the_held_snapshot_until_it_is_two_refreshes_old() -> None:
    feed, snapshots, clock = warm()
    _, first = snapshots.build()
    feed.put(task("PROJ-1", "In Progress"))
    clock.now += 2 * REFRESH_S

    assert snapshots.build()[1] is first

    clock.now += 0.1
    fresh_served, fresh = snapshots.build()

    assert fresh is not first
    assert fresh_served.rev == feed.rev
    assert titles(fresh) == ["PROJ-1:in_progress"]


def test_an_unchanged_feed_is_rebuilt_once_the_held_snapshot_is_idle_old() -> None:
    _, snapshots, clock = warm()
    _, first = snapshots.build()
    clock.now += IDLE_REFRESH_S + 1

    assert snapshots.build()[1] is not first


def test_refresh_rebuilds_a_changed_feed_and_leaves_an_unchanged_one() -> None:
    feed, snapshots, clock = warm()
    _, first = snapshots.build()

    snapshots.refresh()
    assert snapshots.build()[1] is first

    feed.put(task("PROJ-1", "In Progress"))
    snapshots.refresh()
    served, rebuilt = snapshots.build()

    assert rebuilt is not first and served.rev == feed.rev
    assert titles(rebuilt) == ["PROJ-1:in_progress"]


def test_requests_that_find_it_stale_share_one_build() -> None:
    feed, snapshots, clock = warm()
    snapshots.build()
    feed.put(task("PROJ-1", "In Progress"))
    clock.now += 10 * REFRESH_S
    builds = []
    take = snapshots.take

    def counting():
        builds.append(1)
        return take()

    snapshots.take = counting  # type: ignore[method-assign]
    results = []
    threads = [threading.Thread(target=lambda: results.append(snapshots.build()[1])) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(builds) == 1 and len({id(r) for r in results}) == 1


def test_two_streams_sharing_one_held_body_each_fetch_it() -> None:
    _, snapshots, _ = warm()
    encoded = snapshots.build()[1]

    first, second = snapshots.hold(encoded), snapshots.hold(encoded)

    assert first != second
    assert snapshots.body(first) is encoded
    assert snapshots.body(second) is encoded
    assert snapshots.body(first) is None


def test_keep_warm_rebuilds_a_changed_feed_until_stopped() -> None:
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-1", "To Do"))
    snapshots = Snapshots(feed, refresh_s=0.01)
    snapshots.build()
    stop = threading.Event()
    thread = threading.Thread(target=snapshots.keep_warm, args=(stop,), daemon=True)
    thread.start()
    feed.put(task("PROJ-1", "In Progress"))
    deadline = threading.Event()
    for _ in range(200):
        if snapshots.held_rev == feed.rev:
            break
        deadline.wait(0.01)
    stop.set()
    thread.join(timeout=2)

    assert snapshots.held_rev == feed.rev
    assert not thread.is_alive()
