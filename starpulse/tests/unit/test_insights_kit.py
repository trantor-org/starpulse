"""The insights engine kit fails an engine that breaks the contract or the API's behavior, and passes one that keeps both."""

from collections.abc import Callable

import pytest
from pydantic import ValidationError

from starpulse.adapter_kit import InsightsEngineKit

FINDING = {
    "id": "slow-review",
    "engine": {"name": "skill-coach", "version": "1.4.0"},
    "scope": {"team": "platform", "state": "review"},
    "severity": "warn",
    "text": "Review takes four times as long as the norm.",
    "evidence": [{"label": "time in review", "url": "https://hub.example/history?state=review"}],
    "created_at": 1_700_000_000.0,
}
OTHER = {**FINDING, "id": "stuck-task", "scope": {"task": "PROJ-45"}, "severity": "act", "expires_at": 1_700_086_400.0}


def engine(findings: list[dict]) -> InsightsEngineKit:
    return type("Engine", (InsightsEngineKit,), {"produce": lambda self: findings})()


def failing(check: Callable[[], None]) -> bool:
    try:
        check()
    except AssertionError, ValidationError:
        return True
    return False


def every_check(kit: InsightsEngineKit) -> dict[str, Callable[[], None]]:
    return {name: getattr(kit, name) for name in dir(kit) if name.startswith("test_")}


def test_an_engine_that_keeps_the_contract_passes_every_check() -> None:
    checks = every_check(engine([FINDING, OTHER]))

    assert len(checks) == 4
    assert {name: failing(check) for name, check in checks.items()} == dict.fromkeys(checks, False)


@pytest.mark.parametrize(
    "bad",
    [
        {**FINDING, "text": "x" * 281},
        {**FINDING, "severity": "fatal"},
        {**FINDING, "scope": {"team": "platform", "assignee": "alice"}},
        {k: v for k, v in FINDING.items() if k != "evidence"} | {"evidence": [{"label": "no target"}]},
    ],
)
def test_an_engine_whose_finding_breaks_the_contract_fails_a_check(bad: dict) -> None:
    assert any(failing(check) for check in every_check(engine([bad])).values())


def test_an_engine_posting_one_id_twice_fails_a_check() -> None:
    assert any(failing(check) for check in every_check(engine([FINDING, FINDING])).values())


def test_an_engine_with_no_findings_is_told_nothing_is_checked() -> None:
    with pytest.raises(AssertionError, match="no findings"):
        engine([]).test_the_engine_produces_findings()


def test_an_engine_that_does_not_override_produce_is_told_to() -> None:
    with pytest.raises(NotImplementedError, match="override produce"):
        InsightsEngineKit().produce()
