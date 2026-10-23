"""Runs as observed History: a run is one stream, a re-read of a source appends, and a lost Event shows as a gap."""

from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.runs import run_events
from starpulse._internal.runs.run_history import RunHistory
from starpulse._internal.store import EventStore


@pytest.fixture
def history(tmp_path: Path) -> RunHistory:
    return RunHistory(EventStore(EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").engine))


def _pushed(event: str, status: str, *, step: str | None = None, at: float = 100.0, run_id: str = "r1") -> dict:
    return run_events.entry(event, "nightly", run_id, status, now=at, step=step, instance="cron")


def _dag(status: str, steps: dict[str, str], run_id: str = "r1") -> dict[str, Any]:
    return {
        "name": "nightly",
        "status": status,
        "runId": run_id,
        "startedAt": "2026-10-22T10:00:00Z",
        "finishedAt": "",
        "steps": [{"name": name, "depends": [], "status": s, "kind": None} for name, s in steps.items()],
    }


def test_the_events_of_one_run_land_on_one_stream_in_order(history: RunHistory) -> None:
    history.ingest("e1", _pushed("StepStarted", "running"))
    history.ingest("e2", _pushed("StepStarted", "running", step="load"))
    history.ingest("e3", _pushed("StepFinished", "succeeded", step="load"))
    history.ingest("e4", _pushed("StepFinished", "succeeded"))
    history.ingest("e5", _pushed("StepStarted", "running", run_id="r2"))

    record = history.read("cron", "r1")

    assert [(e.version, e.type) for e in record.events] == [
        (1, "StepStarted"),
        (2, "StepStarted"),
        (3, "StepFinished"),
        (4, "StepFinished"),
    ]
    assert (record.workflow, record.status, record.steps) == ("nightly", "succeeded", {"load": "succeeded"})
    assert history.read("cron", "r2").status == "running"


def test_an_event_posted_twice_is_on_the_stream_once(history: RunHistory) -> None:
    history.ingest("e1", _pushed("StepStarted", "running"))
    history.ingest("e1", _pushed("StepStarted", "running"))

    assert len(history.read("cron", "r1").events) == 1


def test_a_reread_that_finds_nothing_new_appends_nothing(history: RunHistory) -> None:
    dag = _dag("running", {"load": "running", "ship": "not_started"})
    history.observe("dagu", [dag])
    history.observe("dagu", [dag])

    record = history.read("dagu", "r1")

    assert [e.type for e in record.events] == ["StepStarted", "StepStarted"]
    assert (record.status, record.steps) == ("running", {"load": "running"})


def test_a_correction_is_a_new_event_and_the_earlier_one_stays(history: RunHistory) -> None:
    history.observe("dagu", [_dag("succeeded", {"load": "succeeded"})])
    history.observe("dagu", [_dag("failed", {"load": "failed"})])

    record = history.read("dagu", "r1")

    assert [(e.type, e.payload["status"]) for e in record.events if "step" not in e.payload] == [
        ("StepFinished", "succeeded"),
        ("StepFinished", "failed"),
    ]
    assert (record.status, record.steps) == ("failed", {"load": "failed"})


def test_a_step_that_never_ended_in_a_finished_run_is_a_gap(history: RunHistory) -> None:
    history.ingest("e1", _pushed("StepStarted", "running"))
    history.ingest("e2", _pushed("StepStarted", "running", step="load"))
    history.ingest("e3", _pushed("StepStarted", "running", step="ship"))
    history.ingest("e4", _pushed("StepFinished", "succeeded", step="ship"))
    assert history.read("cron", "r1").gaps == []  # the run is still going

    history.ingest("e5", _pushed("StepFinished", "succeeded"))  # the end of `load` was lost

    assert history.read("cron", "r1").gaps == ["load"]
