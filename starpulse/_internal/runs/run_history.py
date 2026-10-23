"""Runs as observed History: one event stream per run in the event store (spec D8).

A run is the stream `("run", "<instance>/<run_id>")`. A pushed Step event (the CloudEvents ingest, over HTTP and gRPC)
and a run an Adapter re-reads from its source both append `StepStarted` and `StepFinished` Events; a run's own Events
name no `step`. A correction, such as a source now reporting `failed` for a step it reported `succeeded`, is a new Event
and the earlier one stays. `read` folds a stream into a `RunRecord`; the fold is the runs read model.

A lost Event is a gap, not an error: a step whose last Event is a start, in a run whose last Event is a finish, never
reported its end.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from starpulse._internal.store import EventStore, NewEvent, StaleVersion, StoredEvent

SUBJECT_KIND = "run"
#: Statuses after which a unit of a run has nothing left to report.
TERMINAL = frozenset({"succeeded", "failed", "aborted", "skipped"})
#: Appends tried before a stream that keeps moving is given up on.
ATTEMPTS = 3


@dataclass(frozen=True)
class RunRecord:
    """One run as its stream tells it."""

    workflow: str
    #: The run's last reported status; empty for a stream with no Events.
    status: str
    #: Each step's last reported status.
    steps: dict[str, str]
    #: The steps that started and never ended, once the run has.
    gaps: list[str]
    events: list[StoredEvent]


def _subject(instance: str, run_id: str) -> str:
    return f"{instance}/{run_id}"


def _type(status: str) -> str:
    return "StepFinished" if status in TERMINAL else "StepStarted"


def _fold(events: Sequence[StoredEvent]) -> RunRecord:
    workflow, status = "", ""
    steps: dict[str, str] = {}
    open_steps: set[str] = set()
    run_ended = False
    for event in events:
        workflow = event.payload["workflow"]
        step = event.payload.get("step")
        if step is None:
            status, run_ended = event.payload["status"], event.type == "StepFinished"
            continue
        steps[step] = event.payload["status"]
        if event.type == "StepStarted":
            open_steps.add(step)
        else:
            open_steps.discard(step)
    return RunRecord(workflow, status, steps, sorted(open_steps) if run_ended else [], list(events))


class RunHistory:
    """Appends the run Events a source reports to the event store and reads a run back."""

    def __init__(self, store: EventStore) -> None:
        self._store = store

    def read(self, instance: str, run_id: str) -> RunRecord:
        return _fold(self._store.read(SUBJECT_KIND, _subject(instance, run_id)))

    def ingest(self, event_id: str, fields: Mapping[str, Any]) -> None:
        """Append the `runs:events` entry `fields` (`run_events.entry`) a producer posted as CloudEvent `event_id`; an
        event id already on the stream appends nothing, so the sender may post a batch again."""
        instance, run_id = fields["instance"], fields["run_id"]
        payload = {key: fields[key] for key in ("workflow", "status", "step", "depends", "time") if key in fields}
        event = NewEvent(fields["event"], payload, actor=instance, writer="ingest", causation_id=event_id)
        self._append(instance, run_id, lambda seen: [] if _has(seen, event_id) else [event], at=fields["time"])

    def observe(self, instance: str, dags: Sequence[Mapping[str, Any]]) -> None:
        """Append what `dags`, the workflows an Adapter just read from its source, say beyond what each run's stream
        already holds: a unit whose status differs from its last Event's gets a new one."""
        for dag in dags:
            run_id = dag.get("runId")
            if run_id:
                self._append(instance, run_id, lambda seen, dag=dag: _differences(instance, dag, seen))

    def _append(self, instance: str, run_id: str, events: Any, *, at: float | None = None) -> None:
        subject = _subject(instance, run_id)
        for _ in range(ATTEMPTS):
            seen = self._store.read(SUBJECT_KIND, subject)
            new = events(seen)
            if not new:
                return
            try:
                self._store.append(SUBJECT_KIND, subject, seen[-1].version if seen else 0, new, at=at)
            except StaleVersion:
                continue
            return
        raise StaleVersion(f"run {subject} kept moving; the Events were not appended")


def _has(seen: Sequence[StoredEvent], event_id: str) -> bool:
    return any(event.causation_id == event_id for event in seen)


def _differences(instance: str, dag: Mapping[str, Any], seen: Sequence[StoredEvent]) -> list[NewEvent]:
    """The Events that bring the stream `seen` to the run `dag` reports."""
    record = _fold(seen)
    units: list[tuple[str | None, str, list[str]]] = [(None, dag["status"], [])]
    units += [(step["name"], step["status"], step.get("depends") or []) for step in dag.get("steps", [])]
    new = []
    for step, status, depends in units:
        recorded = record.status if step is None else record.steps.get(step)
        if status == "not_started" or status == recorded:
            continue
        payload = {"workflow": dag["name"], "status": status}
        if step is not None:
            payload["step"] = step
            if depends:
                payload["depends"] = depends
        new.append(NewEvent(_type(status), payload, actor=instance, writer="adapter"))
    return new
