"""A done task goes cold at the first local midnight after it entered done: the feed holds its id, state and entered time only."""

from datetime import datetime

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse.contracts.adapters import BoardTask

DAY_S = 86400.0

NOW = 10_000_000.0


def _task(task_id: str, lane: str = "done", at: float = NOW, **fields) -> BoardTask:
    return BoardTask(id=task_id, team="demo", title=f"Title {task_id}", lane=lane, observed_at=at, **fields)


def _live() -> BoardFeed:
    feed = BoardFeed(clock=lambda: NOW)
    feed.expect("0-0")  # read up to the stream's end: every put from here is live
    return feed


def _ids(feed: BoardFeed) -> list[str]:
    return [a["id"] for a in feed.snapshot()["flows"][0]["agents"]]


def test_done_cold_a_done_task_before_midnight_holds_only_id_state_and_entered() -> None:
    feed = _live()
    entered = NOW - DAY_S - 60

    feed.put(_task("PROJ-1", at=entered))

    assert feed.held("PROJ-1") == {"id": "PROJ-1", "state": "done", "entered": entered}
    assert (_ids(feed), feed.snapshot()["cold_done"]) == ([], ["PROJ-1"])
    assert (feed.task("PROJ-1"), feed.open_tasks()) == (None, [])


def test_done_cold_a_done_task_since_local_midnight_keeps_its_record() -> None:
    feed = _live()

    feed.put(_task("PROJ-1", at=_midnight(NOW) + 60))

    assert (_ids(feed), feed.snapshot()["cold_done"]) == (["PROJ-1"], [])
    assert feed.task("PROJ-1")["title"] == "Title PROJ-1"


def test_done_cold_a_lane_change_out_of_done_reloads_the_task_onto_its_new_lane() -> None:
    feed = _live()
    feed.put(_task("PROJ-1", at=NOW - DAY_S - 60))
    _, deltas = feed.subscribe()

    feed.put(_task("PROJ-1", lane="in_progress"))

    reopened = feed.task("PROJ-1")
    assert (reopened["state"], reopened["title"]) == ("in_progress", "Title PROJ-1")
    assert (_ids(feed), feed.snapshot()["cold_done"]) == (["PROJ-1"], [])
    kind, data = deltas.get_nowait()
    assert (kind, data["id"], data["agent"]["state"]) == ("task", "PROJ-1", "in_progress")


def test_done_cold_cooling_and_the_hourly_reconcile_publish_nothing() -> None:
    feed = _live()
    cold = _task("PROJ-1", at=NOW - DAY_S - 60)
    feed.put(cold)
    _, deltas = feed.subscribe()

    feed.put(cold)  # the hourly reconcile republishes every task

    assert deltas.empty()


def test_done_cold_a_dependent_of_a_cold_done_task_stays_workable() -> None:
    feed = _live()
    feed.put(_task("PROJ-1", at=NOW - DAY_S - 60))

    feed.put(_task("PROJ-2", lane="ready", dependencies=("PROJ-1",)))

    assert feed.task("PROJ-2")["workable"] is True
    assert feed.is_done("PROJ-1")


def test_done_cold_a_hot_done_task_cools_on_a_republish_after_midnight() -> None:
    now = [NOW]
    feed = BoardFeed(clock=lambda: now[0])
    feed.expect("0-0")
    feed.put(_task("PROJ-1", at=NOW - 60))
    assert feed.task("PROJ-1") is not None

    now[0] = NOW + DAY_S + 120
    feed.put(_task("PROJ-1", at=NOW - 60))  # a republish after the clock passed 24 h

    assert feed.held("PROJ-1")["state"] == "done" and "title" not in feed.held("PROJ-1")


def _midnight(at: float) -> float:
    return datetime.fromtimestamp(at).astimezone().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def test_done_cold_a_done_task_from_before_local_midnight_is_cold_though_under_24h() -> None:
    feed = _live()
    midnight = _midnight(NOW)

    feed.put(_task("PROJ-1", at=midnight - 60))
    feed.put(_task("PROJ-2", at=midnight + 60))

    assert (_ids(feed), feed.snapshot()["cold_done"]) == (["PROJ-2"], ["PROJ-1"])
