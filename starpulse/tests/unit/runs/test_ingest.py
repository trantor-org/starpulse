"""The push helpers every ingest route shares: whose token a bearer is, and which run events the contract allows."""

from __future__ import annotations

from typing import Any

import pytest

from starpulse.runs.config import Producer
from starpulse.runs import ingest

TOKENS = {"cron": "s3cret-cron", "dagu": "s3cret-dagu"}


def event(**fields: Any) -> dict[str, Any]:
    base = {"event": "StepStarted", "workflow": "nightly", "run_id": "r1", "status": "running"} | fields
    return {key: value for key, value in base.items() if value is not None}


@pytest.mark.parametrize("authorization", ["Bearer s3cret-cron", "bearer s3cret-cron"])
def test_a_bearer_token_names_the_instance_it_belongs_to(authorization: str) -> None:
    assert ingest.token_owner(TOKENS, authorization) == "cron"


@pytest.mark.parametrize(
    "authorization", [None, "", "Bearer", "Bearer wrong", "Basic s3cret-cron", "s3cret-cron", "Bearer s3cret-cro"]
)
def test_a_missing_or_wrong_token_names_no_instance(authorization: str | None) -> None:
    assert ingest.token_owner(TOKENS, authorization) is None


def test_a_valid_run_event_is_returned_as_it_was_sent() -> None:
    sent = event(time=1.5, step="load", depends=["fetch"])

    assert ingest.run_event(sent) is sent


@pytest.mark.parametrize(
    "sent",
    [
        [],
        "text",
        event(workflow=None),
        event(workflow=""),
        event(event="pause"),
        event(status="exploded"),
        event(run_id=""),
        event(run_id=7),
        event(time="soon"),
        event(time=True),
        event(depends=["a"]),
        event(step="load", depends="fetch"),
        event(step="load", depends=[1]),
        event(step=3),
    ],
)
def test_an_event_the_contract_does_not_allow_is_refused_with_its_reason(sent: object) -> None:
    assert isinstance(ingest.run_event(sent), str)


def test_tokens_are_read_from_the_environment_for_each_instance_that_names_one() -> None:
    instances = [Producer("cron", "CRON_TOKEN", (), ()), Producer("dagu", "", (), ())]

    assert ingest.tokens(instances, {"CRON_TOKEN": "s3", "OTHER": "x"}) == {"cron": "s3"}


@pytest.mark.parametrize("environ", [{}, {"CRON_TOKEN": ""}])
def test_an_instance_whose_token_variable_is_unset_or_empty_is_an_error(environ: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="runs instance cron: CRON_TOKEN is not set"):
        ingest.tokens([Producer("cron", "CRON_TOKEN", (), ())], environ)


def test_two_instances_holding_the_same_token_is_an_error() -> None:
    instances = [Producer("a", "A_TOKEN", (), ()), Producer("b", "B_TOKEN", (), ())]

    with pytest.raises(ValueError, match="runs instances a and b hold the same token"):
        ingest.tokens(instances, {"A_TOKEN": "same", "B_TOKEN": "same"})
