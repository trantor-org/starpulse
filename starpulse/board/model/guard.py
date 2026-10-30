"""What a task write must pass before it lands: the declared `types`, the board's rules, then its `validate` hook.

The verdicts are pure policy; an adapter parses the file it is about to replace and writes the file only when
`Guard.refusal` returns None."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from starpulse.board.model import rules
from starpulse.board.model.seam import Written
from starpulse.machine_engine.model.transitions import lane_id

#: A task write's check: the file's path, its text before (None for a create) and the text about to be written; it
#: returns why the write is refused, or None to let it land.
Validate = Callable[[Path, "str | None", str], "str | None"]

#: The actor that moves a Waiting task to Ready once its dependencies are Done (`pulls.adapters.inbound.task_actor.ACTOR`).
_TASK_ACTOR = "starpulse/task-actor"


@dataclass(frozen=True)
class Guard:
    """What a task write must pass before it lands: the declared `types`, the board's rules, then its `validate` hook."""

    rules: tuple[rules.Rule, ...] = ()
    validate: Validate | None = None
    #: The state of another task (a dependency a rule reads), or None when the board has none.
    state_of: Callable[[str], str | None] = lambda _: None
    #: The names a task's `type` may take; empty accepts any.
    types: tuple[str, ...] = ()
    #: The Waiting lane id and the Ready status, which a write leaving a task in Waiting must be able to move on to.
    waiting: str | None = None
    ready: str = ""

    def standing(self, front: Mapping[str, Any], body: str, lane: str) -> dict[str, Any] | None:
        """The move update of the board rule that refuses moving the task to `lane`, or None when none does.

        It is the verdict as an actor no rule exempts meets it, with the verdict of each actor some rule exempts that
        differs, so a reader lifts the refusal for an actor the write lets through (`rules.standing_refusal`)."""

        def verdict(actor: str) -> dict[str, Any]:
            broken = rules.standing_refusal(self.rules, front, body, lane, actor)
            return {"allowed": True, "reason": "", "skill": ""} if broken is None else {
                "allowed": False,
                "reason": broken.explain(rules.Record(front, body)),
                "skill": broken.skill,
            }

        own = verdict("")
        if own["allowed"]:
            return None
        apart = {actor: verdict(actor) for actor in sorted({actor for rule in self.rules for actor in rule.exempt})}
        return {**own, "actors": {actor: found for actor, found in apart.items() if found != own}}

    def readable(self, front: Mapping[str, Any], body: str) -> str:
        """What the board's `readable` rules find broken in the description of the task, or "" when it reads well."""
        return rules.readable_verdict(self.rules, front, body)

    def refusal(
        self,
        path: Path,
        before: str | None,
        earlier: rules.Record | None,
        frontmatter: dict,
        body: str,
        text: str,
        actor: str,
    ) -> Written | None:
        """Why the write of `text` over `before` (None for a create; `earlier` is it parsed) by `actor` is refused, or
        None to let it land."""
        kind = str(frontmatter.get("type") or "")
        was = str(earlier.front.get("type") or "") if earlier else ""  # a write that leaves the type alone is not refused for it
        if self.types and kind and kind != was and kind not in self.types:
            return Written(False, f"type {kind!r} is not one of this board's types: {', '.join(self.types)}")
        if self.rules:
            after = rules.Record(frontmatter, body, self.state_of)
            if broken := rules.refusal(self.rules, earlier, after, actor):
                return Written(False, broken.explain(after), broken.skill, lint=True)
        staying = lane_id(str(frontmatter.get("status") or "")) == self.waiting
        if self.waiting and self.ready and staying and actor != _TASK_ACTOR:
            released = rules.standing_refusal(self.rules, frontmatter, body, self.ready, _TASK_ACTOR)
            if released:  # the task actor would never release it: a Waiting task nothing can ready is a stuck one
                return Written(False, released.explain(rules.Record(frontmatter, body)), released.skill, lint=True)
        if self.validate is not None and (reason := self.validate(path, before, text)):
            return Written(False, reason, lint=True)
        return None
