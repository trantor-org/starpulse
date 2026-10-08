"""A task's pull requests, as GitHub answers them poll by poll, become its trail on the shipped `ci` machine."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from starpulse.projections.board_feed import BoardFeed
from starpulse.projections.ci import CI_MACHINES
from starpulse.projections.ci_trail import CiTrail, parse
from starpulse.projections.machine_tasks import MachineTasks
from starpulse.store import events
from starpulse.store.event_log import EventLog, Tail
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
        self.tail = Tail(self.log, events.STREAM)

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
        return len(Tail(self.log, events.STREAM).poll())


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
