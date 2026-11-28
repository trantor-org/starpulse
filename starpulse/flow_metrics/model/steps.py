"""Per-step records: one row per model request, with the skill in force, the calls it made and its tokens.

A step is a `request` signal, whichever thread made it (`origin` says which). Its calls are the `tool` signals it
issued, and it carries the activities they performed and one key each: the shell command the instance's redactor
left, else the tool's name. Its task is the one `session_health.attribution` names for the request.

The export's order cannot say which request issued a call: Claude Code starts a tool while the response is still
streaming and logs the request when the stream ends, so a result can come before its own request. A call belongs to
the latest request that started (its time less its duration) at or before the call started; a call that started
before every request of the window belongs to the first. Steps of one subagent that overlap another's can take each
other's calls.

The skill in force is the one the most recent `skill` signal named, counting the loads the step itself issued: a
skill is in force from the step that loads it until the next load, the same charge `bin/skill_step_census.py`
makes from transcripts, and `none` before any load.
"""

from bisect import bisect_right
from collections.abc import Iterable
from typing import Any, NamedTuple

from starpulse.contracts.signals import Signal

__all__ = ["NO_SKILL", "Owned", "combine_steps", "owned_of"]

#: The skill of a step taken before the session loaded any.
NO_SKILL = "none"
_TOKENS = ("input", "output", "cache_read", "cache_write", "reasoning")


class Owned(NamedTuple):
    """A step row, the seconds its request took and the `tool`, `skill` and `decision` signals it owns."""

    step: dict[str, Any]
    seconds: float
    calls: list[Signal]


def _step(task: str | None, s: Signal) -> dict[str, Any]:
    return {
        "harness": s.harness,
        "session": s.session,
        "key": s.key,
        "task": task,
        "at": s.time,
        "model": s.model,
        "effort": s.effort,
        "origin": s.origin,
        "skill": NO_SKILL,
        "activities": [],
        "keys": [],
        "tokens": {name: getattr(s, name) for name in _TOKENS},
        "captured": s.captured,
        "eval": s.eval,
    }


def owned_of(pairs: list[tuple[str | None, Signal]], skill: str = NO_SKILL) -> list[Owned]:
    """Each model request of one session's attributed signals `pairs`, oldest first, with the `tool`, `skill` and
    `decision` signals it owns, in the order they were exported; `skill` is the one in force before the first."""
    steps: list[dict[str, Any]] = []
    seconds: list[float] = []
    starts: list[float] = []
    calls: list[Signal] = []
    for task, s in pairs:
        if s.kind == "request":
            steps.append(_step(task, s))
            seconds.append(s.seconds)
            starts.append(s.time - s.seconds)
        elif s.kind in {"tool", "skill", "decision"}:
            calls.append(s)
    if not steps:
        return []
    by_start = sorted(range(len(steps)), key=starts.__getitem__)
    sorted_starts = [starts[i] for i in by_start]
    loads: list[str | None] = [None] * len(steps)
    owned: list[list[Signal]] = [[] for _ in steps]
    for call in calls:
        owner = by_start[max(bisect_right(sorted_starts, call.time - call.seconds) - 1, 0)]
        owned[owner].append(call)
        if call.kind == "skill":
            loads[owner] = call.name
        elif call.kind == "tool":
            steps[owner]["activities"] += call.activities
            steps[owner]["keys"].append(call.command or call.name)
    current = skill
    for step, load in zip(steps, loads, strict=True):
        current = load or current
        step["skill"] = current
    return [Owned(*row) for row in zip(steps, seconds, owned, strict=True)]


def combine_steps(folds: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The step rows of the sessions' `ledger.steps_of` results as one list, oldest first."""
    return sorted((row for rows in folds for row in rows), key=lambda r: (r["at"], r["harness"], r["session"]))
