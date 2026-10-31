"""A board's rules: what a task must satisfy for a write to land.

`[board] guards` lists them. Each is `{on, require, reason}` (and optionally `skill` and `unless_actor`): `on` says
which writes it judges, `require` is one primitive the task as it will be after the write must satisfy, and `reason`
is the refusal every writer, the CLI's and the page's, answers with. A primitive is a one-key table naming its kind:
`{field: {...}}`, `{label: {...}}`, `{section: {...}}`, `{body: {...}}`, `{block: {...}}`,
`{post_merge_checks: {}}`, `{dependencies: {...}}`, `{checklist: {...}}` or `{readable: {...}}`, or a
combinator, `all_of`, `any_of`, `exactly_one` and `none_of`, over a list of primitives; `{before: <primitive>}` reads
the task as it was before the write (a create had none, so it holds). A write carries the actor that makes it
(`operator`, `agent`, or `<instance>/<workflow>` as a machine's `writers` spell it), which `unless_actor` exempts.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

from starpulse.board.model import post_merge_checks, readable
from starpulse.board.model.sections import fenced_list, under
from starpulse.machine_engine.model.transitions import lane_id

__all__ = ["Record", "Rule", "load", "readable_verdict", "refusal", "standing_refusal"]


@dataclass(frozen=True)
class Record:
    """A task as a write leaves it: its front matter and its Markdown body."""

    front: Mapping[str, Any]
    body: str = ""
    #: The state of another task, as `lane_id` spells it, or None when the board has no such task.
    state_of: Callable[[str], str | None] = lambda _: None
    #: The task as it was before the write, None for a create; the `before` primitive reads it.
    earlier: Record | None = None

    @property
    def state(self) -> str:
        return lane_id(str(self.front.get("status") or "").strip())


#: A primitive: whether the record satisfies it.
Primitive = Callable[[Record], bool]
#: The regions of a body a rule can read, by the name a rule gives them and the markers that bound them.
_REGIONS = {
    "description": "SECTION:DESCRIPTION",
    "plan": "SECTION:PLAN",
    "acceptance_criteria": "AC",
    "definition_of_done": "DOD",
}
#: The regions that hold a checklist.
_CHECKLISTS = ("acceptance_criteria", "definition_of_done")
_UNCHECKED = re.compile(r"^- \[ \] #\d+ ", re.M)
_ITEM = re.compile(r"^- \[[ xX]\]", re.M)
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

    def explain(self, record: Record) -> str:
        """The refusal text for `record`: the reason, then what a `readable` requirement found broken, when it is one."""
        found = _found(self.require, record)
        return f"{self.reason}: {found}" if found else self.reason


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
    if spec.keys() == {"starts_with"} and isinstance(spec["starts_with"], str) and spec["starts_with"]:
        start = spec["starts_with"]
        return lambda record: any(label.startswith(start) for label in _values(record.front.get("labels")))
    raise ValueError(
        f"{where}: label is `contains: <label>`, `starts_with: <text>`, or `prefix: <text>` with `in: [<values>]`"
    )


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
        text = under(record.body, heading.strip())
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


def _region(name: str) -> re.Pattern[str]:
    marker = _REGIONS[name]
    return re.compile(rf"<!-- {marker}:BEGIN -->(.*?)<!-- {marker}:END -->", re.S)


def _body(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"region", "matches"}, where, "body")
    region = spec.get("region")
    if region is not None and region not in _REGIONS:
        raise ValueError(f"{where}: body has no region {region}; known: {', '.join(_REGIONS)}")
    try:
        wanted = re.compile(spec["matches"])
    except KeyError as error:
        raise ValueError(f"{where}: body needs `matches`, the regular expression it searches for") from error
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: body `matches` is not a regular expression: {error}") from error
    bounds = _region(region) if region else None

    def holds(record: Record) -> bool:
        found = bounds.search(record.body) if bounds else None
        return bool(wanted.search(found.group(1) if found else "" if bounds else record.body))

    return holds


def _block(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"heading", "key"}, where, "block")
    heading, key = spec.get("heading"), spec.get("key")
    if not isinstance(heading, str) or not heading.strip():
        raise ValueError(f"{where}: block needs `heading`, the `## ` heading whose fenced YAML it reads")
    if not isinstance(key, str) or not key.strip():
        raise ValueError(f"{where}: block needs `key`, the YAML key that holds the list")

    def holds(record: Record) -> bool:
        try:
            return bool(fenced_list(record.body, heading.strip(), key))
        except ValueError:
            return False

    return holds


def _post_merge_checks(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, set(), where, "post_merge_checks")

    def holds(record: Record) -> bool:
        try:
            post_merge_checks.parse(record.body)
        except ValueError:
            return False
        return True

    return holds


def _dependencies(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"all_in"}, where, "dependencies")
    states = _states(spec.get("all_in"), f"{where}.all_in")
    return lambda record: all(record.state_of(task) in states for task in _values(record.front.get("dependencies")))


def _checklist(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"sections", "all_checked", "min_items"}, where, "checklist")
    names = spec.get("sections")
    if not isinstance(names, list) or not names or not all(isinstance(name, str) for name in names):
        raise ValueError(f"{where}: checklist `sections` is a list of: {', '.join(_CHECKLISTS)}")
    if missing := [name for name in names if name not in _CHECKLISTS]:
        raise ValueError(f"{where}: checklist has no section {', '.join(missing)}; known: {', '.join(_CHECKLISTS)}")
    minimum = spec.get("min_items")
    if "all_checked" in spec and spec["all_checked"] is not True:
        raise ValueError(f"{where}: checklist `all_checked` can only be `true`")
    if minimum is None and "all_checked" not in spec:
        raise ValueError(f"{where}: checklist needs `all_checked: true` or `min_items`, what it can require")
    if minimum is not None and (not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1):
        raise ValueError(f"{where}: checklist `min_items` must be a whole number of at least 1")
    regions = [_region(name) for name in names]

    def holds(record: Record) -> bool:
        lists = [found.group(1) for region in regions if (found := region.search(record.body))]
        return (not spec.get("all_checked") or not any(_UNCHECKED.search(text) for text in lists)) and (
            minimum is None or sum(len(_ITEM.findall(text)) for text in lists) >= minimum
        )

    return holds


def _found(primitive: Primitive, record: Record) -> str:
    """What a `readable` primitive finds broken in `record`, "" for any other primitive or a description that reads well."""
    return primitive.broken(record) if isinstance(primitive, _Readable) else ""


class _Readable:
    """A `readable` primitive: holds when the description reads well, and `broken` says what it found otherwise."""

    def __init__(self, template: readable.Template) -> None:
        self._template = template

    def _judged(self, record: Record) -> str:
        return readable.judged(self._template, record.body)

    def broken(self, record: Record) -> str:
        return readable.broken(self._template, record.body)

    def __call__(self, record: Record) -> bool:
        """Holds for a description the write left as it was: the rules judge a create and an edit, not an older text."""
        if record.earlier is not None and self._judged(record.earlier) == self._judged(record):
            return True
        return not self.broken(record)


def _readable(spec: Mapping[str, Any], where: str) -> Primitive:
    return _Readable(readable.parse(spec, where))


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
    "body": _body,
    "block": _block,
    "post_merge_checks": _post_merge_checks,
    "dependencies": _dependencies,
    "checklist": _checklist,
    "readable": _readable,
}
_NAMES = ", ".join([*_KINDS, "before", *_COMBINATORS])


def _primitive(spec: object, where: str) -> Primitive:
    if not isinstance(spec, dict) or len(spec) != 1:
        raise ValueError(f"{where}: a primitive is one key naming its kind: {_NAMES}")
    ((kind, body),) = spec.items()
    here = f"{where}.{kind}"
    if kind == "before":
        earlier = _primitive(body, here)
        return lambda record: record.earlier is None or earlier(record.earlier)
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
    """The rules a `[board] guards` setting declares, in order; a rule the board cannot read is a ValueError naming it."""
    if declared is None:
        return ()
    if not isinstance(declared, list):
        raise ValueError("board: guards must be a list of tables, `[[board.guards]]`")
    rules = []
    for number, spec in enumerate(declared):
        where = f"board: guards[{number}]"
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
    after = replace(after, earlier=before)
    return next((rule for rule in rules if rule.judges(before, after, actor) and not rule.require(after)), None)


def standing_refusal(
    rules: tuple[Rule, ...], front: Mapping[str, Any], body: str, lane: str, actor: str = ""
) -> Rule | None:
    """The first rule that refuses moving the task to `lane` by `actor` whatever other tasks hold, or None.

    A rule that reads another task's state can change its verdict without the task's file changing; the write still
    enforces it, but a standing verdict recorded with the task leaves it out."""
    read: list[str] = []

    def unread(task: str) -> None:
        read.append(task)

    before = Record(front, body, unread)
    after = Record({**front, "status": lane}, body, unread, before)
    for rule in rules:
        read.clear()
        if rule.judges(before, after, actor) and not rule.require(after) and not read:
            return rule
    return None


def readable_verdict(rules: tuple[Rule, ...], front: Mapping[str, Any], body: str) -> str:
    """What the first `readable` rule finds broken in the description of `body`, or "" when each reads well.

    It judges the description, not a write, so no actor exempts it and a state a rule names does not narrow it."""
    record = Record(front, body)
    return next((found for rule in rules if (found := _found(rule.require, record))), "")
