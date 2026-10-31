"""The Temporal adapter: each Workflow Type as a workflow, its latest Workflow Execution as the run and that run's Activities as its steps.

`url` is the frontend's address, `host:port`, with an optional `/namespace` (`default` without one). `follow` lists the
open executions and those closed since the last good listing every `INTERVAL` seconds, and reads a run's history only
when its length changed. The follow set is bounded: it holds the latest execution of at most `FOLLOW_LIMIT` Workflow
Types, the most recently started kept, and an execution whose history read fails `FAILURE_LIMIT` times in a row is
dropped from it and shown without steps. A Temporal that cannot be listed keeps the last reading and shows the error, so
an outage grows nothing. `start` is None: a Workflow Type has no Run now. The event log is not read.

The client is `temporalio`, the `starpulse[temporal]` extra, imported only when `follow` runs.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

from starpulse.contracts.adapters import RunsSink, RunStatus

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog

#: The worker that runs this adapter (`starpulse.runs.opt_in`): `serve` supervises it as a child.
WORKER = "temporal"

#: Seconds between two listings.
INTERVAL = 30.0
#: The most Workflow Types the follow set holds.
FOLLOW_LIMIT = 64
#: History reads of one execution that fail in a row before it is dropped from the follow set.
FAILURE_LIMIT = 3
#: The most executions one listing reads, newest first.
LISTING_LIMIT = 1000
#: How far back the first listing reads closed executions.
LOOKBACK = timedelta(days=1)
#: How far before the last good listing the next one starts, so an execution closing during a listing is not missed.
OVERLAP = timedelta(minutes=1)
#: Seconds one call to Temporal may take.
RPC_TIMEOUT = timedelta(seconds=10)

_NAMESPACE = "default"

#: A Workflow Execution's status (`WorkflowExecutionStatus` name) -> the run's.
_RUN_STATUS: dict[str, RunStatus] = {
    "RUNNING": "running",
    "COMPLETED": "succeeded",
    "CONTINUED_AS_NEW": "succeeded",
    "FAILED": "failed",
    "TIMED_OUT": "failed",
    "TERMINATED": "aborted",
    "CANCELED": "aborted",
}

#: An Activity history event (`EventType` name less `EVENT_TYPE_ACTIVITY_TASK_`) -> its step's status and raw status.
_ACTIVITY_STATUS: dict[str, tuple[RunStatus, str | None]] = {
    "SCHEDULED": ("queued", None),
    "STARTED": ("running", None),
    "COMPLETED": ("succeeded", None),
    "FAILED": ("failed", None),
    "TIMED_OUT": ("failed", "timed_out"),
    "CANCEL_REQUESTED": ("running", "cancel_requested"),
    "CANCELED": ("aborted", "canceled"),
}
_ACTIVITY_EVENT = "EVENT_TYPE_ACTIVITY_TASK_"


class Execution(NamedTuple):
    """One Workflow Execution as a listing reports it; `status` is its `WorkflowExecutionStatus` name."""

    workflow_type: str
    workflow_id: str
    run_id: str
    status: str
    started: datetime
    closed: datetime | None
    history_length: int


class Activity(NamedTuple):
    """One Activity of a run at its latest state."""

    name: str
    status: RunStatus
    raw: str | None


class Source(Protocol):
    """Where the follower reads Temporal; a call that cannot reach it raises `OSError`."""

    def executions(self, since: datetime) -> Iterable[Execution]: ...

    def activities(self, run: Execution) -> list[Activity]: ...


def target(url: str) -> tuple[str, str]:
    """The frontend address and namespace `url` names."""
    address, _, namespace = url.strip().partition("/")
    return address, namespace or _NAMESPACE


class _Activities:
    """A history's Activities folded one event at a time, so a long history is never held whole."""

    def __init__(self) -> None:
        from temporalio.api.enums.v1 import EventType

        self.kind = EventType.Name
        self.names: dict[int, str] = {}
        self.latest: dict[str, Activity] = {}

    def take(self, event: Any) -> None:
        state = self.kind(event.event_type).removeprefix(_ACTIVITY_EVENT)
        if state not in _ACTIVITY_STATUS:
            return
        if state == "SCHEDULED":
            name = self.names[event.event_id] = event.activity_task_scheduled_event_attributes.activity_type.name
        else:
            attributes = getattr(event, f"activity_task_{state.lower()}_event_attributes")
            name = self.names.get(attributes.scheduled_event_id)
        if name is not None:
            self.latest[name] = Activity(name, *_ACTIVITY_STATUS[state])


def activities_of(events: Iterable[Any]) -> list[Activity]:
    """A history's Activities in the order first scheduled, one per Activity Type at its latest event's state."""
    folded = _Activities()
    for event in events:
        folded.take(event)
    return list(folded.latest.values())


def _iso(moment: datetime | None) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if moment else ""


