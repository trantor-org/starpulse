"""The Temporal adapter shows each workflow type as a `Dag`: its running workflows as `active` runs (current activity, attempt,
last failure) and its last day's closed ones, failed first-class, as `recent` runs."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, unquote_plus, urlparse

from starpulse.board.model.adapter_types import ADAPTER_CONTEXTS, BUILT_IN, module_name
from starpulse.contracts.adapters import Dag
from starpulse.runs import temporal
from starpulse.runtime import worker

BASE = "http://temporal.invalid:8233"
NOW = datetime(2026, 10, 31, 15, 0, 0, tzinfo=UTC)


def execution(workflow_id: str, run_id: str, kind: str, status: str, start: str, close: str | None = None) -> dict:
    return {
        "execution": {"workflowId": workflow_id, "runId": run_id},
        "type": {"name": kind},
        "status": f"WORKFLOW_EXECUTION_STATUS_{status}",
        "startTime": start,
        "closeTime": close,
    }


def pending(activity: str, attempt: int, last_failure: dict | None = None) -> dict:
    out = {"activityType": {"name": activity}, "attempt": attempt, "lastStartedTime": "2026-10-31T14:50:00.5Z"}
    return out | ({"lastFailure": last_failure} if last_failure else {})


class FakeTemporal:
    """The visibility, describe and history-reverse answers of one server, and the calls made."""

    def __init__(self, listed: dict[str, list[dict]], pendings: dict[str, list[dict]], histories: dict[str, list[dict]]):
        self.listed, self.pendings, self.histories = listed, pendings, histories
        self.calls: list[str] = []
        self.down = ""

    def __call__(self, url: str) -> dict:
        self.calls.append(url)
        if self.down:
            raise OSError(self.down)
        parts = urlparse(url)
        path = unquote(parts.path).removeprefix("/api/v1/namespaces/default/workflows")
        if not path:
            query = parse_qs(parts.query)["query"][0]
            key = "running" if 'ExecutionStatus="Running"' in query else "failed" if "Failed" in query else "closed"
            return {"executions": self.listed.get(key, [])}
        workflow_id = path.removeprefix("/").removesuffix("/history-reverse")
        if path.endswith("/history-reverse"):
            return {"history": {"events": self.histories[workflow_id]}}
        return {"pendingActivities": self.pendings.get(workflow_id, [])}


def failed_history(activity: str, attempt: int, cause: str) -> list[dict]:
    info = {"startedEventId": "11", "activityType": {"name": activity}}
    failure = {"message": "Activity task failed", "cause": {"message": cause}, "activityFailureInfo": info}
    return [
        {
            "eventId": "16",
            "eventType": "EVENT_TYPE_WORKFLOW_EXECUTION_FAILED",
            "workflowExecutionFailedEventAttributes": {"failure": failure},
        },
        {
            "eventId": "11",
            "eventType": "EVENT_TYPE_ACTIVITY_TASK_STARTED",
            "activityTaskStartedEventAttributes": {"attempt": attempt},
        },
    ]


class Sink:
    def __init__(self) -> None:
        self.reports: list[tuple[list[dict] | None, str | None]] = []

    def set_dags(self, dags: list[dict] | None, error: str | None) -> None:
        self.reports.append((dags, error))


LIFECYCLE = execution(
    "task-lifecycle/TASK-10434/trantor-org/trantor", "run-1", "task_lifecycle", "RUNNING", "2026-10-31T14:51:32.261922Z"
)
FAILED = execution(
    "TASK-10232", "run-2", "task_phases", "FAILED", "2026-10-30T23:18:56.531623Z", "2026-10-31T05:18:59.892121Z"
)
DONE = execution(
    "TASK-10300", "run-3", "task_phases", "COMPLETED", "2026-10-31T10:00:00Z", "2026-10-31T10:05:00Z"
)


def server(**overrides) -> FakeTemporal:
    listed = {"running": [LIFECYCLE], "failed": [FAILED], "closed": [DONE, FAILED]}
    pendings = {LIFECYCLE["execution"]["workflowId"]: [pending("deliver_steps", 1)]}
    histories = {"TASK-10232": failed_history("park_task", 3, "park exited 4\nstdout tail: x")}
    return FakeTemporal(overrides.get("listed", listed), overrides.get("pendings", pendings), histories)


def listing(fake: FakeTemporal) -> list[dict]:
    return temporal.Poller(Sink(), fake, BASE).listing(NOW)


def by_name(dags: list[dict]) -> dict[str, dict]:
    return {dag["name"]: dag for dag in dags}


def test_a_workflow_id_names_its_task_or_none() -> None:
    assert temporal.task_of("task-lifecycle/TASK-10434/trantor-org/trantor") == "TASK-10434"
    assert temporal.task_of("TASK-9708") == "TASK-9708"
    assert temporal.task_of("alert-investigation-grafana-1") is None
    assert temporal.task_of("skill-eval-20261031-6323c478730a") is None


def test_each_workflow_type_is_a_job_even_with_no_runs() -> None:
    dags = listing(server(listed={}))

    assert [d["name"] for d in dags] == ["task_lifecycle", "task_phases", "AlertInvestigationWorkflow"]
    assert {d["status"] for d in dags} == {"not_started"}
    assert all(Dag.model_validate(d) for d in dags)


def test_a_running_workflow_is_an_active_run_with_task_activity_and_attempt() -> None:
    dags = by_name(listing(server()))

    dag = dags["task_lifecycle"]
    assert dag["status"] == "running"
    assert dag["active"] == [
        {
            "runId": "run-1",
            "status": "running",
            "raw": None,
            "startedAt": "2026-10-31T14:51:32Z",
            "step": "deliver_steps",
            "stepStartedAt": "2026-10-31T14:50:00Z",
            "steps": {"deliver_steps": "running"},
            "task": "TASK-10434",
            "attempt": 1,
            "failure": None,
        }
    ]
    assert Dag.model_validate(dag)


def test_a_retrying_activity_shows_its_attempt_and_the_deepest_failure_line() -> None:
    last = {"message": "Activity task failed", "cause": {"message": "ci_head exited 2\nlogs: nothing"}}
    pendings = {LIFECYCLE["execution"]["workflowId"]: [pending("ci_head", 2, last)]}

    run = by_name(listing(server(pendings=pendings)))["task_lifecycle"]["active"][0]

    assert (run["step"], run["attempt"], run["failure"]) == ("ci_head", 2, "ci_head exited 2")


def test_a_running_workflow_between_activities_has_no_step() -> None:
    run = by_name(listing(server(pendings={})))["task_lifecycle"]["active"][0]

    assert (run["step"], run["stepStartedAt"], run["attempt"], run["steps"]) == ("", "", None, {})


def test_a_failed_workflow_is_a_recent_run_with_its_activity_attempt_and_failure() -> None:
    dag = by_name(listing(server()))["task_phases"]

    failed = next(r for r in dag["recent"] if r["runId"] == "run-2")
    assert failed == {
        "runId": "run-2",
        "task": "TASK-10232",
        "url": f"{BASE}/namespaces/default/workflows/TASK-10232/run-2",
        "status": "failed",
        "raw": "FAILED",
        "startedAt": "2026-10-30T23:18:56Z",
        "finishedAt": "2026-10-31T05:18:59Z",
        "params": {},
        "steps": {"park_task": "failed"},
        "attempt": 3,
        "failure": "park exited 4",
    }
    assert [r["runId"] for r in dag["recent"]] == ["run-3", "run-2"]  # newest finish first, once each
    assert dag["status"] == "succeeded"  # the latest closed run, not the failure behind it
    assert Dag.model_validate(dag)


def test_a_closed_run_is_read_once_across_polls() -> None:
    fake = server()
    poller = temporal.Poller(Sink(), fake, BASE)

    poller.listing(NOW)
    poller.listing(NOW)

    assert sum("history-reverse" in call for call in fake.calls) == 1


def test_the_poll_reports_an_unreachable_or_malformed_server_as_an_error() -> None:
    sink, fake = Sink(), server()
    poller = temporal.Poller(sink, fake, BASE)

    fake.down = "connection refused"
    poller.read()
    fake.down = ""
    fake.listed = {"running": [{"execution": {}}]}
    poller.read()

    assert sink.reports[0] == (None, "connection refused")
    assert sink.reports[1][0] is None and sink.reports[1][1].startswith("unreadable response (KeyError")


def test_the_poll_reports_the_listing() -> None:
    sink = Sink()

    temporal.Poller(sink, server(), BASE).read()

    dags, error = sink.reports[0]
    assert error is None and [d["name"] for d in dags] == ["task_lifecycle", "task_phases", "AlertInvestigationWorkflow"]
    json.dumps(dags)


def test_the_adapter_is_a_built_in_opt_in_worker_with_no_start() -> None:
    assert BUILT_IN["temporal"] == module_name("temporal") == "starpulse.runs.temporal"
    assert "temporal" in ADAPTER_CONTEXTS and "temporal" in worker.OPT_IN
    assert temporal.WORKER == "temporal" and temporal.start(BASE) is None


def test_each_listing_is_limited_to_the_three_workflow_types() -> None:
    fake = server()
    listing(fake)

    listings = [unquote_plus(c) for c in fake.calls if "history" not in c and "query=" in c]
    assert listings and all(
        'WorkflowType IN ("task_lifecycle","task_phases","AlertInvestigationWorkflow")' in c for c in listings
    )
