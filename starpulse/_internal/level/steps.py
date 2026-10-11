"""Per-step records: one row per model request, with the skill in force, the calls it made and its tokens.

A step is a `request` signal, whichever thread made it (`origin` says which). Its calls are the `tool` signals it
issued, and it carries the activities they performed and one key each: the shell command the instance's redactor
left, else the tool's name. Its task is the one `sessions.attributed` names for the request.

The export's order cannot say which request issued a call: Claude Code starts a tool while the response is still
streaming and logs the request when the stream ends, so a result can come before its own request. A call belongs to
the latest request that started (its time less its duration) at or before the call started; a call that started
before every request of the window belongs to the first. Steps of one subagent that overlap another's can take each
other's calls.

The skill in force is the one the most recent `skill` signal named, counting the loads the step itself issued: a
skill is in force from the step that loads it until the next load, the same charge `bin/skill_step_census.py`
makes from transcripts, and `none` before any load. A session that began before the window reads `none` until its
first load inside it.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from typing import Any

from starpulse._internal.config.analytics import Analytics
from starpulse._internal.level.sessions import attributed, grouped
from starpulse._internal.level.signals import Signal
from starpulse.contracts.adapters import TaskKeys

__all__ = ["NO_SKILL", "session_steps"]

#: The skill of a step taken before the session loaded any.
NO_SKILL = "none"
_TOKENS = ("input", "output", "cache_read", "cache_write", "reasoning")


def _step(task: str | None, s: Signal) -> dict[str, Any]:
    return {
        "harness": s.harness,
        "session": s.session,
        "task": task,
        "at": s.time,
        "model": s.model,
        "origin": s.origin,
        "skill": NO_SKILL,
        "activities": [],
        "keys": [],
        "tokens": {name: getattr(s, name) for name in _TOKENS},
        "captured": s.captured,
    }


def session_steps(
    found: Iterable[Signal], keys: TaskKeys | None, analytics: Analytics | None = None
) -> list[dict[str, Any]]:
    """One row per model request of the sessions `found` holds, oldest first; see the module docstring."""
    rows: list[dict[str, Any]] = []
    for ordered in grouped(found, keys, analytics):
        steps: list[dict[str, Any]] = []
        starts: list[float] = []
        calls: list[Signal] = []
        for task, s in attributed(ordered, keys):
            if s.kind == "request":
                steps.append(_step(task, s))
                starts.append(s.time - s.seconds)
            elif s.kind in {"tool", "skill"}:
                calls.append(s)
        if not steps:
            continue
        by_start = sorted(range(len(steps)), key=starts.__getitem__)
        sorted_starts = [starts[i] for i in by_start]
        loads: list[str | None] = [None] * len(steps)
        for call in calls:
            owner = by_start[max(bisect_right(sorted_starts, call.time - call.seconds) - 1, 0)]
            if call.kind == "skill":
                loads[owner] = call.name
            else:
                steps[owner]["activities"] += call.activities
                steps[owner]["keys"].append(call.command or call.name)
        current = NO_SKILL
        for step, load in zip(steps, loads, strict=True):
            current = load or current
            step["skill"] = current
        rows += steps
    return sorted(rows, key=lambda r: (r["at"], r["harness"], r["session"]))
