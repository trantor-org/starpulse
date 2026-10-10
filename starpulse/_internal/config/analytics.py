"""The `[analytics]` config table: what the instance's agents' telemetry is read against.

StarPulse reads missed skill loads and trace clusters from the harness exports (`GET /api/analytics/missed-loads`,
`GET /api/analytics/trace-clusters`), and the vocabulary those reads need belongs to the instance, not the package:

- `roots`: absolute checkout paths. A path a tool call read or wrote is cut to an area (its first two components) below
  the root it is under; a `*` matches one path component, so `/repo/.claude/worktrees/*` is every worktree of `/repo`.
  A path under no root is no area, and with no root there are no areas.
- `stop_activities`: activities that say how a session was run, not what work it did; they never define a cluster.
- `lifecycle_skills`: skills every task's delivery loads, so loading one says nothing about the work.
- `[[analytics.skill_loads]]`: per `skill`, what should load it: any of `activities` (globs over an activity's name),
  a task whose title matches `title` (a regular expression, case-insensitive) or one carrying `label`. A case that
  ran a trigger without activating the skill is a missed load; a skill with no declaration is never reported.

What a session's own events say about its work is read against four more keys, so the package names no instance's
tasks or skills (`GET /api/analytics/sessions`):

- `injected_openings`: prefixes of a prompt's text. A prompt that opens with one is labelled `injected` (a harness
  or scheduler wrote it), any other `human`; the label is stored and the text never is.
- `claims`: regular expressions run over each shell command and each `Skill` call's arguments. Group 1 is a task
  key; a match under the board's key scheme says the session now works that task, and every step after it is the
  task's until another claim.
- `completion_skill` and `completion_call`: a task is complete in a session that loaded the skill and ran a shell
  command matching the call.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

__all__ = ["Analytics", "AnalyticsError", "SkillLoad", "parse_analytics"]

_KEYS = {
    "roots",
    "stop_activities",
    "lifecycle_skills",
    "skill_loads",
    "injected_openings",
    "claims",
    "completion_skill",
    "completion_call",
}
_LOAD_KEYS = {"skill", "activities", "title", "label"}


class AnalyticsError(ValueError):
    """The table cannot be read; the message names the key to fix."""


@dataclass(frozen=True)
class SkillLoad:
    """What should load `skill`: any activity matching one of the `activities` globs, or a task with a title matching
    `title` or carrying `label`."""

    skill: str
    activities: frozenset[str] = frozenset()
    title: re.Pattern[str] | None = None
    label: str | None = None


@dataclass(frozen=True)
class Analytics:
    roots: tuple[str, ...] = ()
    """The checkouts a path is cut to an area under; none: no areas."""
    stop_activities: frozenset[str] = frozenset()
    """Activities that never define a trace cluster."""
    lifecycle_skills: frozenset[str] = frozenset()
    """Skills every task's delivery loads, left out of what a cluster's cases loaded."""
    skill_loads: tuple[SkillLoad, ...] = field(default_factory=tuple)
    """What should load each declared skill."""
    injected_openings: tuple[str, ...] = ()
    """Prefixes that label a prompt `injected`; none: every prompt is `human`."""
    claims: tuple[re.Pattern[str], ...] = ()
    """Patterns whose group 1 is the task a shell command or a `Skill` call's arguments claims; none: no claims."""
    completion_skill: str = ""
    """The skill whose load, with a `completion_call`, marks a session's task complete."""
    completion_call: re.Pattern[str] | None = None
    """The shell command that, after `completion_skill` loaded, marks the task complete."""


def _texts(raw: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise AnalyticsError(f"analytics: {key} must be a list of text")
    return tuple(value)


def _load(raw: object, at: int) -> SkillLoad:
    who = f"analytics.skill_loads[{at}]"
    if not isinstance(raw, dict):
        raise AnalyticsError(f"{who} must be a [[analytics.skill_loads]] table")
    if unknown := sorted(raw.keys() - _LOAD_KEYS):
        raise AnalyticsError(f"{who}: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_LOAD_KEYS))}")
    if not isinstance(skill := raw.get("skill"), str) or not skill:
        raise AnalyticsError(f"{who} needs skill")
    activities = frozenset(_texts(raw, "activities"))
    title, label = raw.get("title"), raw.get("label")
    if not (activities or title or label):
        raise AnalyticsError(f"{who}: needs activities, title or label")
    if label is not None and not isinstance(label, str):
        raise AnalyticsError(f"{who}: label must be text")
    pattern = None
    if title is not None:
        try:
            pattern = re.compile(str(title), re.IGNORECASE)
        except re.error as exc:
            raise AnalyticsError(f"{who}: title is not a regular expression: {exc}") from exc
    return SkillLoad(skill, activities, pattern, label)


def _pattern(value: object, who: str) -> re.Pattern[str]:
    if not isinstance(value, str) or not value:
        raise AnalyticsError(f"analytics: {who} must be a regular expression")
    try:
        return re.compile(value)
    except re.error as exc:
        raise AnalyticsError(f"analytics: {who} is not a regular expression: {exc}") from exc


def _claims(raw: Mapping[str, object]) -> tuple[re.Pattern[str], ...]:
    found = raw.get("claims", [])
    if not isinstance(found, list):
        raise AnalyticsError("analytics: claims must be a list of text")
    patterns = tuple(_pattern(value, f"claims[{at}]") for at, value in enumerate(found))
    for at, pattern in enumerate(patterns):
        if pattern.groups < 1:
            raise AnalyticsError(f"analytics: claims[{at}] needs a group that captures the task key")
    return patterns


def parse_analytics(raw: object) -> Analytics:
    """The `[analytics]` table, or the empty one for `None`; each refusal names the key to fix."""
    if raw is None:
        return Analytics()
    if not isinstance(raw, dict):
        raise AnalyticsError("analytics must be an [analytics] table")
    if unknown := sorted(raw.keys() - _KEYS):
        raise AnalyticsError(f"analytics: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_KEYS))}")
    roots = _texts(raw, "roots")
    if not all(root.startswith("/") for root in roots):
        raise AnalyticsError("analytics: roots must be absolute paths")
    loads = raw.get("skill_loads", [])
    if not isinstance(loads, list):
        raise AnalyticsError("analytics: skill_loads must be a list of [[analytics.skill_loads]] tables")
    skill = raw.get("completion_skill", "")
    if not isinstance(skill, str):
        raise AnalyticsError("analytics: completion_skill must be text")
    call = raw.get("completion_call")
    return Analytics(
        roots,
        frozenset(_texts(raw, "stop_activities")),
        frozenset(_texts(raw, "lifecycle_skills")),
        tuple(_load(table, at) for at, table in enumerate(loads)),
        _texts(raw, "injected_openings"),
        _claims(raw),
        skill,
        None if call is None else _pattern(call, "completion_call"),
    )