def _dag(run: Execution, activities: list[Activity]) -> dict:
    return {
        "name": run.workflow_type,
        "status": _RUN_STATUS.get(run.status, "failed"),
        "raw": run.status.lower(),
        "runId": run.run_id,
        "startedAt": _iso(run.started),
        "finishedAt": _iso(run.closed),
        "steps": [
            {
                "name": activity.name,
                "depends": [],
                "status": activity.status,
                "raw": activity.raw,
                "kind": None,
                "precondition": None,
                "lock": None,
                "last": [],
            }
            for activity in activities
        ],
        "schedule": [],
        "stats": None,
        "rerun": None,
    }


class _Followed:
    """One Workflow Type's latest execution, the history length its Activities were read at, and its failed reads."""

    def __init__(self, run: Execution) -> None:
        self.run = run
        self.read_at: int | None = None
        self.activities: list[Activity] = []
        self.failures = 0


class Follower:
    """The follow set as last read, handed to the page whole after each listing."""

    def __init__(
        self,
        sink: RunsSink,
        source: Source,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        limit: int = FOLLOW_LIMIT,
        failures: int = FAILURE_LIMIT,
    ) -> None:
        self.sink, self.source, self.clock = sink, source, clock
        self.limit, self.failure_limit = limit, failures
        self.followed: dict[str, _Followed] = {}
        self.since: datetime | None = None

    def read(self) -> None:
        """List what changed since the last good listing, read the histories that grew, and show the follow set."""
        began = self.clock()
        try:
            for run in self.source.executions(self.since or began - LOOKBACK):
                self._take(run)
        except OSError as exc:
            self.sink.set_dags(None, str(exc))
            return
        self.since = began - OVERLAP
        kept = sorted(self.followed.values(), key=lambda followed: followed.run.started, reverse=True)[: self.limit]
        self.followed = {followed.run.workflow_type: followed for followed in kept}
        for followed in kept:
            self._read_history(followed)
        self.sink.set_dags([_dag(followed.run, followed.activities) for followed in kept], None)

    def _take(self, run: Execution) -> None:
        followed = self.followed.get(run.workflow_type)
        if followed is None or followed.run.run_id != run.run_id and run.started > followed.run.started:
            self.followed[run.workflow_type] = _Followed(run)
        elif followed.run.run_id == run.run_id:
            followed.run = run

    def _read_history(self, followed: _Followed) -> None:
        if followed.failures >= self.failure_limit or followed.read_at == followed.run.history_length:
            return
        try:
            followed.activities = self.source.activities(followed.run)
        except OSError:
            followed.failures += 1
            if followed.failures >= self.failure_limit:
                followed.activities = []
            return
        followed.failures, followed.read_at = 0, followed.run.history_length


class Temporal:  # pragma: no mutate block — process boundary
    """A `Source` over a Temporal frontend, on an event loop of its own; a failed call drops the client to reconnect."""

    def __init__(self, url: str) -> None:
        self.address, self.namespace = target(url)
        self.loop = asyncio.new_event_loop()
        self.client: Any = None

    def _call(self, call: Callable[[Any], Any]) -> Any:
        from temporalio.service import RPCError

        async def run() -> Any:
            if self.client is None:
                from temporalio.client import Client

                self.client = await Client.connect(self.address, namespace=self.namespace)
            return await call(self.client)

        try:
            return self.loop.run_until_complete(run())
        except (RPCError, RuntimeError, asyncio.TimeoutError) as exc:
            self.client = None
            raise OSError(f"temporal {self.address}: {exc}") from exc

    def executions(self, since: datetime) -> Iterator[Execution]:
        query = f"ExecutionStatus = 'Running' OR CloseTime > '{_iso(since)}'"

        async def listing(client: Any) -> list[Execution]:
            listed = client.list_workflows(query, limit=LISTING_LIMIT, rpc_timeout=RPC_TIMEOUT)
            return [
                Execution(
                    run.workflow_type,
                    run.id,
                    run.run_id,
                    run.status.name if run.status else "RUNNING",
                    run.start_time,
                    run.close_time,
                    run.history_length,
                )
                async for run in listed
            ]

        return iter(self._call(listing))

    def activities(self, run: Execution) -> list[Activity]:
        async def history(client: Any) -> list[Activity]:
            handle = client.get_workflow_handle(run.workflow_id, run_id=run.run_id)
            folded = _Activities()
            async for event in handle.fetch_history_events(rpc_timeout=RPC_TIMEOUT):
                folded.take(event)
            return list(folded.latest.values())

        return self._call(history)


def start(url: str) -> None:
    """No start capability: a Workflow Type has no Run now."""
    return


def follow(url: str, runs: RunsSink, log: EventLog) -> None:  # pragma: no mutate block — thread wiring
    """Show the Workflow Types of the Temporal `url` names on `runs`, re-listed every `INTERVAL` seconds."""

    def run() -> None:
        follower = Follower(runs, Temporal(url))
        while True:
            follower.read()
            time.sleep(INTERVAL)

    threading.Thread(target=run, name="temporal-runs", daemon=True).start()
