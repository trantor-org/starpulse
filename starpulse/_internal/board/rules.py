"""A board's rules: what a task must satisfy for a write to land.

`[board] rules` lists them. Each is `{on, require, reason}` (and optionally `skill` and `unless_actor`): `on` says
which writes it judges, `require` is one primitive the task as it will be after the write must satisfy, and `reason`
is the refusal every writer, the CLI's and the page's, answers with. A primitive is a one-key table naming its kind:
`{field: {...}}`, `{label: {...}}`, `{section: {...}}`, `{dependencies: {...}}` or `{checklist: {...}}`, or a
combinator, `all_of`, `any_of`, `exactly_one` and `none_of`, over a list of primitives. A write carries the actor that
makes it (`operator`, `agent`, or `<instance>/<workflow>` as a machine's `writers` spell it), which `unless_actor`
exempts.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from starpulse._internal.machines.transitions import lane_id

__all__ = ["Record", "Rule", "load", "refusal"]


@dataclass(frozen=True)
class Record:
    """A task as a write leaves it: its front matter and its Markdown body."""

    front: Mapping[str, Any]
    body: str = ""
    #: The state of another task, as `lane_id` spells it, or None when the board has no such task.
    state_of: Callable[[str], str | None] = lambda _: None

    @property
    def state(self) -> str:
        return lane_id(str(self.front.get("status") or "").strip())


#: A primitive: whether the record satisfies it.
Primitive = Callable[[Record], bool]
#: The `## <heading>` lines that bound a body's sections.
_HEADING = re.compile(r"^##[ \t]+(.*?)[ \t]*$", re.M)
#: The checklists a record keeps, by the name a rule gives them and the markers that bound them.
_CHECKLISTS = {"acceptance_criteria": "AC", "definition_of_done": "DOD"}
_UNCHECKED = re.compile(r"^- \[ \] #\d+ ", re.M)
_RULE_KEYS = {"on", "require", "reason", "skill", "unless_actor"}
_ON_KEYS = {"to", "from", "while", "write"}


@dataclass(frozen=True)
class Rule:
    """One rule of the set: the writes it judges, what the task must satisfy and what the refusal says.

    It judges every write (`always`), or a write that enters a state in `to` from one in `origin` (both empty
    matching any), and with `staying` also a write that leaves the task in a state of `to`. `exempt` are the actors
    it does not judge."""

    to: frozenset[str]
    origin: frozenset[str]
    require: Primitive
    reason: str
    skill: str = ""
    always: bool = False
    staying: bool = False
    exempt: frozenset[str] = frozenset()

    def judges(self, before: Record | None, after: Record, actor: str) -> bool:
        """Whether the write by `actor` that takes `before` (None for a create) to `after` is one this rule judges."""
        if actor in self.exempt:
            return False
        if self.always:
            return True
        if self.to and after.state not in self.to:
            return False
        if self.origin and (before is None or before.state not in self.origin):
            return False
        return self.staying or before is None or before.state != after.state


def _states(spec: object, where: str) -> frozenset[str]:
    names = [spec] if isinstance(spec, str) else spec
    if not isinstance(names, list) or not names or not all(isinstance(name, str) and name.strip() for name in names):
        raise ValueError(f"{where}: expected a state name or a list of them")
    return frozenset(lane_id(name.strip()) for name in names)


def _actors(spec: object, where: str) -> frozenset[str]:
    if not isinstance(spec, list) or not all(isinstance(actor, str) and actor.strip() for actor in spec):
        raise ValueError(f"{where}: expected a list of actors (`operator`, `agent`, `<instance>/<workflow>`)")
    return frozenset(actor.strip() for actor in spec)


def _values(value: object) -> list[str]:
    """The nonblank text of a scalar or list front matter value."""
    return [
        text
        for item in (value if isinstance(value, list) else [value])
        if item is not None and (text := str(item).strip())
    ]


def _unknown(spec: Mapping[str, Any], known: set[str], where: str, kind: str) -> None:
    if unknown := sorted(spec.keys() - known):
        raise ValueError(f"{where}: {kind} has no key {', '.join(unknown)}")


def _field(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"field", "matches", "in", "min"}, where, "field")
    name = spec.get("field")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{where}: field needs `field`, the front matter key it reads")
    if spec.keys() <= {"field"}:
        raise ValueError(f"{where}: field {name} needs `matches`, `in` or `min`")
    try:
        matches = re.compile(spec["matches"]) if "matches" in spec else None
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: field {name} `matches` is not a regular expression: {error}") from error
    allowed = {str(item) for item in spec["in"]} if isinstance(spec.get("in"), list) else None
    if "in" in spec and allowed is None:
        raise ValueError(f"{where}: field {name} `in` must be a list")
    minimum = spec.get("min", 1)
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
        raise ValueError(f"{where}: field {name} `min` must be a whole number")

    def holds(record: Record) -> bool:
        found = [
            item
            for item in _values(record.front.get(name))
            if (matches is None or matches.search(item)) and (allowed is None or item in allowed)
        ]
        return len(found) >= minimum

    return holds


def _label(spec: Mapping[str, Any], where: str) -> Primitive:
    if spec.keys() == {"contains"} and isinstance(spec["contains"], str) and spec["contains"]:
        wanted = spec["contains"]
        return lambda record: wanted in _values(record.front.get("labels"))
    if spec.keys() == {"prefix", "in"} and isinstance(spec["prefix"], str) and spec["prefix"]:
        if not isinstance(spec["in"], list) or not spec["in"]:
            raise ValueError(f"{where}: label `in` must be a list of the values a prefixed label may take")
        prefix, allowed = spec["prefix"], {str(value) for value in spec["in"]}

        def sized(record: Record) -> bool:
            found = [
                label.removeprefix(prefix) for label in _values(record.front.get("labels")) if label.startswith(prefix)
            ]
            return bool(found) and all(value in allowed for value in found)

        return sized
    raise ValueError(f"{where}: label is `contains: <label>`, or `prefix: <text>` with `in: [<values>]`")


def _under(body: str, heading: str) -> str | None:
    """The text under the body's `## <heading>` up to the next `##` heading, or None when it has no such section."""
    heads = list(_HEADING.finditer(body))
    for number, head in enumerate(heads):
        if head[1].casefold() == heading.casefold():
            end = heads[number + 1].start() if number + 1 < len(heads) else len(body)
            return body[head.end() : end].strip()
    return None


