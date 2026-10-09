"""Admission: whether a Ready task fits the capacity left, and in what order the tasks that fit go.

A task's demand is priced by what a task of its tier and size has drawn. The tasks that fit rank two ways: the enforced
order is critical-path depth, and the shadow order is `value / dominant share` (Dominant Resource Fairness), where
value is depth times the chance of the goal. The shadow order is only logged beside the enforced one until a calibration
report earns it the enforced place (`shadow=False`).

The rule is pure over the sampler's readings, the policy, the run ledger, the board's tasks and the trajectory chain; the
loop that acts on it is not here. It reads the headroom it is given, so a caller that starts a task passes the readings
again, with that task's demand in them, before deciding the next.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace
from typing import Any

from starpulse._internal.autopilot.inputs import points
from starpulse._internal.autopilot.ledger import Ledger
from starpulse._internal.autopilot.sampler import Reading
from starpulse._internal.config.autopilot import DIMENSIONS, Autopilot

#: Runs of one tier and size it takes before their measured demand replaces the prior.
MIN_RUNS = 3
#: Percent of CPU and of memory one point at tier weight 1 is priced at, until runs measure it.
PERCENT_PER_UNIT = 1.0

logger = logging.getLogger(__name__)

_TIER = re.compile(r"@agent-([a-z]+)-")


def tier_of(task: Mapping[str, Any]) -> str:
    """The tier of the task's agent profile (`@agent-standard-high` is `standard`); empty for a profile with none."""
    match = _TIER.match(task["model"] or "")
    return match[1] if match else ""


def demand(task: Mapping[str, Any], policy: Autopilot, ledger: Ledger) -> dict[str, float]:
    """What `task` draws on each dimension: the mean peak of past runs of its tier and size once `MIN_RUNS` exist, else
    its prior: its points times its tier's weight as a share of CPU and memory, one session, its points of review.

    A tier with no weight prices at the dearest, so a task of an unknown profile never fits where a known one would not.
    """
    tier, size = tier_of(task), points(task["labels"], policy.unsized_points)
    if (measured := ledger.measured(tier, size, MIN_RUNS)) is not None:
        return measured
    percent = size * policy.tier_weights.get(tier, max(policy.tier_weights.values())) * PERCENT_PER_UNIT
    return {"cpu": percent, "memory": percent, "sessions": 1, "review": size}


@dataclass(frozen=True)
class Decision:
    """One eligible task's verdict.

    It is `admitted` when its `demand` fits every dimension's headroom, else `blocked_by` the first dimension it overfits.
    `depth` is the longest chain of open tasks waiting on it; `p_goal` the chain's chance of the goal from its lane and
    `predictor` the optional predictor's score. The ranks number the admitted tasks from 1: `shadow_rank` by value over
    dominant share and `enforced_rank` by the order admission follows.
    """

    task: str
    admitted: bool
    blocked_by: str | None
    demand: Mapping[str, float]
    depth: int
    p_goal: float
    predictor: float | None
    shadow_rank: int | None = None
    enforced_rank: int | None = None


def _depths(tasks: Collection[Mapping[str, Any]]) -> dict[str, int]:
    """Each task's critical-path depth: itself plus the longest chain of open tasks that wait on it, directly or not."""
    dependents: dict[str, list[str]] = {}
    for task in tasks:
        for dependency in task["dependencies"]:
            dependents.setdefault(dependency, []).append(task["id"])
    depths: dict[str, int] = {}

    def depth(task_id: str, above: frozenset[str]) -> int:
        if task_id not in depths:
            above = above | {task_id}  # a dependency cycle ends the chain rather than the recursion
            depths[task_id] = 1 + max(
                (depth(after, above) for after in dependents.get(task_id, ()) if after not in above), default=0
            )
        return depths[task_id]

    return {task["id"]: depth(task["id"], frozenset()) for task in tasks}


def _score(predictor: Callable[[str], float] | None, task: Mapping[str, Any]) -> float | None:
    """The predictor's score for the task's text, None without a predictor or when it fails: it is only a shadow."""
    if predictor is None:
        return None
    try:
        return predictor(f"{task.get('title', '')}\n{task.get('description', '')}")
    except Exception:  # a predictor is third-party code; admission must not wait on its bug
        logger.exception("StarPulse autopilot: the predictor failed on %s", task["id"])
        return None


def decide(
    tasks: Collection[Mapping[str, Any]],
    lane: str,
    readings: Collection[Reading],
    policy: Autopilot,
    chain: Mapping[str, Mapping[str, Any]],
    ledger: Ledger,
    *,
    predictor: Callable[[str], float] | None = None,
    shadow: bool = True,
) -> list[Decision]:
    """A decision for each workable task of `tasks` in `lane`, the admitted first in enforced order, then the refused.

    `tasks` are all the open tasks, because a task's depth counts the ones waiting on it in other lanes. `chain` is the
    trajectory analytics' chain (`trajectory_analytics(...)["chain"]`); a lane with no row, as in a board with no history,
    gives P(goal) 1. With `shadow` on, the predictor's score and P(goal) rank only the shadow order; off, that order is
    enforced.
    """
    depths = _depths(tasks)
    limits = {reading.name: reading.limit for reading in readings}
    headroom = {reading.name: reading.limit - reading.use for reading in readings}
    p_goal = chain.get(lane, {}).get("p_goal", 1.0)
    decisions, values = [], {}
    for task in tasks:
        if task["state"] != lane or not task["workable"]:
            continue
        need = demand(task, policy, ledger)
        blocked_by = next((name for name in DIMENSIONS if need[name] > headroom[name]), None)
        score = _score(predictor, task)
        decision = Decision(task["id"], blocked_by is None, blocked_by, need, depths[task["id"]], p_goal, score)
        share = max(need[name] / limits[name] for name in DIMENSIONS)
        values[decision.task] = decision.depth * (p_goal if score is None else score) / share
        decisions.append(decision)
    admitted = [d for d in decisions if d.admitted]
    by_shadow = sorted(admitted, key=lambda d: (-values[d.task], -d.depth, d.task))
    by_depth = sorted(admitted, key=lambda d: (-d.depth, d.task))
    enforced = by_depth if shadow else by_shadow
    shadow_rank = {d.task: rank for rank, d in enumerate(by_shadow, 1)}
    enforced_rank = {d.task: rank for rank, d in enumerate(enforced, 1)}
    ranked = [replace(d, shadow_rank=shadow_rank[d.task], enforced_rank=enforced_rank[d.task]) for d in enforced]
    refused = sorted((d for d in decisions if not d.admitted), key=lambda d: (-d.depth, d.task))
    for decision in [*ranked, *refused]:
        logger.info(
            "StarPulse autopilot: %s %s p_goal=%.2f predictor=%s shadow_rank=%s enforced_rank=%s",
            decision.task,
            "admitted" if decision.admitted else f"refused ({decision.blocked_by} full)",
            decision.p_goal,
            decision.predictor,
            decision.shadow_rank,
            decision.enforced_rank,
        )
    return [*ranked, *refused]
