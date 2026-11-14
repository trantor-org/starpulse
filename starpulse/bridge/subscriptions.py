"""What a session subscribes to: the subjects of its JetStream consumer, each kept under the origin that gave it."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from itertools import zip_longest
from string import Formatter
from typing import Any

from starpulse.bridge.subjects import token

EXPLICIT = "explicit"

#: The values a rule may name, by the event that fires it.
CLAIM_VALUES = frozenset({"task"})
PR_OPENED_VALUES = frozenset({"task", "pr"})

_SUBJECT = re.compile(r"(?:[A-Za-z0-9_-]+|\*)(?:\.(?:[A-Za-z0-9_-]+|\*))*(?:\.>)?|>")


def overlaps(a: str, b: str) -> bool:
    """Whether one message subject can match both `a` and `b`; NATS refuses a consumer whose filters do."""
    for x, y in zip_longest(a.split("."), b.split(".")):
        if x == ">" or y == ">":
            return x is not None and y is not None
        if x is None or y is None:
            return False
        if x != y and "*" not in (x, y):
            return False
    return True


def covers(wide: str, narrow: str) -> bool:
    """Whether every message subject `narrow` matches is also matched by `wide`."""
    for x, y in zip_longest(wide.split("."), narrow.split(".")):
        if x == ">":
            return y is not None
        if x is None or y is None or y == ">" or (x != y and x != "*"):
            return False
    return True


@dataclass(frozen=True)
class Rules:
    claim: tuple[str, ...] = ()
    pr_opened: tuple[str, ...] = ()


@dataclass
class Subscription:
    origins: dict[str, set[str]] = field(default_factory=dict)

    @property
    def filters(self) -> list[str]:
        held = set().union(*self.origins.values())
        return sorted(subject for subject in held if not any(other != subject and covers(other, subject) for other in held))

    def add(self, origin: str, subjects: list[str]) -> bool:
        """Add `subjects` under `origin`, replacing each subject it held that overlaps one added; whether that changed."""
        held = self.origins.get(origin, set())
        grown = {kept for kept in held if not any(overlaps(kept, new) for new in subjects)} | set(subjects)
        if grown != held:
            self.origins[origin] = grown
        return grown != held

    def drop(self, origin: str) -> bool:
        return self.origins.pop(origin, None) is not None

    def remove(self, subject: str) -> bool:
        """Remove `subject` from every origin that holds it."""
        holders = [origin for origin, subjects in self.origins.items() if subject in subjects]
        for origin in holders:
            self.origins[origin].discard(subject)
            if not self.origins[origin]:
                del self.origins[origin]
        return bool(holders)

    def dumps(self) -> str:
        return json.dumps({origin: sorted(subjects) for origin, subjects in sorted(self.origins.items())}, separators=(",", ":"))

    @classmethod
    def loads(cls, text: str) -> Subscription:
        return cls({origin: set(subjects) for origin, subjects in json.loads(text or "{}").items()})


def expand(board: str, templates: tuple[str, ...], **values: str) -> list[str]:
    """The full subjects of `templates` on `board`, each value as one token so it cannot widen the subject."""
    safe = {name: token(value) for name, value in values.items()}
    return [f"starpulse.{board}.{template.format(**safe)}" for template in templates]


def explicit_subject(board: str, subject: str) -> str:
    """`subject` when it is a subject of `board`'s stream, else `ValueError`."""
    prefix = f"starpulse.{board}."
    relative = subject.removeprefix(prefix)
    if relative == subject or not _SUBJECT.fullmatch(relative):
        raise ValueError(f"{subject!r} is not a subject of the {board} board; it starts {prefix} (`{prefix}task.TASK-1.>`)")
    return subject


def _checked(kind: str, event: str, templates: Any, known: frozenset[str]) -> tuple[str, ...]:
    for template in templates:
        names = {name for _, name, _, _ in Formatter().parse(str(template)) if name}
        if not names <= known:
            raise ValueError(f"{kind}.{event} {template!r} names {sorted(names - known)}; this event knows {sorted(known)}")
        try:
            subject = str(template).format(**dict.fromkeys(known, "x"))
        except (IndexError, ValueError):
            subject = ""
        if not _SUBJECT.fullmatch(subject) or subject.split(".")[0] == "starpulse":
            raise ValueError(f"{kind}.{event} {template!r} is not a subject relative to the board, such as `task.{{task}}.>`")
    return tuple(templates)


def parse_rules(table: dict[str, Any]) -> dict[str, Rules]:
    """The rules of each task kind from the `[bridge.subscriptions.<kind>]` tables; a rule that names an unknown value or
    is not a subject raises `ValueError`."""
    rules = {}
    for kind, tables in table.items():
        rules[kind] = Rules(
            claim=_checked(kind, "claim", tables.get("claim", ()), CLAIM_VALUES),
            pr_opened=_checked(kind, "pr_opened", tables.get("pr_opened", ()), PR_OPENED_VALUES),
        )
    return rules
