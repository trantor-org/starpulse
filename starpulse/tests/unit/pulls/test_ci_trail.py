"""A task's pull requests, as GitHub answers them poll by poll, become its trail on the shipped `ci` machine."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from starpulse.pulls.ci import CI_MACHINES
from starpulse.pulls.ci_trail import CiTrail, parse
from starpulse._internal.config.config import Producer
from starpulse.board.board_feed import BoardFeed
from starpulse.board.machine_tasks import MachineTasks
from starpulse._internal.kit.adapter_kit import task
from starpulse.pulls.github import GITHUB_MACHINES
from starpulse.pulls.pull_events import RecordProjection
from starpulse.pulls.pulls import PullStore
from starpulse.runs.cloudevents import CloudEventsIngest
from starpulse.event_log import events
from starpulse.event_log.event_log import Entry, EventLog, Tail
from starpulse.tests.machines import MACHINES

TASK = "PROJ-7"
FIRST, SECOND = "https://github.com/acme/widgets/pull/1", "https://github.com/acme/widgets/pull/2"
START = datetime(2026, 10, 7, 16, 0, tzinfo=UTC)


def _epoch(minute: float) -> float:
    return (START + timedelta(minutes=minute)).timestamp()


def _iso(minute: float) -> str:
    return (START + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _suite(status: str, conclusion: str | None, created: float, updated: float, attempt: int = 1) -> dict:
    return {
        "status": status,
        "conclusion": conclusion,
        "createdAt": _iso(created),
        "updatedAt": _iso(updated),
        "workflowRun": {"runAttempt": attempt},
    }


def _running(created: float, updated: float | None = None, attempt: int = 1) -> dict:
    return _suite("IN_PROGRESS", None, created, created if updated is None else updated, attempt)


def _done(conclusion: str, created: float, updated: float, attempt: int = 1) -> dict:
    return _suite("COMPLETED", conclusion, created, updated, attempt)


def _node(
    *,
    opened: float = 0,
    commits: dict[str, list[dict]],
    force_pushes: tuple[tuple[float, str], ...] = (),
    mergeable: str = "MERGEABLE",
    merged_at: float | None = None,
) -> dict:
    """A GraphQL `pullRequest` node as the history query answers it."""
    return {
        "createdAt": _iso(opened),
        "mergeable": mergeable,
        "merged": merged_at is not None,
        "mergedAt": None if merged_at is None else _iso(merged_at),
        "commits": {
            "nodes": [{"commit": {"oid": oid, "checkSuites": {"nodes": suites}}} for oid, suites in commits.items()]
        },
        "timelineItems": {
            "nodes": [{"createdAt": _iso(minute), "afterCommit": {"oid": oid}} for minute, oid in force_pushes]
        },
    }


class _Trail:
    """A `CiTrail` on a real event log, with the machine tasks that follow it, and the poll clock in minutes."""

    def __init__(self, tmp_path: Path) -> None:
        self.log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
        self.minute = 0.0
        self.trail = CiTrail(self.log, clock=lambda: _epoch(self.minute))
        self.feed = BoardFeed(None, machines={**MACHINES, **CI_MACHINES})
        self.tasks = MachineTasks(self.feed)
        self.tail = Tail.replay(self.log, events.STREAM)

    def poll(self, minute: float, **pulls: dict) -> None:
        """One poll at `minute`: the nodes by pull request URL, for the one task."""
        self.minute = minute
        urls = {"first": FIRST, "second": SECOND}
        self.trail.record({TASK: [parse(urls[name], node) for name, node in pulls.items()]})
        for entry in self.tail.poll():
            self.tasks.handle_entry(f"{entry.id}-0", entry.fields)

    def agent(self) -> dict:
        agent = self.feed.machine_task("ci", TASK)
        assert agent is not None
        return agent

    def steps(self) -> list[tuple[str, str, float]]:
        return [(step["state"], step["event"], step["at"]) for step in self.agent()["trail"]]

    def logged(self) -> int:
        return len(Tail.replay(self.log, events.STREAM).poll())


@pytest.fixture
def ci(tmp_path: Path) -> _Trail:
    return _Trail(tmp_path)


def test_a_pull_request_from_push_to_merge_is_the_tasks_trail(ci: _Trail) -> None:
    ci.poll(3, first=_node(commits={"aaa": [_running(1)]}))
    ci.poll(6, first=_node(commits={"aaa": [_done("FAILURE", 1, 5)]}))
    ci.poll(9, first=_node(commits={"aaa": [_running(1, 8, attempt=2)]}))
    ci.poll(12, first=_node(commits={"aaa": [_done("SUCCESS", 1, 11, attempt=2)]}))
    ci.poll(15, first=_node(commits={"aaa": [_done("SUCCESS", 1, 11, attempt=2)]}, mergeable="CONFLICTING"))
    ci.poll(20, first=_node(commits={"bbb": [_running(19)]}, force_pushes=((18, "bbb"),)))
    ci.poll(24, first=_node(commits={"bbb": [_done("SUCCESS", 19, 23)]}, force_pushes=((18, "bbb"),)))
    ci.poll(30, first=_node(commits={"bbb": [_done("SUCCESS", 19, 23)]}, force_pushes=((18, "bbb"),), merged_at=29))

    assert ci.steps() == [
        ("opened", "PR_OPENED", _epoch(0)),
        ("running", "PUSHED", _epoch(1)),
        ("failing", "CHECKS_FAILED", _epoch(5)),
        ("running", "RERUN", _epoch(8)),
        ("passing", "CHECKS_PASSED", _epoch(11)),
        ("conflicting", "CONFLICTED", _epoch(15)),
        ("running", "REBASED", _epoch(18)),
        ("passing", "CHECKS_PASSED", _epoch(23)),
        ("merged", "MERGED", _epoch(29)),
    ]


def test_a_second_pull_request_reopens_the_merged_task_and_the_agent_sits_at_its_state(ci: _Trail) -> None:
    merged = _node(commits={"aaa": [_done("SUCCESS", 1, 4)]}, merged_at=10)
    ci.poll(11, first=merged)
    ci.poll(22, first=merged, second=_node(opened=20, commits={"ccc": [_running(21)]}))

    assert [state for state, _, _ in ci.steps()] == [
        "opened",
        "running",
        "passing",
        "merged",
        "opened",
        "running",
    ]
    assert ci.agent()["state"] == "running"
    assert ci.agent()["trail"][4]["at"] == _epoch(20)


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        pytest.param(
            _node(commits={"aaa": [_done("SUCCESS", 1, 9, attempt=2)]}),
            ["PR_OPENED", "PUSHED", "CHECKS_FAILED", "RERUN", "CHECKS_PASSED"],
            id="a re-run is RERUN, not a push",
        ),
        pytest.param(
            _node(commits={"bbb": [_done("SUCCESS", 5, 8)]}, force_pushes=((4, "bbb"),)),
            ["PR_OPENED", "REBASED", "CHECKS_PASSED"],
            id="a force-push is REBASED, not a push or a re-run",
        ),
    ],
)
def test_re_runs_and_rebases_are_distinct_events(ci: _Trail, node: dict, expected: list[str]) -> None:
    ci.poll(10, first=node)

    assert [event for _, event, _ in ci.steps()] == expected


def test_a_poll_that_sees_nothing_new_records_nothing_even_after_a_restart(ci: _Trail) -> None:
    node = _node(commits={"aaa": [_done("FAILURE", 1, 5)]}, mergeable="CONFLICTING")
    ci.poll(6, first=node)
    recorded = ci.logged()

    ci.poll(7, first=node)
    ci.trail = CiTrail(ci.log, clock=lambda: _epoch(8))
    ci.poll(8, first=node)

    assert ci.logged() == recorded
    assert [event for _, event, _ in ci.steps()] == ["PR_OPENED", "PUSHED", "CHECKS_FAILED", "CONFLICTED"]


def test_a_cancelled_suite_is_neither_a_failure_nor_a_pass_and_a_commit_without_suites_is_no_push(ci: _Trail) -> None:
    ci.poll(
        10,
        first=_node(commits={"old": [], "aaa": [_done("CANCELLED", 1, 3), _running(2)]}),
    )

    assert [event for _, event, _ in ci.steps()] == ["PR_OPENED", "PUSHED"]
    assert ci.agent()["state"] == "running"


def test_an_app_suite_with_no_workflow_run_stuck_queued_does_not_hold_the_checks_open(ci: _Trail) -> None:
    never_ran = {**_suite("QUEUED", None, 1, 1), "workflowRun": None}
    ci.poll(6, first=_node(commits={"aaa": [never_ran, _done("SUCCESS", 1, 5), _done("SUCCESS", 1, 4)]}))

    assert [event for _, event, _ in ci.steps()] == ["PR_OPENED", "PUSHED", "CHECKS_PASSED"]
    assert ci.agent()["state"] == "passing"


PULL = ("acme/widgets", 7)
HEAD, NEXT_HEAD = "a" * 40, "b" * 40


def _job_cloud_event(event_id: str, kind: str, job: str, head: str, minute: int) -> dict:
    """A CI job CloudEvent for pull request 7, the head SHA in `data`, keyed by the job's run."""
    return {
        "specversion": "1.0",
        "id": event_id,
        "source": "ci-bot",
        "type": kind,
        "run": f"run-{event_id}",
        "time": (START + timedelta(minutes=minute)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "machine": "ci-job",
        "actor": "github",
        "data": {"repository": PULL[0], "pr": PULL[1], "head_sha": head, "job": job},
    }


class _PullRequest:
    """A log that CI job CloudEvents are posted to, and the pull request store a projection of it fills."""

    def __init__(self, tmp_path: Path) -> None:
        self.log = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
        producer = Producer("ci-bot", "CI_TOKEN", machines=("ci-job",), actors=("github",))
        self.ingest = CloudEventsIngest({producer.name: producer}, {}, self.log, GITHUB_MACHINES)
        feed = BoardFeed()
        feed.put(task("PROJ-1", "In Progress", references=[f"https://github.com/{PULL[0]}/pull/{PULL[1]}"]))
        self.store = PullStore(create_engine("sqlite://"))
        self.projection = RecordProjection(self.store, feed)
        self.tail = Tail.replay(self.log, events.STREAM)
        opened = {"machine": "github-pull-request", "event": "PR_OPENED", "task": "PROJ-1", "time": str(_epoch(-5))}
        self.projection.handle(Entry(0, events.STREAM, "opened", opened, _epoch(-5)))

    def post(self, *sent: dict) -> None:
        status, _ = self.ingest.write("ci-bot", list(sent))
        assert status == 201
        for entry in self.tail.poll():
            self.projection.handle(entry)

    def record(self) -> dict:
        (record,) = self.store.find(*PULL)
        return record


@pytest.fixture
def pull(tmp_path: Path) -> _PullRequest:
    return _PullRequest(tmp_path)


def test_ci_job_cloud_events_with_a_head_sha_show_on_the_pull_request(pull: _PullRequest) -> None:
    pull.post(
        _job_cloud_event("e1", "JOB_SUCCEEDED", "lint", HEAD, 1),
        _job_cloud_event("e2", "JOB_FAILED", "test", HEAD, 2),
    )

    record = pull.record()
    assert record["headRefOid"] == HEAD
    assert record["requiredChecks"] == [{"name": "lint", "result": "pass"}, {"name": "test", "result": "failing"}]


def test_ci_job_cloud_events_are_read_from_machine_events_not_only_ci_jobs(pull: _PullRequest) -> None:
    pull.post(_job_cloud_event("e1", "JOB_FAILED", "lint", HEAD, 1))
    pull.post(_job_cloud_event("e2", "JOB_SUCCEEDED", "test", NEXT_HEAD, 2))

    record = pull.record()
    assert (record["headRefOid"], record["requiredChecks"]) == (NEXT_HEAD, [{"name": "test", "result": "pass"}])
    assert Tail.replay(pull.log, "ci:jobs").poll() == []
