"""The Delivery worker's seam with `serve`: the projection, refresh requests, actor notes and metrics cross the log."""

import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.pulls import delivery
from starpulse._internal.pulls.pulls import PullStore

PULLS = {"TASK-1": [{"number": 7, "url": "https://github.com/acme/widgets/pull/7", "checks": "pass"}]}
ANSWERS = {"records": {}, "pins": {}}
WAIT_S = 5.0


class Feed(BoardFeed):
    """A feed that says when it has taken a projection."""

    def __init__(self) -> None:
        super().__init__()
        self.taken = threading.Event()
        self.notes: list[tuple[str, str | None]] = []

    def set_pulls(self, pulls: dict, answers: dict | None = None) -> None:
        super().set_pulls(pulls, answers)
        self.taken.set()

    def note_actor(self, task_id: str, actor: str | None, session: str = "", harness: str = "") -> None:
        self.notes.append((task_id, actor))


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}")


@pytest.fixture
def stop() -> Iterator[threading.Event]:
    event = threading.Event()
    yield event
    event.set()


def test_a_projection_is_kept_in_the_log_and_announced(log: EventLog) -> None:
    feed = Feed()
    feed.set_pulls(PULLS, ANSWERS)

    delivery.Publisher(log, feed).publish()

    assert log.setting(delivery.PROJECTION) == {"pulls": PULLS, "answers": ANSWERS}
    assert log.last(delivery.PROJECTED_STREAM) is not None


def test_a_projection_that_has_not_changed_is_not_announced_again(log: EventLog) -> None:
    feed = Feed()
    feed.set_pulls(PULLS, ANSWERS)
    publisher = delivery.Publisher(log, feed)
    publisher.publish()
    first = log.last(delivery.PROJECTED_STREAM)

    publisher.publish()

    assert log.last(delivery.PROJECTED_STREAM) == first


def test_the_serving_feed_takes_the_projection_the_worker_kept(log: EventLog) -> None:
    worker = Feed()
    worker.set_pulls(PULLS, ANSWERS)
    delivery.Publisher(log, worker).publish()
    serving = Feed()

    delivery.Projected(log, serving).apply()

    assert serving.pulls() == PULLS


def test_serving_with_no_projection_yet_leaves_the_feed_as_it_was(log: EventLog) -> None:
    serving = Feed()

    delivery.Projected(log, serving).apply()

    assert serving.pulls() == {}


def test_the_serving_feed_follows_each_projection_the_worker_announces(log: EventLog, stop: threading.Event) -> None:
    serving = Feed()
    delivery.Projected(log, serving).follow(stop)
    worker = Feed()
    worker.set_pulls(PULLS, ANSWERS)

    delivery.Publisher(log, worker).publish()

    assert serving.taken.wait(WAIT_S)
    assert serving.pulls() == PULLS


def test_a_refresh_of_a_repository_the_store_does_not_track_is_refused_and_not_queued(log: EventLog) -> None:
    request = delivery.request_refresh(log, lambda: ["acme/widgets"])

    assert request("acme/other", 3) is False
    assert log.last(delivery.REFRESH_STREAM) is None


def test_a_tracked_refresh_is_queued_for_the_worker(log: EventLog, stop: threading.Event) -> None:
    asked: list[tuple[str, int]] = []
    seen = threading.Event()

    def worker(repo: str, number: int) -> None:
        asked.append((repo, number))
        seen.set()

    delivery.follow_refreshes(log, worker, stop)

    assert delivery.request_refresh(log, lambda: ["acme/widgets"])("acme/widgets", 3) is True
    assert seen.wait(WAIT_S)
    assert asked == [("acme/widgets", 3)]


