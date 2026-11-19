"""Admission: whether a Ready task fits the capacity left, and in what order the tasks that fit go.

A task's demand is priced by what a task of its tier and size has drawn. The tasks that fit go in the
order of the task's `tier` field's position in `TIERS`, then the heaviest Priority weight, the most open tasks waiting
on it directly, the deepest critical path and the id; nothing but the field picks a task's tier, and no dependents lift
crosses tiers. A task in a `LEFTOVER_TIERS` tier (`decide`) ranks after every other task and is priced against the
headroom less the demand of every other task admitted, so it takes only the room the others leave. Its session frames the
choice and parks for the operator.

The rule is pure over the sampler's readings, the policy, the run ledger and the board's tasks; the loop that acts on it
is not here. It reads the headroom it is given, so a caller that starts a task passes the readings
again, with that task's demand in them, before deciding the next.
"""

import logging
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from typing import Any

from starpulse.contracts.tiers import DEFAULT_TIER, LEFTOVER_TIERS, TIERS
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
#: The label a post-merge QA miss puts on the task it sends back to In Progress: its fix goes before any other work.
REGRESSION = "regression"

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

    It is `admitted` when its `demand` fits every dimension's headroom, else `blocked_by` the first dimension it overfits;
    `overfit` lists every one it overfits, in gate order, empty for a task refused `NO_PROFILE`.
    `depth` is the longest chain of open tasks waiting on it; `priority` the Priority matrix cell the task ranked by
    (`<impact>/<urgency>`, or `default` for a task with neither) and `weight` that cell's Priority weight.
    `enforced_rank` numbers the admitted tasks from 1 by the order admission follows.
    """

    task: str
    admitted: bool
    blocked_by: str | None
    demand: Mapping[str, float]
    depth: int
    priority: str = "default"
    weight: float = 1.0
    enforced_rank: int | None = None
    overfit: tuple[str, ...] = ()


#: The gates a task meets in the order `decide` tries them, named as the `gate` label of the admission metric.
GATES = ("profile", *DIMENSIONS)


def gate_verdicts(decision: Decision) -> list[tuple[str, str]]:
    """Each gate `decision` met and what it said: `admitted` for a gate it passed, `refused` for the one that bound.

    The gates are tried in order and the first that overfits refuses, so a refused task never met the gates after it.
    """
    binding = "profile" if decision.blocked_by == NO_PROFILE else decision.blocked_by
    verdicts = []
    for gate in GATES:
        if gate == binding:
            return [*verdicts, (gate, "refused")]
        verdicts.append((gate, "admitted"))
    return verdicts


def needs_operator(task: Mapping[str, Any]) -> bool:
    """Whether `task` asks the operator for a decision, which a session can only frame and park."""
    return "kind-decide" in task["labels"]


def _leftover(task: Mapping[str, Any]) -> bool:
    """Whether `task`'s tier is a leftover one, so it goes last and takes only the room others leave."""
    return task.get("tier") in LEFTOVER_TIERS


def _dependents(tasks: Collection[Mapping[str, Any]]) -> dict[str, int]:
    """How many open tasks wait on each task directly."""
    counts: dict[str, int] = {}
    for task in tasks:
        for dependency in task["dependencies"]:
            counts[dependency] = counts.get(dependency, 0) + 1
    return counts


def _enforced_key(task: Mapping[str, Any], dependents: int, decision: Decision) -> tuple[Any, ...]:
    """Where `task` goes in the enforced order: a leftover tier last, else its `tier` field's position in `TIERS` (a task
    with none or an unknown one takes the default tier), then the heaviest weight, dependents, depth and id."""
    tier = task.get("tier")
    return (
        _leftover(task),
        TIERS.index(tier if tier in TIERS else DEFAULT_TIER),
        -decision.weight,
        -dependents,
        -decision.depth,
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


def _why(blocked_by: str | None) -> str:
    """The refusal a log line gives: the dimension that is full or the missing profile."""
    return blocked_by if blocked_by == NO_PROFILE else f"{blocked_by} full"


def decide(
    tasks: Collection[Mapping[str, Any]],
    lane: str,
    readings: Collection[Reading],
    policy: Scheduler,
    ledger: Ledger,
    *,
    log: bool = True,
) -> list[Decision]:
    """A decision for each workable task of `tasks` in `lane`, the admitted first in enforced order, then the refused.

    A task whose profile names no tier in the policy's weights is refused `NO_PROFILE`, whatever room is left. A
    leftover-tier task is priced against the headroom less the demand of every other task admitted, so it starts only
    when nothing else needs the room, and ranks after them.

    `tasks` are all the open tasks, because a task's depth counts the ones waiting on it in other lanes. Each decision is
    logged unless `log` is off, as for a read that only looks.
    """
    depths, dependents = _depths(tasks), _dependents(tasks)
    headroom = {reading.name: reading.limit - reading.use for reading in readings}
    decisions, keys = [], {}
    reserved = dict.fromkeys(DIMENSIONS, 0.0)
    workable = [task for task in tasks if task["state"] == lane and task["workable"]]

    for task in sorted(workable, key=_leftover):  # the decisions last, after the room the others take is known
        need = demand(task, policy, ledger)
        room = {name: headroom[name] - (reserved[name] if _leftover(task) else 0) for name in DIMENSIONS}
        overfit = tuple(name for name in DIMENSIONS if need[name] > room[name])
        if tier_of(task) not in policy.tier_weights:
            blocked_by: str | None = NO_PROFILE
            overfit = ()
        else:
            blocked_by = overfit[0] if overfit else None
        if blocked_by is None and not _leftover(task):
            reserved = {name: reserved[name] + need[name] for name in DIMENSIONS}
        priority, weight = policy.priority_of(task)
        decision = Decision(task["id"], blocked_by is None, blocked_by, need, depths[task["id"]], priority, weight, overfit=overfit)
        keys[decision.task] = _enforced_key(task, dependents.get(decision.task, 0), decision)
        decisions.append(decision)
    admitted = [d for d in decisions if d.admitted]
    enforced = sorted(admitted, key=lambda d: keys[d.task])
    ranked = [replace(d, enforced_rank=rank) for rank, d in enumerate(enforced, 1)]
    refused = sorted((d for d in decisions if not d.admitted), key=lambda d: (-d.depth, d.task))
    for decision in [*ranked, *refused] if log else ():
        logger.info(
            "StarPulse scheduler: %s %s enforced_rank=%s",
            decision.task,
            "admitted" if decision.admitted else f"refused ({_why(decision.blocked_by)})",
            decision.enforced_rank,
        )
    return [*ranked, *refused]
