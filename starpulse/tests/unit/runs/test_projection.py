"""The Runs worker's seam with `serve`: the workflows each run adapter instance reports cross the event log."""

import threading
from pathlib import Path

import pytest

from starpulse.board.board_feed import BoardFeed
from starpulse.runs import projection
from starpulse.event_log.event_log import EventLog

DAGS = [{"name": "ci", "status": "success", "runId": "1", "startedAt": "", "finishedAt": "", "steps": []}]
POOLS = [{"name": "gpu", "limit": 1, "running": 0}]
WAIT_S = 5.0


class Inner:
    """The worker feed's sink for one instance: it only says which workflows a Board event cues."""

    tied = frozenset({"ci"})


class Feed(BoardFeed):
    """A feed that records what it was given and says when it has taken a projection."""

    def __init__(self) -> None:
        super().__init__()
        self.given: list[tuple] = []
        self.taken = threading.Event()

    def set_dags(self, instance, dags, error, pools=None, startable=None) -> None:
        self.given.append((instance, dags, error, pools, startable))
        self.taken.set()


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


def test_a_published_report_is_kept_in_the_log_and_announced(log: EventLog) -> None:
    sink = projection.Publisher(log).runs("dagu", Inner())

    sink.set_dags(DAGS, None, POOLS, ["ci"])

    assert log.setting(projection.PROJECTION) == {
        "dagu": {"dags": DAGS, "error": None, "pools": POOLS, "startable": ["ci"]}
    }
    assert log.last(projection.PROJECTED_STREAM) is not None


def test_a_published_sink_reports_the_workflows_the_feed_ties(log: EventLog) -> None:
    assert projection.Publisher(log).runs("dagu", Inner()).tied == frozenset({"ci"})


def test_none_keeps_what_the_instance_last_reported_and_an_empty_pools_clears_it(log: EventLog) -> None:
    sink = projection.Publisher(log).runs("dagu", Inner())
    sink.set_dags(DAGS, None, POOLS, ["ci"])

    sink.set_dags(None, "unreachable")
    assert log.setting(projection.PROJECTION)["dagu"] == {
        "dags": DAGS,
        "error": "unreachable",
        "pools": POOLS,
        "startable": ["ci"],
    }

    sink.set_dags(DAGS, None, [])
    assert log.setting(projection.PROJECTION)["dagu"]["pools"] == []
    assert log.setting(projection.PROJECTION)["dagu"]["error"] is None


def test_instances_are_kept_side_by_side(log: EventLog) -> None:
    publisher = projection.Publisher(log)
    publisher.runs("dagu", Inner()).set_dags(DAGS, None)
    publisher.runs("pushed", Inner()).set_dags([], None)

    assert set(log.setting(projection.PROJECTION)) == {"dagu", "pushed"}


def test_a_report_the_log_already_holds_is_not_announced_again(log: EventLog) -> None:
    sink = projection.Publisher(log).runs("dagu", Inner())
    sink.set_dags(DAGS, None)
    announced = log.last(projection.PROJECTED_STREAM)

    sink.set_dags(DAGS, None)

    assert log.last(projection.PROJECTED_STREAM) == announced


def test_serve_applies_each_instances_kept_report_to_its_feed(log: EventLog) -> None:
    publisher = projection.Publisher(log)
    publisher.runs("dagu", Inner()).set_dags(DAGS, None, POOLS, ["ci"])
    publisher.runs("pushed", Inner()).set_dags([], "down")
    feed = Feed()

    projection.Projected(log, feed).apply()

    assert sorted(feed.given, key=lambda g: g[0]) == [
        ("dagu", DAGS, None, POOLS, ["ci"]),
        ("pushed", [], "down", [], None),
    ]


@pytest.mark.parametrize("kept", [None, [], "text", {"dagu": "text"}, {"dagu": {"dags": "text", "error": None}}])
def test_a_kept_report_that_is_missing_or_unreadable_leaves_the_feed_as_it_was(log: EventLog, kept: object) -> None:
    if kept is not None:
        log.set_setting(projection.PROJECTION, kept)
    feed = Feed()

    projection.Projected(log, feed).apply()

    assert feed.given == []


def test_following_applies_the_kept_report_now_and_each_one_announced_after(log: EventLog) -> None:
    publisher = projection.Publisher(log)
    sink = publisher.runs("dagu", Inner())
    sink.set_dags(DAGS, None)
    feed = Feed()
    stop = threading.Event()
    try:
        projection.Projected(log, feed).follow(stop)
        assert feed.taken.is_set()
        feed.taken.clear()

        sink.set_dags([], None)

        assert feed.taken.wait(WAIT_S)
        assert feed.given[-1][:3] == ("dagu", [], None)
    finally:
        stop.set()
