"""Every kind of event written to the log has a record schema a consumer can read it by."""

from __future__ import annotations

import ast
from pathlib import Path

import jsonschema
import pytest

import starpulse
from starpulse import contracts
from starpulse._internal.eventlog import events, lane_events
from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.runs import run_events

STREAMS = contracts.EVENT_STREAMS


def _declared_streams() -> set[str]:
    """The stream names the package's producers declare: each module-level `STREAM = "..."` under `_internal`."""
    found: set[str] = set()
    for path in (Path(starpulse.__file__).parent / "_internal").rglob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "STREAM" for target in node.targets)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                found.add(node.value.value)
    return found


def test_every_stream_a_producer_declares_has_a_contract_schema() -> None:
    declared = _declared_streams()

    assert declared == {events.STREAM, run_events.STREAM, lane_events.STREAM}, "a producer declared a new stream"
    assert sorted(declared - set(STREAMS)) == [], "declare the stream's record in starpulse.contracts.EVENT_STREAMS"
    assert sorted(set(STREAMS.values()) - set(contracts.CONTRACTS)) == []


def test_an_entry_each_producer_writes_validates_against_its_streams_schema(tmp_path: Path) -> None:
    log = EventLog(f"sqlite:///{tmp_path / 'log.sqlite'}")
    task = contracts.BoardTask(
        id="T-1", title="t", team="core", lane="in_progress", milestone="m-1", labels=("a",), assignee="ana"
    )
    events.publish("in-progress", "WORKTREE_READY", actor="agent", task="T-1", now=5.0, log=log)
    lane_events.publish(log, "T-1@in_progress@5.0", task, 5.0)
    log.append(run_events.STREAM, run_events.entry("start", "nightly", "r1", "running", now=6.0))
    log.append(
        run_events.STREAM,
        run_events.entry("end", "nightly", "r1", "succeeded", now=7.0, step="load", depends=["fetch"], instance="ana"),
    )

    entries = Tail(log, "reader", streams=sorted(_declared_streams())).poll()

    assert len(entries) == 4
    assert [e.stream for e in entries if e.stream not in STREAMS] == []
    for entry in entries:
        name = STREAMS[entry.stream]
        contracts.CONTRACTS[name].model_validate(entry.fields)
        jsonschema.Draft202012Validator(contracts.SCHEMAS[name]).validate(entry.fields)


@pytest.mark.parametrize(
    "bad",
    [
        {"time": 1.0, "phase": "pause", "workflow": "w", "run_id": "r", "status": "running"},
        {"time": 1.0, "phase": "start", "workflow": "w", "run_id": "r", "status": "weird"},
        {"time": 1.0, "phase": "start", "workflow": "", "run_id": "r", "status": "running"},
        {"time": 1.0, "phase": "start", "workflow": "w", "run_id": "r", "status": "running", "title": "x"},
        {"time": 1.0, "phase": "start", "workflow": "w", "run_id": "r", "status": "running", "depends": ["a"]},
    ],
)
def test_a_run_event_the_ingest_would_refuse_is_not_a_run_event_record(bad: dict) -> None:
    run_event = contracts.CONTRACTS["run-events"]

    with pytest.raises(ValueError):
        run_event.model_validate(bad)
