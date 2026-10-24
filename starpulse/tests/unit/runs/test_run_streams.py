"""A run is an observed event stream: every entry path appends to one stream per run, and a correction appends."""

import json
import threading
import time
from pathlib import Path

import pytest

from starpulse._internal.config.config import Producer
from starpulse._internal.runs import run_events
from starpulse._internal.runs.cloudevents import SINGLE, CloudEventsIngest
from starpulse._internal.runs.ingest import tokens as ingest_tokens
from starpulse._internal.runs.run_streams import RunStreams, record_run_streams
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.store import EventStore

PRODUCER = Producer("flow", "FLOW_TOKEN", machines=(), actors=())


def _cloudevent(id: str, type: str, step: str | None = None, status: str = "running", **data: object) -> dict:
    return {
        "specversion": "1.0",
        "id": id,
        "source": "flow",
        "type": type,
        "subject": "r1",
        "time": "2026-10-22T12:00:00+00:00",
        "data": {"workflow": "build", "status": status, **({"step": step} if step else {}), **data},
    }


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


@pytest.fixture
def streams(log: EventLog) -> RunStreams:
    return RunStreams(EventStore(log.engine))


@pytest.fixture
def ingest(log: EventLog) -> CloudEventsIngest:
    return CloudEventsIngest({"flow": PRODUCER}, ingest_tokens([PRODUCER], {"FLOW_TOKEN": "s"}), log, {})


def _drain(log: EventLog, streams: RunStreams) -> None:
    stop = threading.Event()
    reader = threading.Thread(target=record_run_streams, args=(streams, log, stop), kwargs={"interval": 0.01})
    reader.start()
    time.sleep(0.3)
    stop.set()
    reader.join()


def test_a_run_pushed_over_http_and_over_grpc_lands_as_one_stream(
    log: EventLog, streams: RunStreams, ingest: CloudEventsIngest
) -> None:
    assert ingest("Bearer s", SINGLE, json.dumps(_cloudevent("e1", "StepStarted", "compile")).encode())[0] == 201
    assert ingest.write("flow", [_cloudevent("e2", "StepFinished", "compile", "succeeded")])[0] == 201  # the gRPC call

    _drain(log, streams)

    assert [e.type for e in streams.read("build", "r1")] == ["StepStarted", "StepFinished"]


def test_a_correction_appends_and_the_earlier_event_stays(
    log: EventLog, streams: RunStreams, ingest: CloudEventsIngest
) -> None:
    ingest.write("flow", [_cloudevent("e1", "StepFinished", "compile", "failed")])
    ingest.write("flow", [_cloudevent("e2", "StepFinished", "compile", "succeeded")])

    _drain(log, streams)
    _drain(log, streams)  # a replay of the same entries adds nothing

    assert [e.payload["status"] for e in streams.read("build", "r1")] == ["failed", "succeeded"]


def test_an_adapter_entry_lands_in_the_same_stream(log: EventLog, streams: RunStreams) -> None:
    log._append(run_events.STREAM, run_events.entry("StepStarted", "build", "r1", "running", now=1.0, step="lint"))

    _drain(log, streams)

    assert [e.payload["step"] for e in streams.read("build", "r1")] == ["lint"]


def test_a_phase_only_entry_from_before_the_event_field_is_skipped(streams: RunStreams) -> None:
    legacy = {"phase": "compile", "workflow": "build", "run_id": "r1", "status": "running", "time": 1.0}

    assert streams.record("legacy-1", legacy) is False
    assert streams.read("build", "r1") == []


def test_a_lost_step_end_shows_as_a_step_with_no_finish(
    log: EventLog, streams: RunStreams, ingest: CloudEventsIngest
) -> None:
    ingest.write("flow", [_cloudevent("e1", "StepStarted", "compile"), _cloudevent("e2", "StepStarted", "test")])
    ingest.write("flow", [_cloudevent("e3", "StepFinished", "compile", "succeeded")])

    _drain(log, streams)

    assert streams.unfinished("build", "r1") == ["test"]
