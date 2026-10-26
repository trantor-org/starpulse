"""The shipped tdd machine takes a check run's verdict wherever the skill runs the checks."""

from pathlib import Path

import pytest
from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model.graph import Incomplete, conform

TDD = Path(__file__).parents[3] / "starpulse" / "skills" / "tdd" / "machine.yaml"


@pytest.mark.parametrize("verdict", ["LINT_GREEN", "LINT_RED"])
@pytest.mark.parametrize("prefix", [["RED_PROVEN", "GREEN"], ["RED_PROVEN", "GREEN", "AC_CHECKPOINTED"]])
def test_a_check_verdict_is_legal_at_green_and_after_a_checkpoint(prefix: list[str], verdict: str) -> None:
    chart = load_machine(TDD).machine
    assert isinstance(conform(chart, [*prefix, verdict]), Incomplete)