def test_a_refresh_asked_before_the_worker_started_is_not_replayed(log: EventLog, stop: threading.Event) -> None:
    delivery.request_refresh(log, lambda: ["acme/widgets"])("acme/widgets", 1)
    asked: list[tuple[str, int]] = []
    seen = threading.Event()
    delivery.follow_refreshes(log, lambda repo, number: (asked.append((repo, number)), seen.set()), stop)

    delivery.request_refresh(log, lambda: ["acme/widgets"])("acme/widgets", 2)

    assert seen.wait(WAIT_S)
    assert asked == [("acme/widgets", 2)]


def test_each_followed_stream_hands_its_entries_to_its_own_handler_from_the_first(
    log: EventLog, stop: threading.Event
) -> None:
    log.append("machine:events", {"task": "TASK-1"})
    log.append("ci:jobs", {"job": "lint"})
    seen: dict[str, list] = {"machine:events": [], "ci:jobs": []}
    done = threading.Event()

    def taking(stream: str):
        def handle(entry) -> None:
            seen[stream].append(entry.fields)
            done.set() if all(seen.values()) else None

        return handle

    delivery.follow_events(log, Feed(), {name: taking(name) for name in seen}, stop)

    assert done.wait(WAIT_S)
    assert seen == {"machine:events": [{"task": "TASK-1"}], "ci:jobs": [{"job": "lint"}]}


def test_the_workers_actor_notes_reach_the_serving_feed(log: EventLog, stop: threading.Event) -> None:
    serving = Feed()
    delivery.follow_notes(log, serving, stop)
    worker = delivery.NotingFeed(Feed(), log)

    worker.note_actor("TASK-1", "task-actor")
    worker.note_actor("TASK-2", None)

    deadline = threading.Event()
    for _ in range(100):
        if len(serving.notes) == 2:
            break
        deadline.wait(0.05)
    assert serving.notes == [("TASK-1", "task-actor"), ("TASK-2", None)]


def test_a_noting_feed_still_answers_for_the_feed_it_wraps(log: EventLog) -> None:
    feed = Feed()
    feed.set_pulls(PULLS, ANSWERS)

    assert delivery.NotingFeed(feed, log).pulls() == PULLS


def test_the_workers_metrics_are_served_from_the_log(log: EventLog) -> None:
    delivery.publish_metrics(log, "starpulse_task_actor_refusals_total 2\n")

    assert delivery.metrics_of(log)() == "starpulse_task_actor_refusals_total 2\n"


def test_no_metrics_before_the_worker_has_published_any(log: EventLog) -> None:
    assert delivery.metrics_of(log)() == ""


def _pull(state: str, checks: str, fetched: float) -> dict:
    return {
        "repo": "acme/widgets",
        "number": 7,
        "state": state,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "baseRefName": "main",
        "headRefOid": "a" * 40,
        "body": "",
        "checks": checks,
        "requiredChecks": [],
        "threads": 0,
        "updatedAt": "2026-10-18T18:00:00Z",
        "mergedAt": None,
        "mergeSha": None,
        "fetchedAt": fetched,
        "detail": None,
    }


def test_a_save_the_worker_makes_reaches_the_record_the_serving_store_holds(log: EventLog, stop: threading.Event) -> None:
    worker = PullStore(log.engine)
    delivery.announce_saves(worker, log)
    worker.save([_pull("OPEN", "pending", 100.0)])
    serving = PullStore(log.engine)
    refreshed = threading.Event()
    serving.subscribe(refreshed.set)
    delivery.follow_saves(serving, log, stop, log.head() or 0)

    worker.save([_pull("OPEN", "pass", 200.0)])

    assert refreshed.wait(WAIT_S)
    assert [(pull["checks"], pull["fetchedAt"]) for pull in serving.find(repo="acme/widgets", number=7)] == [
        ("pass", 200.0)
    ]


def test_a_serving_store_that_saves_announces_nothing(log: EventLog) -> None:
    PullStore(log.engine).save([_pull("OPEN", "pass", 100.0)])

    assert log.last(delivery.SAVED_STREAM) is None
