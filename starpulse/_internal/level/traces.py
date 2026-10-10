"""Missed skill loads and trace clusters: what a session's tool calls say about the work it did.

A case is one session's work on one task (`starpulse._internal.level.sessions.attributed` names the task), read from
the `tool` and `skill` signals of its telemetry export: its `activities` in order, the `skills` it activated, and the
repository areas it `reads` and `writes`. A tool signal stored before activities were kept is its tool name.

An area is a path cut to its first two components below a configured root, so a path under a task worktree and one
under the main checkout are the same area and a path outside every root is none. A root may hold a `*`, which matches
one path component, so `/repo/.claude/worktrees/*` names every worktree of `/repo`; the root that leaves the least
path wins.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from starpulse._internal.config.analytics import SkillLoad
from starpulse._internal.level.sessions import attributed, grouped, session_kind
from starpulse._internal.level.signals import Signal
from starpulse.contracts.adapters import TaskKeys

__all__ = ["Case", "Missed", "cases", "missed_loads"]

#: Components of an area: `lib/store` for `lib/store/src/x.py`.
_AREA_DEPTH = 2


@dataclass(frozen=True)
class Case:
    """One session's work on one task."""

    harness: str
    session: str
    task: str | None
    kind: str
    tool_calls: int
    activities: tuple[str, ...]
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    skills: tuple[str, ...]
    last_seen: float
    title: str | None = None
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Missed:
    """The cases that performed a skill's trigger, and those of them that did not load the skill."""

    skill: str
    performed: tuple[Case, ...]
    missed: tuple[Case, ...]


def _roots(roots: Sequence[str]) -> list[re.Pattern[str]]:
    return [re.compile(re.escape(root.rstrip("/")).replace(r"\*", "[^/]+") + "/(.+)") for root in roots]


def _area(path: str, roots: list[re.Pattern[str]]) -> str | None:
    below = [m[1] for pattern in roots if (m := pattern.fullmatch(path))]
    if not below:
        return None
    return "/".join(min(below, key=len).split("/")[:_AREA_DEPTH])


def _areas(paths: Iterable[str], roots: list[re.Pattern[str]]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(a for p in paths if (a := _area(p, roots)) is not None))


def cases(
    found: Iterable[Signal],
    keys: TaskKeys | None,
    *,
    roots: Sequence[str] = (),
    tasks: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[Case]:
    """One case per (session, task) of `found`, oldest first. `tasks` maps a task key to its board entry, whose `title`
    and `labels` a case carries; `roots` are the checkouts whose paths become areas."""
    patterns = _roots(roots)
    built: list[Case] = []
    for ordered in grouped(found):
        kind = session_kind(ordered)
        by_task: dict[str | None, dict[str, Any]] = {}
        for task, s in attributed(ordered, keys):
            if s.kind not in {"tool", "skill"}:
                continue
            work = by_task.setdefault(task, {"calls": 0, "activities": [], "reads": [], "writes": [], "skills": []})
            work["last"] = s.time
            if s.kind == "skill":
                work["skills"].append(s.name)
                continue
            work["calls"] += 1
            work["activities"] += s.activities or (s.name,)
            work["reads"] += s.reads
            work["writes"] += s.writes
        for task, work in by_task.items():
            entry = (tasks or {}).get(task or "", {})
            built.append(
                Case(
                    harness=ordered[0].harness,
                    session=ordered[0].session,
                    task=task,
                    kind=kind,
                    tool_calls=work["calls"],
                    activities=tuple(work["activities"]),
                    reads=_areas(work["reads"], patterns),
                    writes=_areas(work["writes"], patterns),
                    skills=tuple(dict.fromkeys(work["skills"])),
                    last_seen=work["last"],
                    title=entry.get("title"),
                    labels=tuple(entry.get("labels") or ()),
                )
            )
    return sorted(built, key=lambda c: (c.last_seen, c.harness, c.session, c.task or ""))


def _performs(case: Case, trigger: SkillLoad) -> bool:
    if any(fnmatchcase(a, pattern) for a in case.activities for pattern in trigger.activities):
        return True
    # A task shape says what the case was for; only a case with a trace did it.
    shaped = bool(trigger.title and case.title and trigger.title.search(case.title)) or bool(
        trigger.label and trigger.label in case.labels
    )
    return shaped and case.tool_calls > 0


def missed_loads(found: Iterable[Case], triggers: Sequence[SkillLoad]) -> list[Missed]:
    """Per trigger, the cases of `found` that performed it and those that did so without loading its skill."""
    held = list(found)
    result = []
    for trigger in triggers:
        performed = tuple(c for c in held if _performs(c, trigger))
        result.append(Missed(trigger.skill, performed, tuple(c for c in performed if trigger.skill not in c.skills)))
    return result
