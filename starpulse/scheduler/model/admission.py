"""Admission: whether a Ready task fits the capacity left, and in what order the tasks that fit go.

A task's demand is priced by what a task of its tier and size has drawn. A `kind-decide` task is never admitted: it
waits on the operator. The tasks that fit rank two ways. The enforced order puts first a bug another open task waits on,
then the other bugs (type `bug`, or labelled `board-state` or `regression`), then the tasks labelled `leverage`, and
within each the most open tasks waiting on it directly, then the deepest critical path, the heaviest Priority weight and
the id. The shadow order is `value / dominant share` (Dominant Resource
Fairness), where value is that weight times depth times the chance of the goal. The shadow order is only logged beside the enforced one until a calibration
report earns it the enforced place (`shadow=False`).

The rule is pure over the sampler's readings, the policy, the run ledger, the board's tasks, the trajectory chain and
each task's forecast P(goal); the loop that acts on it is not here. It reads the headroom it is given, so a caller that starts a task passes the readings
again, with that task's demand in them, before deciding the next.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, replace
from typing import Any

from starpulse.scheduler.model.config import DIMENSIONS, Scheduler
from starpulse.scheduler.model.inputs import points
from starpulse.scheduler.model.ledger import Ledger
from starpulse.scheduler.model.sampler import Reading

#: Runs of one tier and size it takes before their measured demand replaces the prior.
MIN_RUNS = 3
#: Percent of CPU and of memory one point at tier weight 1 is priced at, until runs measure it.
PERCENT_PER_UNIT = 1.0
#: Why a task whose profile names no tier the policy weighs is refused: a session needs a profile to run on.
NO_PROFILE = "no agent profile"
#: Why a `kind-decide` task is refused: only the operator can make the decision it asks for.
NEEDS_OPERATOR = "needs_operator"
#: The labels that mark a task a bug whatever its type: a board that shows the wrong state, or a behavior that regressed.
BUG_LABELS = frozenset({"board-state", "regression"})

logger = logging.getLogger(__name__)

_TIER = re.compile(r"@agent-([a-z]+)-")


def tier_of(task: Mapping[str, Any]) -> str:
    """The tier of the task's agent profile (`@agent-standard-high` is `standard`); empty for a profile with none."""
    match = _TIER.match(task["model"] or "")
    return match[1] if match else ""


