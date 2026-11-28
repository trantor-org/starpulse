"""A task's Start Criteria on its record: the event subjects a Waiting task waits on, parsed from the description.

The description's `## Start Criteria` section holds a fenced YAML block, `start_criteria:` a list of entries each with an
`id`, a `kind` and the expression it names (`query`, `expr` or `path`). A parked task's entries are `kind: event`, the
`query` an event subject (`starpulse.<board>.<entity>.<id>.<event>`) the task actor waits on, so the first event of any
of them releases the task; no command evaluates them.
"""

import re
from typing import Any

import yaml

__all__ = ["authored", "bare", "commits", "expect_dates", "subjects"]

EVENT = "event"
_SECTION = re.compile(r"^## Start Criteria\s*$(.*?)(?=^## |\Z)", re.M | re.S)
_FENCE = re.compile(r"```ya?ml\s*\n(.*?)```", re.S)


def declared(description: str) -> list[dict[str, Any]]:
    """The mappings of the description's `start_criteria` block that carry an id, as written."""
    section = _SECTION.search(description)
    fenced = _FENCE.search(section.group(1)) if section else None
    try:
        parsed = yaml.safe_load(fenced.group(1)) if fenced else None
    except yaml.YAMLError:
        return []
    listed = parsed.get("start_criteria") if isinstance(parsed, dict) else None
    return [raw for raw in listed if isinstance(raw, dict) and raw.get("id")] if isinstance(listed, list) else []


def expect_dates(description: str) -> list[str]:
    """The `expect_by` dates the description's Start Criteria declare, each as text, in the order written."""
    return [str(raw["expect_by"]) for raw in declared(description) if raw.get("expect_by") is not None]


def authored(description: str) -> list[dict[str, Any]]:
    """The criteria the description's `start_criteria` block declares, as `{id, kind, expr}`; empty when it has none."""
    return [
        {
            "id": str(raw["id"]),
            "kind": str(raw.get("kind") or ""),
            "expr": str(raw.get("query") or raw.get("expr") or raw.get("path") or ""),
        }
        for raw in declared(description)
    ]


def bare(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`items` cut to the authored `{id, kind, expr}`, without the status fields an evaluator adds."""
    return [{key: item.get(key) for key in ("id", "kind", "expr")} for item in items]


def subjects(description: str) -> tuple[str, ...]:
    """The event subjects the description's Start Criteria wait on, in the order written."""
    return tuple(each["expr"] for each in authored(description) if each["kind"] == EVENT and each["expr"])


def commits(description: str) -> dict[str, str]:
    """The commit each event subject waits for: only an event whose build contains it releases the task."""
    return {
        each["expr"]: str(raw["commit"])
        for each, raw in zip(authored(description), declared(description))
        if raw.get("commit")
    }


def accepting_met(description: str) -> frozenset[str]:
    """The event subjects whose park accepts an event recorded before it (`accept_met: true`): the rest wait for a newer one."""
    return frozenset(
        each["expr"]
        for each, raw in zip(authored(description), declared(description))
        if raw.get("accept_met") is True
    )
