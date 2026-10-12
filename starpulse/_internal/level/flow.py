"""The branching directly-follows graph of a transition, read from the steps ledger.

A *run* is one task's main-thread steps under one skill in force (`starpulse._internal.level.steps`) within the
task's kind x size cell, its activities in the order the steps made them less the `[analytics]` `stop_activities`. A
subagent's steps run beside the main thread and would only add edges that never happened, so the graph leaves them out.

The graph has an edge from one activity to the one that directly follows it in a run, from `[start]` to the first and
from the last to `[end]`. An edge reports the runs it occurred in, its `count` and its `share` of the occurrences that
left its source. An activity is a *judgement cut* when it began at least `MIN_N` runs and its commonest successor
takes no more than `CUT_SHARE` of them: the agent chose there, and every edge leaving it is marked `cut`. An activity
with one way on is a deterministic stretch.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from fnmatch import fnmatchcase
from itertools import pairwise
from statistics import median
from typing import Any, NamedTuple

from starpulse._internal.config.analytics import Analytics, MachineStage, SkillMachine
from starpulse._internal.level.cells import MIN_N, cell_of
from starpulse._internal.level.sessions import session_health, slice_health
from starpulse._internal.level.signals import CLAUDE_CODE, Signal
from starpulse._internal.level.steps import NO_SKILL, Owned, owned_steps
from starpulse.contracts.adapters import TaskKeys

__all__ = ["CUT_SHARE", "END", "LONG_STRETCH", "START", "directly_follows", "fast_slow_diff", "sub_stages"]

START, END = "[start]", "[end]"
#: A cut's commonest successor takes at most this share of the occurrences that leave it.
CUT_SHARE = 0.8


class Run(NamedTuple):
    """One task's steps under one skill: every non-auxiliary step, and the activities the main thread made."""

    task: str
    steps: list[Owned]
    activities: list[str]


def runs_by_transition(
    owned: Iterable[Owned], tasks: Mapping[str, Mapping[str, Any]], stop: frozenset[str] = frozenset()
) -> dict[tuple[str, int, str], list[Run]]:
    """The runs of each (kind, size, skill) of the steps `owned`, by task. A step of a Codex session, of a task
    without a kind and size label or of a compaction's own call is in none."""
    grouped: dict[tuple[str, int, str], dict[str, list[Owned]]] = defaultdict(lambda: defaultdict(list))
    for o in owned:
        step = o.step
        if step["captured"] and step["origin"] != "auxiliary" and (cell := cell_of(tasks, step["task"])) is not None:
            grouped[*cell, step["skill"]][step["task"]].append(o)
    return {
        transition: [
            Run(
                task,
                steps,
                [a for o in steps if o.step["origin"] == "main" for a in o.step["activities"] if a not in stop],
            )
            for task, steps in sorted(by_task.items())
        ]
        for transition, by_task in sorted(grouped.items())
    }


def _edges(runs: list[Run]) -> list[dict[str, Any]]:
    occurrences: Counter[tuple[str, str]] = Counter()
    in_runs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for run in runs:
        trail = [START, *run.activities, END]
        for edge in pairwise(trail):
            occurrences[edge] += 1
            in_runs[edge].add(run.task)
    leaving = Counter[str]()
    started: dict[str, set[str]] = defaultdict(set)
    for (source, target), n in occurrences.items():
        leaving[source] += n
        started[source] |= in_runs[source, target]
    cuts = {
        source
        for source in leaving
        if len(started[source]) >= MIN_N
        and max(n for (s, _), n in occurrences.items() if s == source) / leaving[source] <= CUT_SHARE
    }
    return [
        {
            "source": source,
            "target": target,
            "runs": len(in_runs[source, target]),
            "count": n,
            "share": n / leaving[source],
            "cut": source in cuts,
        }
        for (source, target), n in sorted(occurrences.items())
    ]


def directly_follows(
    found: Iterable[Signal],
    keys: TaskKeys | None,
    tasks: Mapping[str, Mapping[str, Any]],
    analytics: Analytics | None = None,
) -> list[dict[str, Any]]:
    """One row per edge of each transition's graph, by kind, size, skill, source, then target; see the module
    docstring."""
    stop = analytics.stop_activities if analytics else frozenset()
    return [
        {"kind": kind, "size": size, "skill": skill, **edge}
        for (kind, size, skill), runs in runs_by_transition(owned_steps(found, keys, analytics), tasks, stop).items()
        for edge in _edges(runs)
    ]


#: A stretch no skill governs is mined for sub-stages from this many activities.
LONG_STRETCH = 20


def _segments(activities: list[str], cuts: set[str]) -> list[tuple[str, int]]:
    """The stages of one stretch as (opener, length): a stage ends with the cut that closes it and the next opens
    with that cut, the first with `[start]`. A stage with no activity is left out."""
    segments, opener, length = [], START, 0
    for activity in activities:
        length += 1
        if activity in cuts:
            segments.append((opener, length))
            opener, length = activity, 0
    return [*segments, (opener, length)] if length else segments


