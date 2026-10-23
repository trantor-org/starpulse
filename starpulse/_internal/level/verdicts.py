"""The non-inferiority verdict of a trial profile against its cell's baseline.

Per ADR "Randomized step-down trials", the cheaper setting wins at >=90% posterior probability that its score is within
10 points of the baseline's, and loses at >=90% that it is worse. The posterior of the difference of the two mean scores
is a normal (flat prior, Welch standard error), so both probabilities are normal tails. A win outranks a loss: a trial
worse by less than the margin is still non-inferior. Fewer than two tasks on either side is `continue`, with no posterior.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import sqrt
from statistics import NormalDist, mean, variance
from typing import Any

__all__ = ["CONFIDENCE", "MARGIN", "cell_verdicts", "verdict"]

MARGIN = 10.0
CONFIDENCE = 0.9
_STANDARD = NormalDist()


def _tail(centre: float, spread: float) -> float:
    """P(difference > 0) for a difference with mean `centre` and standard error `spread`."""
    if spread == 0:
        return 1.0 if centre > 0 else 0.0
    return _STANDARD.cdf(centre / spread)


def verdict(baseline: Sequence[float], trial: Sequence[float]) -> dict[str, Any]:
    """`{verdict, p_non_inferior, p_worse}` of `trial` task scores against `baseline` task scores."""
    if len(baseline) < 2 or len(trial) < 2:
        return {"verdict": "continue", "p_non_inferior": None, "p_worse": None}
    gap = mean(trial) - mean(baseline)
    spread = sqrt(variance(trial) / len(trial) + variance(baseline) / len(baseline))
    non_inferior = _tail(gap + MARGIN, spread)
    worse = _tail(-gap, spread)
    if non_inferior >= CONFIDENCE:
        outcome = "win"
    elif worse >= CONFIDENCE:
        outcome = "lose"
    else:
        outcome = "continue"
    return {"verdict": outcome, "p_non_inferior": non_inferior, "p_worse": worse}


def cell_verdicts(scores: Mapping[tuple[str, int, str], Sequence[float]]) -> list[dict[str, Any]]:
    """One row per trial profile of each kind x size cell with more than one profile: `{kind, size, baseline, profile,
    n, baseline_n, verdict, p_non_inferior, p_worse}`. The baseline is the cell's profile with the most tasks."""
    cells: dict[tuple[str, int], dict[str, Sequence[float]]] = {}
    for (kind, size, profile), held in scores.items():
        cells.setdefault((kind, size), {})[profile] = held
    rows = []
    for (kind, size), profiles in sorted(cells.items()):
        baseline = max(sorted(profiles), key=lambda profile: len(profiles[profile]))
        for profile in sorted(profiles):
            if profile != baseline:
                rows.append(
                    {"kind": kind, "size": size, "baseline": baseline, "profile": profile, "n": len(profiles[profile]),
                     "baseline_n": len(profiles[baseline]), **verdict(profiles[baseline], profiles[profile])}
                )
    return rows
