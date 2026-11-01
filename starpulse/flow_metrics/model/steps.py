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
from typing import Any, NamedTuple

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import Signal
from starpulse.flow_metrics.model.session_health import attributed, by_session, session_signals

__all__ = ["NO_SKILL", "Owned", "combine_steps", "fold_steps", "session_owned", "session_steps"]

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
        "task": task,
        "at": s.time,
        "model": s.model,
        "origin": s.origin,
        "skill": NO_SKILL,
        "activities": [],
        "keys": [],
        "tokens": {name: getattr(s, name) for name in _TOKENS},
        "captured": s.captured,
        "eval": s.eval,
    }


def session_owned(signals: list[Signal], keys: TaskKeys | None, analytics: Analytics | None = None) -> list[Owned]:
    """Each model request of one session's `signals`, oldest first, with the `tool`, `skill` and `decision`
    signals it owns, in the order they were exported."""
    steps: list[dict[str, Any]] = []
    seconds: list[float] = []
    starts: list[float] = []
    calls: list[Signal] = []
    for task, s in attributed(session_signals(signals, keys, analytics), keys):
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
    current = NO_SKILL
    for step, load in zip(steps, loads, strict=True):
        current = load or current
        step["skill"] = current
    return [Owned(*row) for row in zip(steps, seconds, owned, strict=True)]


def fold_steps(
    signals: list[Signal], keys: TaskKeys | None, analytics: Analytics | None = None
) -> list[dict[str, Any]]:
    """The fold of one session's `signals`: its step rows as plain JSON data; see the module docstring."""
    return [owned.step for owned in session_owned(signals, keys, analytics)]


def combine_steps(folds: Iterable[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """The step rows of the sessions' `fold_steps` results as one list, oldest first."""
    return sorted((row for rows in folds for row in rows), key=lambda r: (r["at"], r["harness"], r["session"]))


def session_steps(
    found: Iterable[Signal], keys: TaskKeys | None, analytics: Analytics | None = None
) -> list[dict[str, Any]]:
    """One row per model request of the sessions `found` holds, oldest first; see the module docstring."""
    return combine_steps(fold_steps(group, keys, analytics) for group in by_session(found))