def _stages(runs: list[Run]) -> dict[str, tuple[int, float]]:
    """Each stage mined from the long runs of one cell as opener -> (runs it occurred in, median activities); none
    under `MIN_N` long runs, which are too few to say where the agent chooses."""
    long = [r for r in runs if len(r.activities) >= LONG_STRETCH]
    if len(long) < MIN_N:
        return {}
    cuts = {e["source"] for e in _edges(long) if e["cut"]}
    lengths: dict[str, list[int]] = defaultdict(list)
    tasks: dict[str, set[str]] = defaultdict(set)
    for run in long:
        for opener, length in _segments(run.activities, cuts):
            lengths[opener].append(length)
            tasks[opener].add(run.task)
    return {opener: (len(tasks[opener]), median(found)) for opener, found in lengths.items()}


def sub_stages(
    found: Iterable[Signal],
    keys: TaskKeys | None,
    tasks: Mapping[str, Mapping[str, Any]],
    analytics: Analytics | None = None,
    *,
    since: float = 0.0,
) -> list[dict[str, Any]]:
    """One row per stage mined from the stretches no skill governs, by kind, size, then stage; see the module
    docstring. The runs of steps from `since` on are this week's and the earlier ones the week before's."""
    stop = analytics.stop_activities if analytics else frozenset()
    owned = owned_steps(found, keys, analytics)

    def week(part: list[Owned]) -> dict[tuple[str, int], dict[str, tuple[int, float]]]:
        transitions = runs_by_transition(part, tasks, stop)
        return {(kind, size): _stages(runs) for (kind, size, skill), runs in transitions.items() if skill == NO_SKILL}

    weeks = [week([o for o in owned if o.step["at"] >= since]), week([o for o in owned if o.step["at"] < since])]
    rows = []
    for cell in sorted(weeks[0].keys() | weeks[1].keys()):
        now, before = weeks[0].get(cell, {}), weeks[1].get(cell, {})
        names = now.keys() | before.keys()
        stability = len(now.keys() & before.keys()) / len(names) if now and before else None
        for stage in sorted(names):
            runs, length = now.get(stage, (0, None))
            previous_runs, previous_length = before.get(stage, (0, None))
            rows.append(
                {
                    "kind": cell[0],
                    "size": cell[1],
                    "stage": stage,
                    "runs": runs,
                    "median_activities": length,
                    "previous_runs": previous_runs,
                    "previous_median_activities": previous_length,
                    "stability": stability,
                }
            )
    return rows


def _reaches(stage: MachineStage, call: Signal) -> bool:
    return (stage.ok is None or call.ok == stage.ok) and any(
        fnmatchcase(activity, glob) for activity in call.activities for glob in stage.activities
    )


def _conforms(run: Run, machine: SkillMachine | None) -> bool:
    """Whether the tool calls of `run` reach the stages of `machine` in order; every run conforms to no machine."""
    if machine is None:
        return True
    reached = 0
    for call in sorted((c for o in run.steps for c in o.calls if c.kind == "tool"), key=lambda c: c.time):
        if reached < len(machine.stages) and _reaches(machine.stages[reached], call):
            reached += 1
    return reached == len(machine.stages)


def _counts(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"activity": a, "count": n} for a, n in sorted(counter.items(), key=lambda item: (-item[1], item[0]))]


def fast_slow_diff(
    found: Iterable[Signal],
    keys: TaskKeys | None,
    tasks: Mapping[str, Mapping[str, Any]],
    analytics: Analytics | None = None,
) -> list[dict[str, Any]]:
    """One row per skill's transition within a kind and size, by kind, size, then skill; see the module docstring."""
    stop = analytics.stop_activities if analytics else frozenset()
    machines = {m.skill: m for m in analytics.skill_machines} if analytics else {}
    signals = list(found)
    clean = {
        s["task"]
        for s in slice_health(session_health(signals, keys, analytics))
        if s["clean"] and s["complete"] and set(s["harnesses"]) == {CLAUDE_CODE}
    }
    rows = []
    for (kind, size, skill), runs in runs_by_transition(owned_steps(signals, keys, analytics), tasks, stop).items():
        group = [r for r in runs if r.task in clean]
        reference_bar = [r for r in group if _conforms(r, machines.get(skill))]
        if skill == NO_SKILL or len(group) < MIN_N:
            continue
        reference = min(reference_bar, key=lambda r: (len(r.steps), r.task), default=None)
        slow = max(group, key=lambda r: (len(r.steps), r.task))
        fast, slower = Counter(reference.activities if reference else ()), Counter(slow.activities)
        rows.append(
            {
                "kind": kind,
                "size": size,
                "skill": skill,
                "runs": len(group),
                "conformant": len(reference_bar),
                "reference": {"task": reference.task, "steps": len(reference.steps)} if reference else None,
                "slow": {"task": slow.task, "steps": len(slow.steps)},
                "slow_only": _counts(slower - fast),
                "reference_only": _counts(fast - slower),
            }
        )
    return rows
