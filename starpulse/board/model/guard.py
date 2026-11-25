"""What a task write must pass before it lands: the declared `types`, the board's rules, then its `validate` hook.

The verdicts are pure policy; an adapter parses the file it is about to replace and writes the file only when
`Guard.refusal` returns None."""

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from starpulse.board.model import entry, rules
from starpulse.board.model.seam import TASK_ACTOR, Written
from starpulse.machine_engine.model.transitions import lane_id

#: A task write's check: the file's path, its text before (None for a create) and the text about to be written; it
#: returns why the write is refused, or None to let it land.
Validate = Callable[[Path, "str | None", str], "str | None"]


@dataclass(frozen=True)
class Guard:
    """What a task write must pass before it lands: the declared `types`, the board's rules, then its `validate` hook."""

    rules: tuple[rules.Rule, ...] = ()
    validate: Validate | None = None
    #: The state of another task (a dependency a rule reads), or None when the board has none.
    state_of: Callable[[str], str | None] = lambda _: None
    #: The stored pull request of `(repository, number)` (`rules.Record.pull_of`), or None when the board has none.
    pull_of: Callable[[str, int, str | None], Mapping[str, Any] | None] = lambda _repo, _number, _settle: None
    #: The names a task's `type` may take; empty accepts any.
    types: tuple[str, ...] = ()
    #: The Waiting lane id and the Ready status, which a write leaving a task in Waiting must be able to move on to.
    waiting: str | None = None
    ready: str = ""
    #: The ids of the open tasks whose field holds a value (a `unique` rule reads it), none when the board has no tasks.
    holders: Callable[[str, str], list[str]] = lambda _field, _value: []
    #: The `dependencies` of the tasks named by ids of any case (`rules.Record.dependencies_of`), none when the board has no tasks.
    dependencies_of: Callable[[Collection[str]], Mapping[str, Sequence[str]]] = lambda _ids: {}
    #: The board's `default_profiles` (`rules.Record.matrix`).
    matrix: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    #: The lenses whose verdict a task's latest qa round recorded (`rules.Record.qa_lenses`), none when the board has no store.
    qa_lenses: Callable[[str], frozenset[str]] = lambda _task: frozenset()
    #: What entering a lane does to the task, whichever writer moves it (`[[board.entry]]`).
    effects: tuple[entry.Effect, ...] = ()
    #: The actors a lane rule they break warns instead of refusing (`warn_actors`); the rules that judge every write still refuse them.
    warn_actors: frozenset[str] = frozenset()

    def entered(self, front: Mapping[str, Any], earlier: Mapping[str, Any] | None) -> Mapping[str, Any]:
        """`front` once the effects of the lane it enters have run, whichever writer made the move."""
        return entry.entered(self.effects, front, earlier)

    def standing(self, front: Mapping[str, Any], body: str, lane: str) -> dict[str, Any] | None:
        """The move update of the board rule that refuses moving the task to `lane`, or None when none does.

        It is the verdict as an actor no rule exempts meets it, with the verdict of each actor some rule exempts or a
        warn actor that differs, so a reader lifts the refusal for an actor the write lets through
        (`rules.standing_verdict`). A warn actor's verdict lists every lane rule it is warned of."""

        def verdict(actor: str) -> dict[str, Any]:
            judged = rules.standing_verdict(
                self.rules, front, body, lane, actor, lambda moved: self.entered(moved, front), self.warn_actors
            )
            record = rules.Record(front, body)
            broken = judged.refused
            found: dict[str, Any] = {
                "allowed": broken is None,
                "reason": "" if broken is None else broken.explain(record),
                "skill": "" if broken is None else broken.skill,
            }
            if judged.warned:
                found["warnings"] = [{"reason": rule.explain(record), "skill": rule.skill} for rule in judged.warned]
            return found

        own = verdict("")
        if own["allowed"]:
            return None
        named = {actor for rule in self.rules for actor in rule.exempt} | self.warn_actors
        apart = {actor: verdict(actor) for actor in sorted(named)}
        return {**own, "actors": {actor: found for actor, found in apart.items() if found != own}}

    def readable(self, front: Mapping[str, Any], body: str) -> str:
        """What the board's `readable` rules find broken in the description of the task, or "" when it reads well."""
        return rules.readable_verdict(self.rules, front, body)

    @staticmethod
    def frozen_refusal(earlier: rules.Record | None, frontmatter: Mapping[str, Any], actor: str) -> str | None:
        """Why a freeze refuses the write, or None. A frozen task keeps its lane against every actor and audit, and only the
        task actor writes `frozen`: the refusal names who froze it and why."""
        was = dict(earlier.front.get("frozen") or {}) if earlier else {}
        task = str(frontmatter.get("id") or "")
        if dict(frontmatter.get("frozen") or {}) != was and actor != TASK_ACTOR:
            return f"{task}: only the task actor writes `frozen`; record `backlog-task freeze` or `unfreeze` and it carries it out."
        if was and earlier and lane_id(str(earlier.front.get("status") or "")) != lane_id(
            str(frontmatter.get("status") or "")
        ):
            return f"{task} is frozen by {was.get('by', '')}: {was.get('reason', '')}. Request an unfreeze first."
        return None

    def verdict(
        self,
        path: Path,
        before: str | None,
        earlier: rules.Record | None,
        frontmatter: dict,
        body: str,
        text: str,
        actor: str,
        *,
        audit: bool = False,
    ) -> Written:
        """The verdict on the write of `text` over `before` (None for a create; `earlier` is it parsed) by `actor`: a
        refusal with its reason and skill, else a landing that carries the reasons of the lane rules an operator's move
        broke. Every writer is judged here, after the entry effects of the lane it enters have run, except that the
        task actor meets no rule: it reads them as facts first (`audit` judges its write by them, to be read, never landed)."""
        if refusal := self.frozen_refusal(earlier, frontmatter, actor):
            return Written(False, refusal)
        kind = str(frontmatter.get("type") or "")
        was = str(earlier.front.get("type") or "") if earlier else ""  # a write that leaves the type alone is not refused for it
        reasons: list[str] = []
        if self.types and kind and kind != was and kind not in self.types:
            reasons.append(f"type {kind!r} is not one of this board's types: {', '.join(self.types)}")
            if earlier is not None:
                return Written(False, reasons[0])
        warnings: tuple[str, ...] = ()
        if self.rules and (audit or actor != TASK_ACTOR):
            after = rules.Record(
                frontmatter,
                body,
                self.state_of,
                pull_of=self.pull_of,
                holders=self.holders,
                dependencies_of=self.dependencies_of,
                matrix=self.matrix,
                qa_lenses=self.qa_lenses,
            )
            verdict = rules.evaluate(self.rules, earlier, after, actor, self.warn_actors)
            if verdict.refused:
                found = (verdict.refused, *verdict.also) if earlier is None else (verdict.refused,)
                reasons.extend(rule.explain(after) for rule in found)
                return Written(False, "\n".join(reasons), verdict.refused.skill, lint=True, rule=verdict.refused.key)
            warnings = tuple(rule.explain(after) for rule in verdict.warned)
        if reasons:
            return Written(False, reasons[0])
        staying = lane_id(str(frontmatter.get("status") or "")) == self.waiting
        if self.waiting and self.ready and staying and actor != TASK_ACTOR:
            released = rules.standing_refusal(
                self.rules, frontmatter, body, self.ready, TASK_ACTOR, lambda moved: self.entered(moved, frontmatter)
            )
            if released:  # the task actor would never release it: a Waiting task nothing can ready is a stuck one
                return Written(
                    False,
                    released.explain(rules.Record(frontmatter, body)),
                    released.skill,
                    lint=True,
                    rule=released.key,
                )
        if self.validate is not None and (reason := self.validate(path, before, text)):
            return Written(False, reason, lint=True)
        return Written(True, warnings=warnings)
