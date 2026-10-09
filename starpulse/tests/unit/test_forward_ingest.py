"""`POST /api/forward` on a hub: a source's batch of forwarded events, taken once however often it is sent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.runs import run_events
from starpulse._internal.runs.ingest import ForwardIngest
from starpulse._internal.eventlog import events
from starpulse._internal.eventlog.event_log import EventLog, Tail

TOKENS = {"ana": "ana-secret", "bo": "bo-secret"}
MOVED = {
    "event_id": "e1",
    "stream": events.STREAM,
    "fields": {"machine": "board", "event": "MOVED", "task": "T-1", "time": 1.0},
}
RAN = {
    "event_id": "e2",
    "stream": run_events.STREAM,
    "fields": {"time": 2.0, "phase": "end", "workflow": "nightly", "run_id": "r1", "status": "succeeded"},
}


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'hub.sqlite'}")


def batch(*sent: dict[str, Any], opt_in: bool = False) -> bytes:
    return json.dumps({"opt_in": opt_in, "events": list(sent)}).encode()


def stored(log: EventLog) -> list[tuple[str, str, dict]]:
    return [
        (e.stream, e.event_id, e.fields)
        for e in Tail(log, events.STREAM, streams=(events.STREAM, run_events.STREAM)).poll()
    ]


def test_a_batch_under_a_sources_token_is_appended_under_that_source(log: EventLog) -> None:
    status, answer = ForwardIngest(TOKENS, log)("Bearer ana-secret", batch(MOVED, RAN))

    assert (status, answer) == (200, {"accepted": 2, "rejected": 0})
    assert stored(log) == [
        (events.STREAM, "ana/e1", MOVED["fields"] | {"source": "ana"}),
        (run_events.STREAM, "ana/e2", RAN["fields"] | {"instance": "ana", "source": "ana"}),
    ]


@pytest.mark.parametrize(
    "authorization", [None, "", "Bearer", "Bearer wrong", "Bearer ana-secret-", "Basic ana-secret"]
)
def test_a_missing_or_wrong_token_answers_401_and_writes_nothing(log: EventLog, authorization: str | None) -> None:
    status, _ = ForwardIngest(TOKENS, log)(authorization, batch(MOVED))

    assert status == 401
    assert stored(log) == []


def test_a_revoked_source_is_a_wrong_token(log: EventLog) -> None:
    revoked = {"bo": "bo-secret"}

    status, _ = ForwardIngest(revoked, log)("Bearer ana-secret", batch(MOVED))

    assert status == 401
    assert stored(log) == []


def test_the_same_batch_sent_again_adds_nothing(log: EventLog) -> None:
    ingest = ForwardIngest(TOKENS, log)
    ingest("Bearer ana-secret", batch(MOVED, RAN))
    before = stored(log)

    status, answer = ingest("Bearer ana-secret", batch(MOVED, RAN))

    assert (status, answer) == (200, {"accepted": 2, "rejected": 0})
    assert stored(log) == before


def test_two_sources_may_forward_events_that_share_an_event_id(log: EventLog) -> None:
    ingest = ForwardIngest(TOKENS, log)
    ingest("Bearer ana-secret", batch(MOVED))
    ingest("Bearer bo-secret", batch(MOVED))

    assert [event_id for _, event_id, _ in stored(log)] == ["ana/e1", "bo/e1"]


def test_a_hub_that_takes_aggregates_only_refuses_an_opt_in_and_writes_nothing(log: EventLog) -> None:
    status, answer = ForwardIngest(TOKENS, log, aggregates_only=True)("Bearer ana-secret", batch(MOVED, opt_in=True))

    assert status == 403
    assert "aggregates only" in answer["error"]
    assert stored(log) == []


def test_a_hub_that_takes_aggregates_only_still_takes_an_opted_out_batch(log: EventLog) -> None:
    status, _ = ForwardIngest(TOKENS, log, aggregates_only=True)("Bearer ana-secret", batch(MOVED))

    assert status == 200
    assert len(stored(log)) == 1


def test_a_name_is_stored_only_from_a_batch_that_opted_in(log: EventLog) -> None:
    named = {"event_id": "n1", "stream": events.STREAM, "fields": MOVED["fields"] | {"actor": "ana", "assignee": "ana"}}
    ingest = ForwardIngest(TOKENS, log)
    ingest("Bearer ana-secret", batch(named, opt_in=False))
    ingest("Bearer bo-secret", batch(named, opt_in=True))

    anonymous, kept = (fields for _, _, fields in stored(log))
    assert "actor" not in anonymous and "assignee" not in anonymous
    assert (kept["actor"], kept["assignee"]) == ("ana", "ana")


@pytest.mark.parametrize(
    "bad",
    [
        {"event_id": "", "stream": events.STREAM, "fields": MOVED["fields"]},
        {"stream": events.STREAM, "fields": MOVED["fields"]},
        {"event_id": "x", "stream": "claude:events", "fields": {}},
        {"event_id": "x", "stream": events.STREAM, "fields": "nope"},
        {"event_id": "x", "stream": events.STREAM, "fields": {"machine": "board", "event": "MOVED", "time": 1.0}},
        {"event_id": "x", "stream": events.STREAM, "fields": MOVED["fields"] | {"run": "r1"}},
        {"event_id": "x", "stream": events.STREAM, "fields": {k: v for k, v in MOVED["fields"].items() if k != "time"}},
        {"event_id": "x", "stream": run_events.STREAM, "fields": RAN["fields"] | {"status": "weird"}},
        "not an object",
    ],
)
def test_an_invalid_event_is_rejected_and_counted_while_the_valid_ones_are_taken(log: EventLog, bad: Any) -> None:
    status, answer = ForwardIngest(TOKENS, log)("Bearer ana-secret", batch(MOVED, bad, RAN))

    assert (status, answer) == (200, {"accepted": 2, "rejected": 1})
    assert [event_id for _, event_id, _ in stored(log)] == ["ana/e1", "ana/e2"]


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"[]", b"{}", b'{"events": "x"}', b'{"events": [], "opt_in": "yes"}', b'{"events": []}'],
)
def test_a_body_that_is_not_a_batch_answers_400(log: EventLog, raw: bytes) -> None:
    status, _ = ForwardIngest(TOKENS, log)("Bearer ana-secret", raw)

    assert status == 400


def test_a_batch_over_the_limit_answers_400_and_writes_nothing(log: EventLog) -> None:
    many = [{**MOVED, "event_id": f"e{n}"} for n in range(201)]

    status, _ = ForwardIngest(TOKENS, log)("Bearer ana-secret", batch(*many))

    assert status == 400
    assert stored(log) == []


def test_a_log_that_refuses_an_event_answers_503_so_the_batch_is_sent_again() -> None:
    status, _ = ForwardIngest(TOKENS, EventLog("sqlite:////nonexistent-dir/hub.sqlite"))(
        "Bearer ana-secret", batch(MOVED)
    )

    assert status == 503
