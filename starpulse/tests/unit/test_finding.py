"""The `Finding` contract, the fourth one: what an engine may say about a team, machine, state or task, and never a person."""

import json

import jsonschema
import pytest
from pydantic import ValidationError

from starpulse import contracts
from starpulse.contracts import CONTRACTS, SCHEMAS, Evidence, Finding, FindingEngine, FindingScope

FINDING = {
    "id": "slow-review",
    "engine": {"name": "skill-coach", "version": "1.4.0"},
    "scope": {"team": "platform", "machine": "repo/board", "state": "review", "task": "PROJ-45"},
    "severity": "warn",
    "text": "Review takes four times as long as the norm.",
    "evidence": [
        {"label": "time in review", "url": "https://hub.example/history?state=review"},
        {"label": "review dwell by day", "query": "SELECT day, seconds FROM starpulse_day_rollups"},
    ],
    "created_at": 1_700_000_000.0,
    "expires_at": 1_700_086_400.0,
}


def test_a_finding_with_every_field_the_adr_names_is_accepted_and_follows_the_schema() -> None:
    finding = Finding.model_validate(FINDING)

    assert finding.id == "slow-review"
    assert finding.scope.state == "review"
    jsonschema.validate(finding.model_dump(mode="json"), SCHEMAS["insights"])


def test_a_finding_needs_only_its_id_engine_severity_text_and_creation_time() -> None:
    minimal = {k: FINDING[k] for k in ("id", "engine", "severity", "text", "created_at")}

    finding = Finding.model_validate(minimal)

    assert (finding.scope.model_dump(), finding.evidence, finding.expires_at) == (
        {"team": None, "machine": None, "state": None, "task": None},
        (),
        None,
    )


@pytest.mark.parametrize("person", ["person", "user", "assignee", "author", "name", "email", "actor"])
def test_a_scope_that_names_a_person_is_refused_because_the_contract_has_no_person_field(person: str) -> None:
    with pytest.raises(ValidationError, match=person):
        Finding.model_validate({**FINDING, "scope": {**FINDING["scope"], person: "alice"}})


def test_a_person_field_beside_the_scope_is_refused_too() -> None:
    with pytest.raises(ValidationError, match="assignee"):
        Finding.model_validate({**FINDING, "assignee": "alice"})


@pytest.mark.parametrize(
    "change",
    [
        {"id": ""},
        {"severity": "fatal"},
        {"text": ""},
        {"text": "x" * 281},
        {"engine": {"name": "skill-coach"}},
        {"engine": {"name": "", "version": "1"}},
        {"created_at": "yesterday"},
        {"created_at": float("nan")},
        {"expires_at": 1_699_999_999.0},
        {"evidence": [{"label": "no target"}]},
        {"evidence": [{"label": "both", "url": "https://x.example", "query": "SELECT 1"}]},
        {"evidence": [{"label": "", "url": "https://x.example"}]},
    ],
)
def test_a_finding_that_breaks_the_contract_is_refused(change: dict) -> None:
    with pytest.raises(ValidationError):
        Finding.model_validate({**FINDING, **change})


def test_text_of_exactly_280_characters_is_accepted() -> None:
    assert Finding.model_validate({**FINDING, "text": "x" * 280}).text == "x" * 280


def test_the_insights_contract_has_a_json_schema_and_the_checked_in_copy_is_current() -> None:
    checked_in = json.loads((contracts.SCHEMA_DIR / "insights.schema.json").read_text())

    assert checked_in == SCHEMAS["insights"] == CONTRACTS["insights"].model_json_schema()


def test_every_field_of_the_finding_says_what_it_holds() -> None:
    for model in (Finding, FindingEngine, FindingScope, Evidence):
        assert [name for name, field in model.model_fields.items() if not field.description] == [], model
