"""The HTTP runs ingest: who may push a run event, and what reaches the event log."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from starpulse import ingest, run_events
from starpulse.settings.config import RunsInstance
from starpulse.store.event_log import EventLog, Tail

NOW = 1_700_000_000.0
TOKENS = {"cron": "cron-secret", "rundeck": "rundeck-secret"}


@pytest.fixture
def log(tmp_path: Path) -> EventLog:
    return EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")


@pytest.fixture
def push(log: EventLog) -> ingest.Ingest:
    return ingest.Ingest(TOKENS, log, clock=lambda: NOW)


def appended(log: EventLog) -> list[dict[str, Any]]:
    return [entry.fields for entry in Tail(log, run_events.STREAM).poll()]


def body(**fields: Any) -> bytes:
    event = {"phase": "start", "workflow": "cron/nightly", "run_id": "r1", "status": "running"} | fields
    return json.dumps({k: v for k, v in event.items() if v is not None}).encode()


def bearer(instance: str) -> str:
    return f"Bearer {TOKENS[instance]}"


def test_a_valid_event_with_its_instances_token_is_appended_as_that_instances_entry(
    push: ingest.Ingest, log: EventLog
) -> None:
    status, answer = push(bearer("cron"), body())

    assert (status, answer) == (201, {"accepted": True})
    assert appended(log) == [
        {
            "time": NOW,
            "phase": "start",
            "workflow": "nightly",
            "run_id": "r1",
            "status": "running",
            "instance": "cron",
        }
    ]


def test_a_step_event_carries_its_time_step_and_dependencies(push: ingest.Ingest, log: EventLog) -> None:
    status, _ = push(
        bearer("cron"), body(phase="end", status="succeeded", time=12.5, step="load", depends=["fetch", "clean"])
    )

    assert status == 201
    assert appended(log) == [
        {
            "time": 12.5,
            "phase": "end",
            "workflow": "nightly",
            "run_id": "r1",
            "status": "succeeded",
            "instance": "cron",
            "step": "load",
            "depends": ["fetch", "clean"],
        }
    ]


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Bearer", "Bearer ", "Bearer wrong", "Basic cron-secret", "cron-secret", "bearer cron-secret "],
)
def test_a_missing_or_wrong_token_answers_401_and_writes_nothing(
    push: ingest.Ingest, log: EventLog, authorization: str | None
) -> None:
    status, answer = push(authorization, body())

    assert status == 401
    assert "error" in answer
    assert appended(log) == []


def test_a_bad_token_is_refused_before_the_body_is_read(push: ingest.Ingest) -> None:
    assert push("Bearer wrong", b"not json")[0] == 401


def test_a_token_for_one_instance_cannot_push_another_instances_workflow(push: ingest.Ingest, log: EventLog) -> None:
    status, answer = push(bearer("cron"), body(workflow="rundeck/nightly"))

    assert status == 403
    assert answer == {"error": "this token may push only cron/<workflow>, not rundeck/nightly"}
    assert appended(log) == []


def test_each_instances_token_pushes_its_own_workflows(push: ingest.Ingest, log: EventLog) -> None:
    push(bearer("cron"), body())
    push(bearer("rundeck"), body(workflow="rundeck/nightly"))

    assert [(e["instance"], e["workflow"]) for e in appended(log)] == [("cron", "nightly"), ("rundeck", "nightly")]


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        body(workflow="nightly"),
        body(workflow="cron/"),
        body(phase="pause"),
        body(status="exploded"),
        body(run_id=""),
        body(run_id=7),
        body(time="soon"),
        body(time=True),
        body(depends=["a"]),
        body(step="load", depends="fetch"),
        body(step="load", depends=[1]),
        body(step=3),
    ],
)
def test_an_event_the_contract_does_not_allow_answers_400_and_writes_nothing(
    push: ingest.Ingest, log: EventLog, raw: bytes
) -> None:
    status, answer = push(bearer("cron"), raw)

    assert status == 400
    assert "error" in answer
    assert appended(log) == []


def test_a_log_that_refuses_the_entry_answers_503() -> None:
    class Down(EventLog):
        def append(self, *_args: Any, **_kwargs: Any) -> None:
            return None

    status, answer = ingest.Ingest(TOKENS, Down("sqlite://"), clock=lambda: NOW)(bearer("cron"), body())

    assert status == 503
    assert "error" in answer


def _instance(name: str, token_env: str | None) -> RunsInstance:
    return RunsInstance(name, "dagu", "http://x.test", token_env=token_env)


def test_tokens_are_read_from_the_environment_for_each_instance_that_names_one() -> None:
    instances = [_instance("cron", "CRON_TOKEN"), _instance("dagu", None)]

    assert ingest.tokens(instances, {"CRON_TOKEN": "s3", "OTHER": "x"}) == {"cron": "s3"}


@pytest.mark.parametrize("environ", [{}, {"CRON_TOKEN": ""}])
def test_an_instance_whose_token_variable_is_unset_or_empty_is_an_error(environ: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="runs instance cron: CRON_TOKEN is not set"):
        ingest.tokens([_instance("cron", "CRON_TOKEN")], environ)


def test_two_instances_holding_the_same_token_is_an_error() -> None:
    instances = [_instance("a", "A_TOKEN"), _instance("b", "B_TOKEN")]

    with pytest.raises(ValueError, match="runs instances a and b hold the same token"):
        ingest.tokens(instances, {"A_TOKEN": "same", "B_TOKEN": "same"})
