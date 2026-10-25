"""The PR store follows the lifecycle events of the tasks whose pull requests it holds."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import task
from starpulse.pulls.pull_events import RecordProjection
from starpulse.pulls.pulls import PullStore
from starpulse.event_log.event_log import Entry, EventLog
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore, NewEvent

URL = "https://github.com/acme/widgets/pull/7"
PULL = ("acme/widgets", 7)
T0 = 1_700_000_000.0


def _entry(machine: str, event: str, key: str = "PROJ-1", at: float = T0, **extra: str) -> Entry:
    fields = {"event_id": f"{machine}-{event}-{at}", "machine": machine, "event": event, "task": key, "time": str(at)}
    return Entry(1, "machine:events", fields["event_id"], fields | extra, at)


def _projection(references: list[str] | None = None, **fields: str) -> tuple[RecordProjection, PullStore, list[int]]:
    feed = BoardFeed()
    feed.put(task("PROJ-1", "In Progress", references=[URL] if references is None else references, **fields))
    store = PullStore(create_engine("sqlite://"))
    changes: list[int] = []
    return RecordProjection(store, feed, lambda: changes.append(1)), store, changes


def _record(store: PullStore) -> dict:
    (record,) = store.find(*PULL)
    return record


OPEN = ("github-pull-request", "PR_OPENED")


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([OPEN], {"state": "OPEN", "isDraft": True, "checks": "none", "threads": 0}),
        ([OPEN, ("in-progress", "PR_READY")], {"isDraft": False}),
        ([OPEN, ("deliver", "PR_READY")], {"isDraft": False}),
        (
            [OPEN, ("github-pull-request", "CHECKS_PASSED"), ("deliver", "PUSHED")],
            {"checks": "pending", "requiredChecks": [], "mergeable": "UNKNOWN"},
        ),
        ([OPEN, ("github-pull-request", "CHECKS_PASSED")], {"checks": "pass"}),
        ([OPEN, ("github-pull-request", "CHECKS_FAILED")], {"checks": "failing"}),
        ([OPEN, ("github-pull-request", "CHECKS_PASSED"), ("in-progress", "PUSHED")], {"checks": "pending"}),
        ([OPEN, ("github-pull-request", "CONFLICTED")], {"mergeable": "CONFLICTING"}),
        (
            [OPEN, ("github-pull-request", "CONFLICTED"), ("github-pull-request", "MERGEABLE")],
            {"mergeable": "MERGEABLE"},
        ),
        ([OPEN, ("github-pull-request", "PR_MERGED")], {"state": "MERGED"}),
        ([OPEN, ("github-pull-request", "PR_CLOSED")], {"state": "CLOSED"}),
    ],
)
def test_each_event_updates_its_field(events: list[tuple[str, str]], expected: dict) -> None:
    projection, store, _ = _projection()

    for offset, (machine, event) in enumerate(events):
        projection.handle(_entry(machine, event, at=T0 + offset))

    record = _record(store)
    assert {name: record[name] for name in expected} == expected


def test_a_thread_count_event_sets_the_threads() -> None:
    projection, store, _ = _projection()

    projection.handle(_entry(*OPEN))
    projection.handle(_entry("github-pull-request", "THREADS_CHANGED", at=T0 + 1, unresolved="3"))

    assert _record(store)["threads"] == 3


def test_the_record_is_dated_by_the_last_event() -> None:
    projection, store, _ = _projection()

    projection.handle(_entry(*OPEN, at=T0))
    projection.handle(_entry("github-pull-request", "CHECKS_PASSED", at=T0 + 60))

    assert _record(store)["fetchedAt"] == T0 + 60


def test_an_opened_record_answers_the_task_and_session_lookup() -> None:
    projection, store, _ = _projection(assignee="session_abc")

    projection.handle(_entry(*OPEN))

    assert [(r["repo"], r["number"]) for r in store.find(body_contains="session_abc")] == [PULL]
    assert [(r["repo"], r["number"]) for r in store.find(body_contains="PROJ-1")] == [PULL]


def test_an_event_of_a_task_the_board_does_not_hold_is_ignored() -> None:
    projection, store, changes = _projection()

    projection.handle(_entry(*OPEN, key="PROJ-99"))

    assert store.find() == []
    assert changes == []


def test_an_event_of_a_task_citing_no_pull_request_is_ignored() -> None:
    projection, store, changes = _projection(references=[])

    projection.handle(_entry(*OPEN))

    assert store.find() == []
    assert changes == []


def test_an_event_of_another_machine_is_ignored() -> None:
    projection, store, _ = _projection()

    projection.handle(_entry("board", "PR_OPENED"))
    projection.handle(_entry("github-pull-request", "WORKTREE_READY"))

    assert store.find() == []


def test_replaying_the_events_changes_nothing() -> None:
    projection, store, changes = _projection()
    events = [
        _entry(*OPEN, at=T0),
        _entry("in-progress", "PR_READY", at=T0 + 1),
        _entry("github-pull-request", "CHECKS_FAILED", at=T0 + 2),
        _entry("github-pull-request", "CHECKS_PASSED", at=T0 + 3),
    ]
    for entry in events:
        projection.handle(entry)
    before, announced = _record(store), len(changes)

    for entry in events:
        projection.handle(entry)

    assert _record(store) == before
    assert len(changes) == announced


def test_an_event_older_than_the_record_does_not_undo_it() -> None:
    projection, store, _ = _projection()
    projection.handle(_entry(*OPEN, at=T0))
    projection.handle(_entry("github-pull-request", "CHECKS_PASSED", at=T0 + 5))

    projection.handle(_entry("github-pull-request", "CHECKS_FAILED", at=T0 + 1))

    assert _record(store)["checks"] == "pass"


def test_a_merged_record_ignores_a_later_push() -> None:
    projection, store, _ = _projection()
    projection.handle(_entry(*OPEN, at=T0))
    projection.handle(_entry("github-pull-request", "PR_MERGED", at=T0 + 1))

    projection.handle(_entry("in-progress", "PUSHED", at=T0 + 2))

    assert _record(store)["state"] == "MERGED"
    assert _record(store)["checks"] == "none"


def test_a_close_is_not_taken_for_one_of_two_open_pull_requests() -> None:
    other = "https://github.com/acme/skills/pull/2"
    projection, store, _ = _projection(references=[URL, other])
    projection.handle(_entry(*OPEN, at=T0))

    projection.handle(_entry("github-pull-request", "PR_MERGED", at=T0 + 1))

    assert {r["state"] for r in store.find()} == {"OPEN"}


def test_a_close_naming_its_pull_request_closes_only_that_one_of_two_open() -> None:
    other = "https://github.com/acme/skills/pull/2"
    projection, store, _ = _projection(references=[URL, other])
    projection.handle(_entry(*OPEN, at=T0))

    projection.handle(_entry("github-pull-request", "PR_CLOSED", at=T0 + 1, repository="acme/skills", pr="2"))

    assert {(r["repo"], r["state"]) for r in store.find()} == {("acme/widgets", "OPEN"), ("acme/skills", "CLOSED")}


def test_a_close_of_a_pull_request_already_closed_does_not_close_the_last_open_one() -> None:
    other = "https://github.com/acme/skills/pull/2"
    projection, store, _ = _projection(references=[URL, other])
    projection.handle(_entry(*OPEN, at=T0))
    projection.handle(_entry("github-pull-request", "PR_CLOSED", at=T0 + 1, repository="acme/skills", pr="2"))

    projection.handle(_entry("github-pull-request", "PR_CLOSED", at=T0 + 2, repository="acme/skills", pr="2"))

    assert {(r["repo"], r["state"]) for r in store.find()} == {("acme/widgets", "OPEN"), ("acme/skills", "CLOSED")}


def test_a_ready_event_reaches_every_pull_request_of_the_task() -> None:
    other = "https://github.com/acme/skills/pull/2"
    projection, store, _ = _projection(references=[URL, other])
    projection.handle(_entry(*OPEN, at=T0))

    projection.handle(_entry("in-progress", "PR_READY", at=T0 + 1))

    assert {r["isDraft"] for r in store.find()} == {False}
    assert len(store.find()) == 2


def _job(job: str = "test", result: str = "succeeded", head: str = "a" * 40, at: float = T0, pr: str = "7") -> Entry:
    fields = {"repository": "acme/widgets", "pr": pr, "head_sha": head, "job": job, "result": result, "time": str(at)}
    return Entry(1, "ci:jobs", f"{job}-{head}-{at}", fields, at)


def test_a_job_result_sets_the_head_and_the_result_of_that_check() -> None:
    projection, store, _ = _projection()
    projection.handle(_entry(*OPEN, at=T0))

    projection.handle_job(_job("lint", "succeeded", at=T0 + 1))
    projection.handle_job(_job("test", "failed", at=T0 + 2))

    record = _record(store)
    assert record["headRefOid"] == "a" * 40
    assert record["requiredChecks"] == [{"name": "lint", "result": "pass"}, {"name": "test", "result": "failing"}]


def test_a_job_of_a_new_head_starts_the_checks_over() -> None:
    projection, store, _ = _projection()
    projection.handle(_entry(*OPEN, at=T0))
    projection.handle_job(_job("lint", "failed", head="a" * 40, at=T0 + 1))

    projection.handle_job(_job("test", "succeeded", head="b" * 40, at=T0 + 2))

    record = _record(store)
    assert (record["headRefOid"], record["requiredChecks"]) == ("b" * 40, [{"name": "test", "result": "pass"}])


def test_a_job_of_a_pull_request_the_store_does_not_hold_or_without_one_is_ignored() -> None:
    projection, store, changes = _projection()

    projection.handle_job(_job())
    projection.handle_job(_job(pr=""))

    assert store.find() == []
    assert changes == []


def test_a_canceled_job_says_nothing_of_its_check() -> None:
    projection, store, _ = _projection()
    projection.handle(_entry(*OPEN, at=T0))

    projection.handle_job(_job("test", "canceled", at=T0 + 1))

    assert _record(store)["requiredChecks"] == []


def test_replaying_the_jobs_changes_nothing() -> None:
    projection, store, changes = _projection()
    projection.handle(_entry(*OPEN, at=T0))
    jobs = [_job("lint", at=T0 + 1), _job("test", "failed", at=T0 + 2)]
    for entry in jobs:
        projection.handle_job(entry)
    before, announced = _record(store), len(changes)

    for entry in jobs:
        projection.handle_job(entry)

    assert _record(store) == before
    assert len(changes) == announced


def test_a_merge_of_a_pr_added_after_startup_lands_on_the_record(tmp_path: Path) -> None:
    engine = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine
    events = EventStore(engine)
    created = NewEvent(type="TaskCreated", payload={"title": "Task", "state": "In Progress"}, actor="adin", writer="operator")
    events.append("task", "PROJ-1", 0, [created])
    Projector(engine, events).catch_up()
    store = PullStore(create_engine("sqlite://"))
    projection = RecordProjection(store, BoardFeed(read_model=ReadModel(engine)))

    referenced = NewEvent(
        type="FieldsEdited", payload={"changes": {"references": [URL]}}, actor="adin", writer="operator"
    )
    events.append("task", "PROJ-1", 1, [referenced])
    Projector(engine, events).catch_up()
    projection.handle(_entry("github-pull-request", "PR_OPENED", at=T0))
    projection.handle(_entry("github-pull-request", "PR_MERGED", at=T0 + 1))

    assert _record(store)["state"] == "MERGED"
