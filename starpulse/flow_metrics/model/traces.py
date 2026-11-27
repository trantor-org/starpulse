"""A case's Trace: the skill one session executed on one task and the Activities its main thread performed, in order.

A case is a run of one session's main-thread steps that name the same task and the same skill; it ends when another
skill loads or another task is named, or when its session ends. Two cases are the same distinctive work when their
ordered Activities are equal once adjacent repeats are collapsed, so a case that ran `git status` three times in a row
shares its key with one that ran it once.
"""

import hashlib
from typing import Any

from starpulse.flow_metrics.model.steps import NO_SKILL

__all__ = ["cases_of", "cluster_key"]


def cluster_key(activities: list[str]) -> str:
    """The stable id of the work `activities` name, in order."""
    return hashlib.sha1(f"trace|{' > '.join(activities)}".encode()).hexdigest()[:12]


def cases_of(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The cases of one session's step `rows`, oldest first, the last one still open. Each is plain JSON data: its
    `task`, `skill`, `started_at`, `ended_at` and `activities`. A case may have no Activity; it has no Trace."""
    cases: list[dict[str, Any]] = []
    steps = (r["step"] for r in rows)
    for step in sorted((s for s in steps if s["captured"] and s["origin"] == "main" and s["task"]), key=lambda s: s["at"]):
        if step["skill"] == NO_SKILL:
            continue
        if not cases or (cases[-1]["task"], cases[-1]["skill"]) != (step["task"], step["skill"]):
            cases.append(
                {"task": step["task"], "skill": step["skill"], "started_at": step["at"], "ended_at": step["at"], "activities": []}
            )
        case = cases[-1]
        case["ended_at"] = step["at"]
        for name in step["activities"]:
            if not case["activities"] or case["activities"][-1] != name:
                case["activities"].append(name)
    return cases