def _section(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"heading", "nonempty", "not_matching", "except_self"}, where, "section")
    heading = spec.get("heading")
    if not isinstance(heading, str) or not heading.strip():
        raise ValueError(f"{where}: section needs `heading`, the `## ` heading it reads")
    if spec.get("except_self") and "not_matching" not in spec:
        raise ValueError(f"{where}: section `except_self` needs `not_matching`")
    try:
        unwanted = re.compile(spec["not_matching"]) if "not_matching" in spec else None
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: section {heading} `not_matching` is not a regular expression: {error}") from error
    nonempty, except_self = bool(spec.get("nonempty")), bool(spec.get("except_self"))

    def holds(record: Record) -> bool:
        text = _under(record.body, heading.strip())
        if text is None and unwanted is None:
            return False
        if nonempty and not text:
            return False
        if unwanted is None:
            return True
        scanned, own = text or "", str(record.front.get("id") or "").strip()
        if except_self and own:
            scanned = re.sub(rf"(?<![\w-]){re.escape(own)}(?![\w-])", "", scanned, flags=re.I)
        return not unwanted.search(scanned)

    return holds


def _dependencies(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"all_in"}, where, "dependencies")
    states = _states(spec.get("all_in"), f"{where}.all_in")
    return lambda record: all(record.state_of(task) in states for task in _values(record.front.get("dependencies")))


def _checklist(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"sections", "all_checked"}, where, "checklist")
    names = spec.get("sections")
    if not isinstance(names, list) or not names or not all(isinstance(name, str) for name in names):
        raise ValueError(f"{where}: checklist `sections` is a list of: {', '.join(_CHECKLISTS)}")
    if missing := [name for name in names if name not in _CHECKLISTS]:
        raise ValueError(f"{where}: checklist has no section {', '.join(missing)}; known: {', '.join(_CHECKLISTS)}")
    if spec.get("all_checked") is not True:
        raise ValueError(f"{where}: checklist needs `all_checked: true`, the one thing it can require")
    regions = [
        re.compile(rf"<!-- {_CHECKLISTS[name]}:BEGIN -->(.*?)<!-- {_CHECKLISTS[name]}:END -->", re.S) for name in names
    ]

    def holds(record: Record) -> bool:
        return not any(
            (found := region.search(record.body)) and _UNCHECKED.search(found.group(1)) for region in regions
        )

    return holds


