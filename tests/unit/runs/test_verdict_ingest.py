"""A verdict posted to the CloudEvents ingest lands on `task:verdicts`; one missing a field is refused."""

import json
from pathlib import Path

import pytest
from starpulse.event_log import verdict_events
from starpulse.event_log.event_log import EventLog, Tail
from starpulse.runs.adapters.inbound.cloudevents import SINGLE, CloudEventsIngest
from starpulse.runs.adapters.inbound.ingest import tokens as ingest_tokens
from starpulse.runs.model.config import Producer

PRODUCER = Producer("qa", "QA_TOKEN", machines=(), actors=())
GOOD = {"lens": "security", "round": 1, "outcome": "PASS", "reason": "no findings"}


def _verdict(id: str = "v1", **data: object) -> dict:
    return {
        "specversion": "1.0",
        "id": id,
        "source": "qa",
        "type": verdict_events.EVENT,
        "subject": "TASK-1",
        "time": "2026-10-22T12:00:00+00:00",
        "data": {**GOOD, **data},
    }


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


@pytest.fixture
def ingest(log: EventLog) -> CloudEventsIngest:
    return CloudEventsIngest({"qa": PRODUCER}, ingest_tokens([PRODUCER], {"QA_TOKEN": "s"}), log, {})


def test_a_verdict_is_appended_to_the_verdict_stream_with_its_task_and_producer(
    log: EventLog, ingest: CloudEventsIngest
) -> None:
    assert ingest("Bearer s", SINGLE, json.dumps(_verdict()).encode()) == (201, {"accepted": True})

    (entry,) = Tail.replay(log, "reader", streams=[verdict_events.STREAM]).poll()

    assert entry.fields == {
        "task": "TASK-1",
        "lens": "security",
        "round": 1,
        "outcome": "PASS",
        "reason": "no findings",
        "time": 1792670400.0,
        "source": "qa",
    }


def _without(key: str) -> dict:
    event = _verdict()
    del event["data"][key]
    return event


@pytest.mark.parametrize(
    "event",
    [
        _without("lens"),
        _without("round"),
        _without("outcome"),
        _verdict(lens=""),
        _verdict(round=0),
        _verdict(round="1"),
        _verdict(outcome="pass"),
        _verdict(outcome="MAYBE"),
        {**_verdict(), "subject": None},
        {k: v for k, v in _verdict().items() if k != "data"},
    ],
    ids=lambda event: str(event.get("data") or event),
)
def test_a_verdict_missing_lens_round_or_outcome_is_refused_and_appends_nothing(
    log: EventLog, ingest: CloudEventsIngest, event: dict
) -> None:
    status, body = ingest("Bearer s", SINGLE, json.dumps(event).encode())

    assert status == 400, body
    assert Tail.replay(log, "reader", streams=[verdict_events.STREAM]).poll() == []
