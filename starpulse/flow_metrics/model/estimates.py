"""The estimate report: each completed task's size estimate beside what it measured.

A task's estimate is its `size-<n>` and `kind-<kind>` labels and its profile. Its actuals are the steps (a subagent's
included) and active minutes (agent seconds plus the operator's wait) of its slice
(`starpulse.flow_metrics.model.session_health.slice_health`). `bands` are the instance's sizes with the p90 steps and
active minutes a task of that size lands within (`[analytics]` `size_bands`), smallest first: the *effort size* is the
smallest size whose band holds both actuals, and the *effort size step* is how many sizes it lies above (positive) or
below (negative) the label. Effort past the largest band has no size and steps to one past the top. With no bands, or a
label that is no band's size, the step is None; with no bands the effort size is too.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from starpulse.flow_metrics.model.cells import cell_of

__all__ = ["estimate_report"]

SizeBand = tuple[int, int, float]


def _effort_rank(bands: Sequence[SizeBand], steps: int, minutes: float) -> int:
    """The index of the first band holding `steps` and `minutes`, or `len(bands)` past the last."""
    fits = (i for i, (_, p90_steps, p90_minutes) in enumerate(bands) if steps <= p90_steps and minutes <= p90_minutes)
    return next(fits, len(bands))


def estimate_report(
    slices: Iterable[Mapping[str, Any]],
    tasks: Mapping[str, Mapping[str, Any]],
    bands: Sequence[SizeBand],
    milestone: str | None = None,
) -> list[dict[str, Any]]:
    """One row per completed, kind- and size-labelled task of `slices` (in `milestone` when given), oldest first; see
    the module docstring."""
    ranks = {size: i for i, (size, _, _) in enumerate(bands)}
    rows = []
    for s in slices:
        cell = cell_of(tasks, s["task"])
        task = tasks.get(s["task"], {})
        if not s["complete"] or cell is None or (milestone is not None and task.get("milestone") != milestone):
            continue
        (kind, size), steps = cell, s["steps"] + s["side_steps"]
        minutes = (s["active_s"] + s["operator_wait_s"]) / 60
        rank = _effort_rank(bands, steps, minutes)
        rows.append(
            {
                "task": s["task"],
                "milestone": task.get("milestone"),
                "kind": kind,
                "size": size,
                "profile": task.get("profile"),
                "steps": steps,
                "active_minutes": round(minutes, 1),
                "effort_size": bands[rank][0] if rank < len(bands) else None,
                "effort_size_step": rank - ranks[size] if size in ranks else None,
            }
        )
    return rows
