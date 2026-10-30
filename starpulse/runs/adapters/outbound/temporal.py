"""The Temporal adapter: each of a server's workflow types as a workflow, its running executions as active runs and the last day's closed ones as recent runs.

`url` is the Temporal UI server's address (`http://host:8233`), whose HTTP API lists executions of the default namespace.
`Poller.listing` reads the three engine-run types, `task_lifecycle`, `task_phases` and `AlertInvestigationWorkflow`, into
the `runs` contract's `Dag` records: a running execution is an `ActiveRun` with the activity it is on, that activity's
attempt and the failure its last attempt ended in; a closed one is a `RecentRun`, and a failed one carries the activity
it failed on, that activity's attempt and the failure. A closed execution never changes, so its history is read once.
`follow` lists the server every `POLL_INTERVAL` seconds, since the server pushes no change. `start` is None, so a workflow
has no Run now: these workflows start from the Board's lifecycle, not from the page.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from starpulse.contracts.adapters import RunsSink, RunStatus
from starpulse.event_log.event_log import EventLog

#: The workflow types shown, in the order the page lists them.
TYPES = ("task_lifecycle", "task_phases", "AlertInvestigationWorkflow")

#: Seconds between two listings of the server.
POLL_INTERVAL = 15.0
#: The worker that runs this adapter (`starpulse.runs.opt_in`): `serve` supervises it as a child.
WORKER = "temporal"

#: How many closed runs, failed and of any status, each listing asks for; the server answers newest first.
RECENT_LIMIT = 40
#: How many running executions a listing asks for.
ACTIVE_LIMIT = 200
_HISTORY_EVENTS = 20
_TIMEOUT = 10.0
_NAMESPACE = "/api/v1/namespaces/default"
_TASK = re.compile(r"TASK-\d+", re.IGNORECASE)
_STATUS: dict[str, RunStatus] = {
    "RUNNING": "running",
    "COMPLETED": "succeeded",
    "FAILED": "failed",
    "TIMED_OUT": "failed",
    "TERMINATED": "aborted",
    "CANCELED": "aborted",
}
_FAILURE_WIDTH = 240


def get(url: str) -> dict:  # pragma: no mutate block — process boundary
    """The JSON the server at `url` answers; a failure to reach it raises `OSError`."""
    with urllib.request.urlopen(url, timeout=_TIMEOUT) as response:
        return json.load(response)


def task_of(workflow_id: str) -> str | None:
    """The Board task a workflow id names (`task-lifecycle/TASK-10434/org/repo` or `TASK-9708` is `TASK-N`), else None."""
    found = _TASK.search(workflow_id)
    return found[0].upper() if found else None


def _iso(timestamp: str | None) -> str:
    """A server timestamp as ISO 8601 UTC to the second, or empty when it has none."""
    if not timestamp:
        return ""
    return datetime.fromisoformat(timestamp).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _message(failure: dict | None) -> str | None:
    """The first line of the deepest message of a failure and its causes, which is the one that names what went wrong."""
    message = None
    while failure:
        message = failure.get("message") or message
        failure = failure.get("cause")
    lines = (message or "").strip().splitlines()
    return lines[0][:_FAILURE_WIDTH] if lines else None


def _short(status: str) -> str:
    return status.removeprefix("WORKFLOW_EXECUTION_STATUS_")


def _status(execution: dict) -> RunStatus:
    return _STATUS.get(_short(execution["status"]), "failed")


class Poller:
    """Reads the server into `Dag` records, remembering what a closed run's history said."""

    def __init__(self, sink: RunsSink, fetch: Callable[[str], dict], url: str) -> None:
        self.sink, self.fetch, self.base = sink, fetch, url.rstrip("/")
        self.closed: dict[str, dict] = {}  # run id -> the failure details of a closed run, which never change

    def _list(self, query: str, limit: int) -> list[dict]:
        types = ",".join(f'"{name}"' for name in TYPES)
        params = urllib.parse.urlencode({"query": f"WorkflowType IN ({types}) AND {query}", "pageSize": limit})
        return self.fetch(f"{self.base}{_NAMESPACE}/workflows?{params}").get("executions") or []

    def _history(self, execution: dict) -> dict:
        """The activity a closed run ended on, its attempt and the failure; empty for a run that did not fail."""
        workflow_id, run_id = execution["execution"]["workflowId"], execution["execution"]["runId"]
        if run_id in self.closed:
            return self.closed[run_id]
        details: dict = {}
        if _status(execution) == "failed":
            params = urllib.parse.urlencode({"execution.runId": run_id, "maximumPageSize": _HISTORY_EVENTS})
            quoted = urllib.parse.quote(workflow_id, safe="")
            events = self.fetch(f"{self.base}{_NAMESPACE}/workflows/{quoted}/history-reverse?{params}")["history"]["events"]
            details = _failure_of(events)
        self.closed[run_id] = details
        return details

    def _active(self, execution: dict) -> dict:
        workflow_id, run_id = execution["execution"]["workflowId"], execution["execution"]["runId"]
        quoted = urllib.parse.quote(workflow_id, safe="")
        described = self.fetch(f"{self.base}{_NAMESPACE}/workflows/{quoted}?execution.runId={run_id}")
        entered = sorted(described.get("pendingActivities") or [], key=lambda a: a.get("lastStartedTime") or "")
        current = entered[-1] if entered else {}
        return {
            "runId": run_id,
            "status": "running",
            "raw": None,
            "startedAt": _iso(execution["startTime"]),
            "step": current.get("activityType", {}).get("name", ""),
            "stepStartedAt": _iso(current.get("lastStartedTime")),
            "steps": {a["activityType"]["name"]: "running" for a in entered},
            "task": task_of(workflow_id),
            "attempt": current.get("attempt"),
            "failure": _message(current.get("lastFailure")),
        }

    def _recent(self, execution: dict) -> dict:
        workflow_id, run_id = execution["execution"]["workflowId"], execution["execution"]["runId"]
        details = self._history(execution)
        quoted = urllib.parse.quote(workflow_id, safe="")
        return {
            "runId": run_id,
            "task": task_of(workflow_id),
            "url": f"{self.base}/namespaces/default/workflows/{quoted}/{run_id}",
            "status": _status(execution),
            "raw": _short(execution["status"]),
            "startedAt": _iso(execution["startTime"]),
            "finishedAt": _iso(execution.get("closeTime")),
            "params": {},
            "steps": {details["activity"]: "failed"} if details.get("activity") else {},
            "attempt": details.get("attempt"),
            "failure": details.get("failure"),
        }

    def listing(self, now: datetime) -> list[dict]:
        """One workflow per type with its running executions and its closed ones of the day before `now`."""
        since = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        window = f'CloseTime > "{since}"'
        running = self._list('ExecutionStatus="Running"', ACTIVE_LIMIT)
        failed = self._list(f'ExecutionStatus IN ("Failed","TimedOut") AND {window}', RECENT_LIMIT)
        closed = self._list(f'ExecutionStatus!="Running" AND {window}', RECENT_LIMIT)
        newest = {e["execution"]["runId"]: e for e in [*closed, *failed]}.values()
        dags = [self._workflow(name, [e for e in running if e["type"]["name"] == name], newest) for name in TYPES]
        self.closed = {run: seen for run, seen in self.closed.items() if run in {e["execution"]["runId"] for e in newest}}
        return dags

    def _workflow(self, name: str, running: list[dict], closed) -> dict:
        active = sorted((self._active(e) for e in running), key=lambda run: run["startedAt"])
        recent = sorted(
            (self._recent(e) for e in closed if e["type"]["name"] == name), key=lambda run: run["finishedAt"], reverse=True
        )
        latest = max(active, key=lambda run: run["startedAt"]) if active else recent[0] if recent else None
        return {
            "name": name,
            "status": "running" if active else latest["status"] if latest else "not_started",
            "raw": None,
            "runId": latest["runId"] if latest else "",
            "startedAt": latest["startedAt"] if latest else "",
            "finishedAt": "" if active or not latest else latest["finishedAt"],
            "steps": [],
            "schedule": [],
            "stats": None,
            "rerun": None,
            "active": active,
            "recent": recent,
        }

    def read(self) -> None:
        """List the server and hand the workflows to the page; when it cannot be read the last reading stays and the error shows."""
        try:
            self.sink.set_dags(self.listing(datetime.now(UTC)), None)
        except OSError as exc:
            self.sink.set_dags(None, str(exc))
        except (ValueError, KeyError, TypeError) as exc:  # an answer not in the shape `listing` reads
            self.sink.set_dags(None, f"unreadable response ({type(exc).__name__}: {exc})")


def _failure_of(events: list[dict]) -> dict:
    """The activity, attempt and failure a failed run's history (newest event first) ended on."""
    details: dict = {}
    for event in events:
        failure = event.get("workflowExecutionFailedEventAttributes", {}).get("failure")
        if failure:
            info = failure.get("activityFailureInfo") or {}
            details = {"failure": _message(failure), "activity": info.get("activityType", {}).get("name")}
            started = next((e for e in events if e["eventId"] == info.get("startedEventId")), {})
            attributes = started.get("activityTaskStartedEventAttributes", {})
            return details | {"attempt": attributes.get("attempt")}
    return details


def start(url: str) -> None:
    """No start capability: these workflows start from the Board's lifecycle, so a workflow has no Run now."""
    return


def follow(url: str, runs: RunsSink, log: EventLog) -> None:  # pragma: no mutate block — thread wiring
    """Show the workflows of the Temporal server at `url` on `runs`, read again every `POLL_INTERVAL` seconds."""
    poller = Poller(runs, get, url)

    def run() -> None:
        while True:
            poller.read()
            time.sleep(POLL_INTERVAL)

    threading.Thread(target=run, name="temporal-runs", daemon=True).start()
