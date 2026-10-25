from __future__ import annotations

import pytest

from starpulse.flow_metrics.verdicts import cell_verdicts, verdict


def test_trial_matching_baseline_wins_non_inferiority() -> None:
    result = verdict(baseline=[80, 82, 78, 81, 79, 80], trial=[79, 81, 80, 78, 82, 80])
    assert result["verdict"] == "win"
    assert result["p_non_inferior"] >= 0.9


def test_trial_far_below_baseline_loses() -> None:
    result = verdict(baseline=[90, 92, 88, 91, 89, 90], trial=[50, 52, 48, 51, 49, 50])
    assert result["verdict"] == "lose"
    assert result["p_worse"] >= 0.9
    assert result["p_non_inferior"] < 0.1


def test_noisy_overlapping_samples_continue() -> None:
    result = verdict(baseline=[100, 20, 90, 30, 80], trial=[10, 95, 40, 85, 25])
    assert result["verdict"] == "continue"


def test_slightly_worse_inside_the_margin_still_wins() -> None:
    result = verdict(baseline=[80.0, 80.1, 79.9, 80.0, 80.0], trial=[75.0, 75.1, 74.9, 75.0, 75.0])
    assert result["verdict"] == "win"
    assert result["p_worse"] >= 0.9


def test_too_few_tasks_continue_without_posterior() -> None:
    result = verdict(baseline=[80, 82], trial=[70])
    assert result == {"verdict": "continue", "p_non_inferior": None, "p_worse": None}


def test_cell_verdicts_judge_each_profile_against_the_busiest() -> None:
    scores = {
        ("execute", 5, "sonnet-medium"): [80, 82, 78, 81, 79, 80, 81],
        ("execute", 5, "haiku-high"): [50, 52, 48, 51, 49],
        ("execute", 3, "sonnet-medium"): [80, 82, 78],
    }
    rows = cell_verdicts(scores)
    assert [(r["kind"], r["size"], r["baseline"], r["profile"], r["verdict"]) for r in rows] == [
        ("execute", 5, "sonnet-medium", "haiku-high", "lose")
    ]
    assert rows[0]["n"] == 5
    assert rows[0]["baseline_n"] == 7
    assert rows[0]["p_worse"] == pytest.approx(1.0, abs=1e-6)
