"""The Temporal adapter: each Workflow Type as a workflow whose latest execution is its run, followed through a bounded set, on a fake Temporal."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest
from starpulse.board.model.adapter_types import BUILT_IN, module_name
from starpulse.contracts.adapters import TaskKeys
from starpulse.runs import temporal
from starpulse.runtime import worker
from starpulse.runtime.adapter_kit import RunsAdapterKit
from temporalio.api.common.v1 import ActivityType
from temporalio.api.enums.v1 import EventType
from temporalio.api.history.v1 import (
    ActivityTaskCompletedEventAttributes,
    ActivityTaskFailedEventAttributes,
    ActivityTaskScheduledEventAttributes,
    ActivityTaskStartedEventAttributes,
    HistoryEvent,
)

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)


def execution(kind: str, run: str, status: str = "COMPLETED", minutes: int = 0, length: int = 10) -> temporal.Execution:
    """An execution of `kind` started `minutes` before `NOW`; a closed one closed a minute after it started."""
    started = NOW - timedelta(minutes=minutes)
    closed = None if status == "RUNNING" else started + timedelta(minutes=1)
    return temporal.Execution(kind, f"{kind}-id", run, status, started, closed, length)


class FakeTemporal:
    """A Temporal that lists `listed` and answers each run's Activities from `activities`; `down` fails every call,
    a run in `failing` fails its history read."""

    def __init__(self, listed=(), activities=None, failing=()) -> None:
        self.listed = list(listed)
        self.activities_of = activities or {}
        self.failing = set(failing)
        self.down: str | None = None
        self.since: list[datetime] = []
        self.reads: list[str] = []

    def executions(self, since: datetime):
        self.since.append(since)
        if self.down:
            raise OSError(self.down)
        return iter(self.listed)

    def activities(self, run: temporal.Execution) -> list[temporal.Activity]:
        self.reads.append(run.run_id)
        if self.down or run.run_id in self.failing:
            raise OSError("history unreadable")
        return self.activities_of.get(run.run_id, [])


class Sink:
    def __init__(self) -> None:
        self.dags: list[dict] | None = None
        self.error: str | None = None

    def set_dags(self, dags, error, pools=None, startable=None, cpu=None) -> None:
        self.dags, self.error = dags, error


def follower(fake: FakeTemporal, sink: Sink | None = None, **bounds) -> temporal.Follower:
    return temporal.Follower(sink or Sink(), fake, clock=lambda: NOW, **bounds)


def test_each_workflow_type_is_a_workflow_whose_latest_execution_is_its_run_and_its_activities_its_steps() -> None:
    fake = FakeTemporal(
        [execution("phases", "new", "RUNNING", minutes=1), execution("phases", "old", minutes=9)],
        {"new": [temporal.Activity("build", "succeeded", None), temporal.Activity("deliver", "running", None)]},
    )
    sink = Sink()
    follower(fake, sink).read()
    (dag,) = sink.dags
    assert (dag["name"], dag["runId"], dag["status"], dag["finishedAt"]) == ("phases", "new", "running", "")
    assert [(step["name"], step["status"]) for step in dag["steps"]] == [("build", "succeeded"), ("deliver", "running")]
    assert fake.reads == ["new"]


def test_the_follow_set_holds_at_most_its_limit_of_types_the_most_recently_started_kept() -> None:
    fake = FakeTemporal([execution(f"t{i}", f"r{i}", minutes=i) for i in range(5)])
    sink = Sink()
    runs = follower(fake, sink, limit=3)
    runs.read()
    assert [dag["name"] for dag in sink.dags] == ["t0", "t1", "t2"]
    fake.listed = [execution(f"u{i}", f"s{i}", minutes=-i) for i in range(50)]
    runs.read()
    assert len(sink.dags) == len(runs.followed) == 3


def test_an_execution_whose_history_read_keeps_failing_is_dropped_from_the_follow_set_and_shown_without_steps() -> None:
    fake = FakeTemporal([execution("phases", "bad", "RUNNING")], failing={"bad"})
    sink = Sink()
    runs = follower(fake, sink, failures=2)
    for length in range(5):
        fake.listed = [execution("phases", "bad", "RUNNING", length=10 + length)]
        runs.read()
    assert fake.reads == ["bad", "bad"]
    assert (sink.dags[0]["runId"], sink.dags[0]["steps"], sink.error) == ("bad", [], None)


def test_a_history_is_read_again_only_when_its_length_changed() -> None:
    fake = FakeTemporal([execution("phases", "r", "RUNNING", length=4)])
    runs = follower(fake)
    runs.read()
    runs.read()
    fake.listed = [execution("phases", "r", "RUNNING", length=6)]
    runs.read()
    assert fake.reads == ["r", "r"]


def test_through_an_outage_the_last_reading_stays_and_the_next_listing_starts_at_the_last_good_one() -> None:
    fake = FakeTemporal([execution("phases", "r")])
    sink = Sink()
    runs = follower(fake, sink)
    runs.read()
    shown = sink.dags
    fake.down = "connection refused"
    for _ in range(3):
        runs.read()
    assert (sink.dags, sink.error) == (None, "connection refused")
    fake.down = None
    runs.read()
    assert sink.dags == shown
    assert fake.since[0] == NOW - temporal.LOOKBACK
    assert set(fake.since[1:]) == {NOW - temporal.OVERLAP}


def test_a_history_reads_as_its_activities_in_the_order_scheduled_each_at_its_latest_state() -> None:
    def scheduled(event_id: int, name: str) -> HistoryEvent:
        attributes = ActivityTaskScheduledEventAttributes(activity_type=ActivityType(name=name))
        return HistoryEvent(
            event_id=event_id,
            event_type=EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED,
            activity_task_scheduled_event_attributes=attributes,
        )

    events = [
        scheduled(5, "build"),
        HistoryEvent(
            event_type=EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED,
            activity_task_started_event_attributes=ActivityTaskStartedEventAttributes(scheduled_event_id=5),
        ),
        HistoryEvent(
            event_type=EventType.EVENT_TYPE_ACTIVITY_TASK_FAILED,
            activity_task_failed_event_attributes=ActivityTaskFailedEventAttributes(scheduled_event_id=5),
        ),
        scheduled(9, "deliver"),
        scheduled(12, "build"),
        HistoryEvent(
            event_type=EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED,
            activity_task_completed_event_attributes=ActivityTaskCompletedEventAttributes(scheduled_event_id=12),
        ),
    ]
    assert temporal.activities_of(events) == [
        temporal.Activity("build", "succeeded", None),
        temporal.Activity("deliver", "queued", None),
    ]


@pytest.mark.parametrize(
    ("url", "target"),
    [("temporal.local:7233", ("temporal.local:7233", "default")), ("10.0.0.1:7233/agents", ("10.0.0.1:7233", "agents"))],
)
def test_the_url_is_the_frontend_address_and_an_optional_namespace(url: str, target: tuple[str, str]) -> None:
    assert temporal.target(url) == target


def test_the_temporal_type_is_built_in_and_runs_in_its_own_worker() -> None:
    assert (BUILT_IN["temporal"], module_name("temporal")) == ("starpulse.runs.temporal",) * 2
    assert temporal.WORKER == "temporal"
    assert "temporal" in worker.OPT_IN


class TestTemporalAdapter(RunsAdapterKit):
    """The adapter is Workflow Executions in, `Dag` records out; a Workflow Type carries no task keys."""

    keys = TaskKeys(key=re.compile(r"PROJ-\d+"), branch=re.compile(r"feature/(PROJ-\d+)"))
    branches = {"feature/PROJ-1": "PROJ-1", "main": None}

    def produce(self) -> list[dict]:
        fake = FakeTemporal(
            [execution("a", "1", "RUNNING"), execution("b", "2", "FAILED", 3), execution("c", "3", "TERMINATED", 5)],
            {"1": [temporal.Activity("x", "running", None)], "2": [temporal.Activity("y", "failed", "timed_out")]},
        )
        sink = Sink()
        follower(fake, sink).read()
        return sink.dags