#: The combinators: how many of the nested primitives, of `total`, must hold.
_COMBINATORS: dict[str, Callable[[int, int], bool]] = {
    "all_of": lambda held, total: held == total,
    "any_of": lambda held, total: held >= 1,
    "exactly_one": lambda held, total: held == 1,
    "none_of": lambda held, total: held == 0,
}
_KINDS: dict[str, Callable[[Mapping[str, Any], str], Primitive]] = {
    "field": _field,
    "label": _label,
    "section": _section,
    "dependencies": _dependencies,
    "checklist": _checklist,
}
_NAMES = ", ".join([*_KINDS, *_COMBINATORS])


def _primitive(spec: object, where: str) -> Primitive:
    if not isinstance(spec, dict) or len(spec) != 1:
        raise ValueError(f"{where}: a primitive is one key naming its kind: {_NAMES}")
    ((kind, body),) = spec.items()
    here = f"{where}.{kind}"
    if kind in _COMBINATORS:
        if not isinstance(body, list) or not body:
            raise ValueError(f"{here}: {kind} takes a non-empty list of primitives")
        nested = [_primitive(item, f"{here}[{number}]") for number, item in enumerate(body)]
        judge = _COMBINATORS[kind]
        return lambda record: judge(sum(1 for primitive in nested if primitive(record)), len(nested))
    if kind not in _KINDS:
        raise ValueError(f"{where}: {kind!r} is no primitive; known: {_NAMES}")
    if not isinstance(body, dict):
        raise ValueError(f"{here}: {kind} takes a table")
    return _KINDS[kind](body, here)


def load(declared: object) -> tuple[Rule, ...]:
    """The rules a `[board] rules` setting declares, in order; a rule the board cannot read is a ValueError naming it."""
    if declared is None:
        return ()
    if not isinstance(declared, list):
        raise ValueError("board: rules must be a list of tables, `[[board.rules]]`")
    rules = []
    for number, spec in enumerate(declared):
        where = f"board: rules[{number}]"
        if not isinstance(spec, dict):
            raise ValueError(f"{where}: a rule is a table")
        if unknown := sorted(spec.keys() - _RULE_KEYS):
            raise ValueError(f"{where}: no key {', '.join(unknown)}; known: {', '.join(sorted(_RULE_KEYS))}")
        reason = spec.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"{where}: needs a `reason`, the refusal text both the CLI and the page show")
        on = spec.get("on")
        if not isinstance(on, dict) or on.get("write", False) not in (True, False) or on.keys() - _ON_KEYS:
            raise ValueError(f"{where}: `on` takes `to`, `from` and `while`, or `write`")
        if bool(on.get("write")) == bool(on.keys() & {"to", "from"}) or ("while" in on and "to" not in on):
            raise ValueError(f"{where}: `on` is `write = true` alone, or `to` and/or `from` (`while` with `to`)")
        if "while" in on and not isinstance(on["while"], bool):
            raise ValueError(f"{where}: `on.while` must be true or false")
        rules.append(
            Rule(
                to=_states(on["to"], f"{where}.on.to") if "to" in on else frozenset(),
                origin=_states(on["from"], f"{where}.on.from") if "from" in on else frozenset(),
                require=_primitive(spec.get("require"), f"{where}.require"),
                reason=reason.strip(),
                skill=str(spec.get("skill", "")),
                always=bool(on.get("write")),
                staying=bool(on.get("while")),
                exempt=_actors(spec.get("unless_actor", []), f"{where}.unless_actor"),
            )
        )
    return tuple(rules)


def refusal(rules: tuple[Rule, ...], before: Record | None, after: Record, actor: str) -> Rule | None:
    """The first rule the write by `actor` from `before` (None for a create) to `after` breaks, or None for none."""
    return next((rule for rule in rules if rule.judges(before, after, actor) and not rule.require(after)), None)