def demand(task: Mapping[str, Any], policy: Scheduler, ledger: Ledger) -> dict[str, float]:
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
    `depth` is the longest chain of open tasks waiting on it; `p_goal` the forecast chance of the goal for that task in
    the eligible lane, else the chain's chance from the lane; `predictor` the optional predictor's score; `priority` the Priority matrix cell the task ranked by (`<impact>/<urgency>`,
    or `default` for a task with neither) and `weight` that cell's Priority weight. The ranks number
    the admitted tasks from 1: `shadow_rank` by value over dominant share and `enforced_rank` by the order admission follows.
    """

    task: str
    admitted: bool
    blocked_by: str | None
    demand: Mapping[str, float]
    depth: int
    p_goal: float
    predictor: float | None
    priority: str = "default"
    weight: float = 1.0
    shadow_rank: int | None = None
    enforced_rank: int | None = None


def needs_operator(task: Mapping[str, Any]) -> bool:
    """Whether `task` asks the operator for a decision, which no unattended session can make."""
    return "kind-decide" in task["labels"]


def _dependents(tasks: Collection[Mapping[str, Any]]) -> dict[str, int]:
    """How many open tasks wait on each task directly."""
    counts: dict[str, int] = {}
    for task in tasks:
        for dependency in task["dependencies"]:
            counts[dependency] = counts.get(dependency, 0) + 1
    return counts


def _enforced_key(task: Mapping[str, Any], dependents: int, decision: Decision) -> tuple[Any, ...]:
    """Where `task` goes in the enforced order: blocking bugs, bugs, leverage, then dependents, depth, weight and id."""
    bug = task.get("type") == "bug" or not BUG_LABELS.isdisjoint(task["labels"])
    leverage = "leverage" in task["labels"]
    return (
        not (bug and dependents > 0),
        not bug,
        not leverage,
        -dependents,
        -decision.depth,
        -decision.weight,
        decision.task,
    )


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


def ranks_from_trajectories_body(body: Mapping[str, Any], lane: str) -> dict[str, Any]:
    """The chain and per-task P(goal) `decide` ranks on, taken from a trajectories analytics body.

    `p_goals` is each forecast row whose `state` is `lane` (a Ready task's going run); a task with no row falls back to
    the lane's chain chance inside `decide`.
    """
    chain = body.get("chain") or {}
    p_goals: dict[str, float] = {}
    for row in body.get("forecast") or ():
        chance = row.get("p_goal")
        if row.get("state") == lane and chance is not None:
            p_goals[row["task"]] = float(chance)
    return {"chain": chain, "p_goals": p_goals}


def _score(predictor: Callable[[str], float] | None, task: Mapping[str, Any]) -> float | None:
    """The predictor's score for the task's text, None without a predictor or when it fails: it is only a shadow."""
    if predictor is None:
        return None
    try:
        return predictor(f"{task.get('title', '')}\n{task.get('description', '')}")
    except Exception:  # a predictor is third-party code; admission must not wait on its bug
        logger.exception("StarPulse scheduler: the predictor failed on %s", task["id"])
        return None


def _why(blocked_by: str | None) -> str:
    """The refusal a log line gives: the dimension that is full, the missing profile, or the operator's decision."""
    return blocked_by if blocked_by in (NO_PROFILE, NEEDS_OPERATOR) else f"{blocked_by} full"


def decide(
    tasks: Collection[Mapping[str, Any]],
    lane: str,
    readings: Collection[Reading],
    policy: Scheduler,
    chain: Mapping[str, Mapping[str, Any]],
    ledger: Ledger,
    *,
    predictor: Callable[[str], float] | None = None,
    shadow: bool = True,
    log: bool = True,
    p_goals: Mapping[str, float] | None = None,
) -> list[Decision]:
    """A decision for each workable task of `tasks` in `lane`, the admitted first in enforced order, then the refused.

    A task whose profile names no tier in the policy's weights is refused `NO_PROFILE`, and a `kind-decide` task
    `NEEDS_OPERATOR`, whatever room is left.

    `tasks` are all the open tasks, because a task's depth counts the ones waiting on it in other lanes. `chain` is the
    trajectory analytics' chain (`trajectory_analytics(...)["chain"]`); `p_goals` is each task's forecast chance of the
    goal in `lane`. A task with no forecast row uses the lane's chain chance, and a lane with no row gives P(goal) 1.
    With `shadow` on, the predictor's score and P(goal) rank only the shadow order; off, that order is enforced. Each
    decision is logged unless `log` is off, as for a read that only looks.
    """
    depths, dependents = _depths(tasks), _dependents(tasks)
    limits = {reading.name: reading.limit for reading in readings}
    headroom = {reading.name: reading.limit - reading.use for reading in readings}
    lane_p_goal = chain.get(lane, {}).get("p_goal", 1.0)
    chances = p_goals or {}
    decisions, values, keys = [], {}, {}
    for task in tasks:
        if task["state"] != lane or not task["workable"]:
            continue
        need = demand(task, policy, ledger)
        if needs_operator(task):
            blocked_by: str | None = NEEDS_OPERATOR
        elif tier_of(task) not in policy.tier_weights:
            blocked_by = NO_PROFILE
        else:
            blocked_by = next((name for name in DIMENSIONS if need[name] > headroom[name]), None)
        score = _score(predictor, task)
        p_goal = chances.get(task["id"], lane_p_goal)
        priority, weight = policy.priority_of(task)
        decision = Decision(
            task["id"], blocked_by is None, blocked_by, need, depths[task["id"]], p_goal, score, priority, weight
        )
        share = max(need[name] / limits[name] for name in DIMENSIONS)
        values[decision.task] = decision.weight * decision.depth * (p_goal if score is None else score) / share
        keys[decision.task] = _enforced_key(task, dependents.get(decision.task, 0), decision)
        decisions.append(decision)
    admitted = [d for d in decisions if d.admitted]
    by_shadow = sorted(admitted, key=lambda d: (-values[d.task], -d.depth, d.task))
    by_rule = sorted(admitted, key=lambda d: keys[d.task])
    enforced = by_rule if shadow else by_shadow
    shadow_rank = {d.task: rank for rank, d in enumerate(by_shadow, 1)}
    enforced_rank = {d.task: rank for rank, d in enumerate(enforced, 1)}
    ranked = [replace(d, shadow_rank=shadow_rank[d.task], enforced_rank=enforced_rank[d.task]) for d in enforced]
    refused = sorted((d for d in decisions if not d.admitted), key=lambda d: (-d.depth, d.task))
    for decision in [*ranked, *refused] if log else ():
        logger.info(
            "StarPulse scheduler: %s %s p_goal=%.2f predictor=%s shadow_rank=%s enforced_rank=%s",
            decision.task,
            "admitted" if decision.admitted else f"refused ({_why(decision.blocked_by)})",
            decision.p_goal,
            decision.predictor,
            decision.shadow_rank,
            decision.enforced_rank,
        )
    return [*ranked, *refused]
