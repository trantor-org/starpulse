"""A board's rules: what a task must satisfy for a write to land.

`[board] guards` lists them. Each is `{on, require, reason}` (and optionally `skill` and `unless_actor`): `on` says
which writes it judges, `require` is one primitive the task as it will be after the write must satisfy, and `reason`
is the refusal every writer, the CLI's and the page's, answers with. A primitive is a one-key table naming its kind:
`{field: {...}}`, `{label: {...}}`, `{section: {...}}`, `{body: {...}}`, `{block: {...}}`,
`{post_merge_checks: {}}`, `{dependencies: {...}}`, `{checklist: {...}}`, `{readable: {...}}`, `{unique: {...}}`,
`{acyclic: {...}}`, `{names_ids: {...}}`, `{retained: {...}}`, `{no_implied_dependency: {}}`, `{pull_proof: {...}}`,
`{matrix_profile: {}}`, `{pulls_ready: {}}`, `{pulls_failing: {}}`, `{pulls_clear: {}}` or `{pulls_changed: {...}}` (these four read the stored pull requests the task's
`references` cite, never GitHub), or a combinator, `all_of`, `any_of`, `exactly_one` and `none_of`, over a list of primitives; `{before: <primitive>}` reads
the task as it was before the write (a create had none, so it holds). A write carries the actor that makes it
(`operator`, `agent`, or `<instance>/<workflow>` as a machine's `writers` spell it), which `unless_actor` exempts.

`evaluate` is the one verdict on a write, `{refused, warned}`: the first broken rule refuses it, except that the rules
of a lane move (`to`, `from`) an actor in `warned_actors` breaks are returned in `warned` and the write lands.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from fnmatch import fnmatchcase
from functools import lru_cache
from typing import Any, NamedTuple

from starpulse.board.model import entry, post_merge_checks, readable
from starpulse.board.model.sections import fenced_list, under
from starpulse.machine_engine.model.transitions import lane_id

__all__ = ["Record", "Rule", "Verdict", "evaluate", "load", "readable_verdict", "refusal", "standing_refusal"]


@dataclass(frozen=True)
class Record:
    """A task as a write leaves it: its front matter and its Markdown body."""

    front: Mapping[str, Any]
    body: str = ""
    #: The state of another task, as `lane_id` spells it, or None when the board has no such task.
    state_of: Callable[[str], str | None] = lambda _: None
    #: The task as it was before the write, None for a create; the `before` primitive reads it.
    earlier: Record | None = None
    #: The stored pull request `(repository, number)` as `{draft, checks, body, files}`, or None when the store holds
    #: none (`files` is None for a record saved before the store kept them); the `pulls_*` primitives read it.
    pull_of: Callable[[str, int, bool], Mapping[str, Any] | None] = lambda _repo, _number, _settle: None
    #: The ids of the open tasks whose front matter field (first argument) holds a value (second), none for a board with no tasks.
    holders: Callable[[str, str], list[str]] = lambda _field, _value: []
    #: Every task's `dependencies` by id, read when asked; the `no_implied_dependency` primitive walks it.
    graph: Callable[[], Mapping[str, Sequence[str]]] = lambda: {}
    #: The board's `default_profiles` (kind, then size, to a profile); the `matrix_profile` primitive reads it.
    matrix: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

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
    "comments": "COMMENTS",
    "final_summary": "SECTION:FINAL_SUMMARY",
}
#: The regions that hold a checklist.
_CHECKLISTS = ("acceptance_criteria", "definition_of_done")
_UNCHECKED = re.compile(r"^- \[ \] #\d+ ", re.M)
_ITEM = re.compile(r"^- \[[ xX]\]", re.M)
_CHECKED = re.compile(r"^- \[[xX]\] .*$", re.M)
_PULL_URL = re.compile(r"https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)/?")
_RULE_KEYS = {"on", "require", "reason", "skill", "unless_actor"}
_ON_KEYS = {"to", "from", "while", "write", "create"}


@dataclass(frozen=True)
class Rule:
    """One rule of the set: the writes it judges, what the task must satisfy and what the refusal says.

    It judges every write (`always`), or a write that enters a state in `to` from one in `origin` (both empty
    matching any), and with `staying` also a write that leaves the task in a state of `to`, or only a create
    (`created`). `exempt` are the actors it does not judge."""

    to: frozenset[str]
    origin: frozenset[str]
    require: Primitive
    reason: str
    skill: str = ""
    always: bool = False
    staying: bool = False
    created: bool = False
    exempt: frozenset[str] = frozenset()

    def judges(self, before: Record | None, after: Record, actor: str) -> bool:
        """Whether the write by `actor` that takes `before` (None for a create) to `after` is one this rule judges."""
        if actor in self.exempt:
            return False
        if self.always:
            return True
        if self.created:
            return before is None
        if self.to and after.state not in self.to:
            return False
        if self.origin and (before is None or before.state not in self.origin):
            return False
        return self.staying or before is None or before.state != after.state

    @property
    def moves(self) -> bool:
        """Whether the rule judges a move between lanes, its entry or its exit, and no write that holds in every lane."""
        return not (self.always or self.created or self.staying)

    def explain(self, record: Record) -> str:
        """The refusal text for `record`: the reason, then what a `readable` or `names_ids` requirement found broken."""
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


def _unique(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"field"}, where, "unique")
    name = spec.get("field")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{where}: unique needs `field`, the front matter key whose value no other open task may hold")

    def holds(record: Record) -> bool:
        own = str(record.front.get("id") or "").strip().casefold()
        return not any(
            task.casefold() != own for value in _values(record.front.get(name)) for task in record.holders(name, value)
        )

    return holds


def _acyclic(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"field", "self_only"}, where, "acyclic")
    name = spec.get("field")
    if not isinstance(name, str) or not name:
        raise ValueError(f"{where}: acyclic needs `field`, the front matter key whose values are task ids")

    def holds(record: Record) -> bool:
        own = str(record.front.get("id") or "").strip()
        held = {value.casefold() for value in _values(record.front.get(name))}
        if own.casefold() in held or spec.get("self_only"):
            return own.casefold() not in held
        kept = record.earlier and {value.casefold() for value in _values(record.earlier.front.get(name))}
        if not held or (kept and held <= kept):
            return True  # only an added value can close a loop; an older one is not this write's
        seen, frontier = {own.casefold()}, [own]
        while frontier:
            frontier = [
                task
                for value in frontier
                for task in record.holders(name, value)
                if task.casefold() not in seen
            ]
            seen.update(task.casefold() for task in frontier)
        return not held & seen

    return holds


def _unchanged(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"field", "region", "ignoring"}, where, "unchanged")
    name, region = spec.get("field"), spec.get("region")
    if (name is None) == (region is None):
        raise ValueError(f"{where}: unchanged needs one of `field` (a front matter key) or `region`")
    if region is not None and region not in _REGIONS:
        raise ValueError(f"{where}: unchanged has no region {region}; known: {', '.join(_REGIONS)}")
    try:
        ignored = re.compile(spec.get("ignoring") or "(?!)")
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: unchanged `ignoring` is not a regular expression: {error}") from error
    bounds = _region(region) if region else None

    def read(record: Record) -> object:
        if bounds is None:
            return record.front.get(name)
        found = bounds.search(record.body)
        return ignored.sub("", found.group(1)) if found else ""

    return lambda record: record.earlier is not None and read(record) == read(record.earlier)


def _no_more(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"region", "matches"}, where, "no_more")
    region, pattern = spec.get("region"), spec.get("matches")
    if region not in _REGIONS:
        raise ValueError(f"{where}: no_more needs a `region`; known: {', '.join(_REGIONS)}")
    try:
        found = re.compile(pattern)
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: no_more `matches` is not a regular expression: {error}") from error
    bounds = _region(region)

    def count(record: Record) -> int:
        inside = bounds.search(record.body)
        return len(found.findall(inside.group(1))) if inside else 0

    return lambda record: record.earlier is not None and count(record) <= count(record.earlier)


def _names_ids(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"from", "matches", "in", "named"}, where, "names_ids")
    pattern = spec.get("matches")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError(f"{where}: names_ids needs `matches`, the pattern that finds an ID")
    source, target = spec.get("from"), spec.get("in")
    if not (isinstance(source, str) and source and isinstance(target, str) and target):
        raise ValueError(f"{where}: names_ids needs `from` and `in`, the front matter keys that list and name the IDs")
    try:
        listed, named = re.compile(pattern), re.compile(spec.get("named", pattern))
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: names_ids `matches` or `named` is not a regular expression: {error}") from error
    return _NamesIds(source, listed, target, named)


class _NamesIds:
    """A `names_ids` primitive: holds when `in` names each ID `from` lists, and `broken` names the ones it leaves out."""

    def __init__(self, source: str, listed: re.Pattern[str], target: str, named: re.Pattern[str]) -> None:
        self._source, self._listed, self._target, self._named = source, listed, target, named

    @staticmethod
    def _ids(record: Record, name: str, found: re.Pattern[str]) -> dict[str, str]:
        return {match.group(0).casefold(): match.group(0) for value in _values(record.front.get(name)) for match in found.finditer(value)}

    def _missing(self, record: Record) -> list[str]:
        named = self._ids(record, self._target, self._named)
        return [text for key, text in self._ids(record, self._source, self._listed).items() if key not in named]

    def broken(self, record: Record) -> str:
        """The listed IDs the record leaves unnamed, "" when it names each."""
        missing = self._missing(record)
        return f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not named" if missing else ""

    def __call__(self, record: Record) -> bool:
        return not self._missing(record)


def _retained(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"region", "matches"}, where, "retained")
    region, pattern = spec.get("region"), spec.get("matches")
    if region not in _REGIONS:
        raise ValueError(f"{where}: retained needs a `region`, not {region}; known: {', '.join(_REGIONS)}")
    try:
        found = re.compile(pattern)
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: retained `matches` is not a regular expression: {error}") from error
    bounds = _region(region)

    def lines(record: Record) -> Counter[str]:
        inside = bounds.search(record.body)
        return Counter(line for line in (inside.group(1) if inside else "").splitlines() if found.search(line))

    return lambda record: record.earlier is None or not lines(record.earlier) - lines(record)


def _node(value: str) -> str:
    """The task id a `dependencies` value names: `TASK-5#2` depends on `TASK-5`."""
    return value.partition("#")[0].strip().casefold()


def _reaches(graph: Mapping[str, list[str]], start: str, goal: str) -> bool:
    seen, frontier = {start}, [start]
    while frontier:
        frontier = list({task for node in frontier for task in graph.get(node, ()) if task not in seen})
        seen.update(frontier)
    return goal in seen


def _no_implied_dependency(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, set(), where, "no_implied_dependency")

    def holds(record: Record) -> bool:
        held = [_node(value) for value in _values(record.front.get("dependencies"))]
        kept = {_node(value) for value in _values(record.earlier.front.get("dependencies"))} if record.earlier else set()
        added = [task for task in held if task not in kept]  # only an added edge is this write's to judge
        if not added:
            return True
        graph = {_node(task): [_node(value) for value in values] for task, values in record.graph().items()}
        return not any(_reaches(graph, via, target) for target in added for via in held if via != target)

    return holds


def _pull_proof(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"region", "matches"}, where, "pull_proof")
    region = spec.get("region", "comments")
    if region not in _REGIONS:
        raise ValueError(f"{where}: pull_proof has no region {region}; known: {', '.join(_REGIONS)}")
    try:
        selects = re.compile(spec["matches"])
    except KeyError as error:
        raise ValueError(f"{where}: pull_proof needs `matches`, the pattern that selects a proof line") from error
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: pull_proof `matches` is not a regular expression: {error}") from error
    bounds = _region(region)

    def named(line: str, repo: str, number: str, alone: bool) -> bool:
        owner, _, name = repo.partition("/")
        spelled = [rf"github\.com/{re.escape(repo)}/pull/{number}(?!\d)", rf"(?<![\w/#-])(?:{re.escape(owner)}/)?{re.escape(name)}#{number}(?!\d)"]
        if alone:  # a bare number names the one pull request that holds it
            spelled.append(rf"(?<![\w/#-])#{number}(?!\d)")
        return any(re.search(text, line, re.I) for text in spelled)

    def holds(record: Record) -> bool:
        links = [link for url in _values(record.front.get("references")) if (link := _PULL_URL.fullmatch(url))]
        inside = bounds.search(record.body)
        proof = [line for line in (inside.group(1) if inside else "").splitlines() if selects.search(line)]
        return all(
            any(named(line, link[1], link[2], alone=all(other[1] == link[1] for other in links if other[2] == link[2])) for line in proof)
            for link in links
        )

    return holds


def _matrix_profile(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, set(), where, "matrix_profile")

    def holds(record: Record) -> bool:
        cell = entry.default_profile(_values(record.front.get("labels")), record.matrix)
        return cell is None or _values(record.front.get("profile")) == [cell]

    return holds


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


def _pulls(record: Record, settle: bool = False) -> list[Mapping[str, Any] | None]:
    """The stored pull request of each URL in the task's `references`, None for one the store does not hold; `settle`
    asks the lookup to correct a stored `mergeable` from GitHub."""
    links = [_PULL_URL.fullmatch(url) for url in _values(record.front.get("references"))]
    return [record.pull_of(link[1], int(link[2]), settle) for link in links if link]


def _pulls_ready(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, set(), where, "pulls_ready")
    return lambda record: all(
        pull is not None and (pull["state"] == "MERGED" or (not pull["draft"] and pull["checks"] == "pass"))
        for pull in _pulls(record)
    )


def _pulls_failing(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, set(), where, "pulls_failing")
    return lambda record: any(
        pull is not None and pull["state"] == "OPEN" and pull["checks"] == "failing" for pull in _pulls(record)
    )


def _pulls_clear(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, set(), where, "pulls_clear")
    return lambda record: all(
        pull is not None and (pull["state"] == "MERGED" or (not pull["threads"] and pull["mergeable"] == "MERGEABLE"))
        for pull in _pulls(record, settle=True)
    )


def _pulls_changed(spec: Mapping[str, Any], where: str) -> Primitive:
    _unknown(spec, {"files", "matches", "merged_matches"}, where, "pulls_changed")
    globs = spec.get("files")
    if not isinstance(globs, list) or not globs or not all(isinstance(glob, str) for glob in globs):
        raise ValueError(f"{where}: pulls_changed needs `files`, a list of globs a changed file is matched against")
    try:
        wanted = re.compile(spec["matches"])
    except KeyError as error:
        raise ValueError(f"{where}: pulls_changed needs `matches`, the regular expression the evidence carries") from error
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: pulls_changed `matches` is not a regular expression: {error}") from error
    try:
        merged_wanted = re.compile(spec.get("merged_matches", spec["matches"]))
    except (re.error, TypeError) as error:
        raise ValueError(f"{where}: pulls_changed `merged_matches` is not a regular expression: {error}") from error
    criteria = _region("acceptance_criteria")

    def holds(record: Record) -> bool:
        found = criteria.search(record.body)
        if found and any(wanted.search(line) for line in _CHECKED.findall(found.group(1))):
            return True  # a checked criterion is evidence whatever the delivery changed, so unknown files cannot fail it closed
        pulls = _pulls(record)
        if any(pull is None for pull in pulls):
            return False  # the store holds no such pull request: the rule cannot clear, so it fails closed
        found = criteria.search(record.body)
        if any(wanted.search(line) for line in (_CHECKED.findall(found.group(1)) if found else [])):
            return True  # a checked verdict clears the rule even when a pull request's file list is unknown
        declared = _values(record.front.get("modified_files"))  # stands for a record no read of GitHub listed files for
        if not declared and any(pull["files"] is None for pull in pulls):
            return False  # no file list to match for a pull request: the rule cannot clear, so it fails closed
        changed = [
            pull
            for pull in pulls
            if any(fnmatchcase(path, glob) for path in (declared if pull["files"] is None else pull["files"]) for glob in globs)
        ]

        def evidenced(pull: Mapping[str, Any]) -> bool:
            return (merged_wanted if pull["state"] == "MERGED" else wanted).search(pull["body"]) is not None

        return not changed or all(evidenced(pull) for pull in changed)

    return holds


def _found(primitive: Primitive, record: Record) -> str:
    """What a `readable` or `names_ids` primitive finds broken in `record`, "" for any other primitive or a record that holds."""
    return primitive.broken(record) if isinstance(primitive, _Readable | _NamesIds) else ""


#: How many description verdicts a `readable` primitive keeps.
_VERDICTS_KEPT = 2048


class _Readable:
    """A `readable` primitive: holds when the description reads well, and `broken` says what it found otherwise."""

    def __init__(self, template: readable.Template) -> None:
        self._template = template
        self._verdict = lru_cache(maxsize=_VERDICTS_KEPT)(lambda body: readable.broken(template, body))

    def _judged(self, record: Record) -> str:
        return readable.judged(self._template, record.body)

    def broken(self, record: Record) -> str:
        """What the body breaks, remembered per body: the verdict depends on the template and the text alone."""
        return self._verdict(record.body)

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
    "unique": _unique,
    "acyclic": _acyclic,
    "unchanged": _unchanged,
    "no_more": _no_more,
    "names_ids": _names_ids,
    "retained": _retained,
    "no_implied_dependency": _no_implied_dependency,
    "pull_proof": _pull_proof,
    "matrix_profile": _matrix_profile,
    "readable": _readable,
    "pulls_ready": _pulls_ready,
    "pulls_failing": _pulls_failing,
    "pulls_clear": _pulls_clear,
    "pulls_changed": _pulls_changed,
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
        scopes = ("write", "create")
        if not isinstance(on, dict) or on.keys() - _ON_KEYS or any(on.get(key, False) not in (True, False) for key in scopes):
            raise ValueError(f"{where}: `on` takes `to`, `from` and `while`, or `write`, or `create`")
        chosen = [bool(on.get("write")), bool(on.get("create")), bool(on.keys() & {"to", "from"})]
        if chosen.count(True) != 1 or ("while" in on and "to" not in on):
            raise ValueError(
                f"{where}: `on` is `write = true` alone, `create = true` alone, or `to` and/or `from` (`while` with `to`)"
            )
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
                created=bool(on.get("create")),
                exempt=_actors(spec.get("unless_actor", []), f"{where}.unless_actor"),
            )
        )
    return tuple(rules)


class Verdict(NamedTuple):
    """What the rules say of one write: the rule that `refused` it, else the `warned` rules it broke and still lands."""

    refused: Rule | None = None
    warned: tuple[Rule, ...] = ()


def evaluate(
    rules: tuple[Rule, ...], before: Record | None, after: Record, actor: str, warned_actors: frozenset[str] = frozenset()
) -> Verdict:
    """The verdict on the write by `actor` from `before` (None for a create) to `after`.

    The first broken rule refuses it. An actor in `warned_actors` is refused only by a rule that holds on every write, a
    create or a task staying in its lane; a rule of lane entry or exit it breaks is a warning and the move lands."""
    after = replace(after, earlier=before)
    broken = [rule for rule in rules if rule.judges(before, after, actor) and not rule.require(after)]
    return _split_broken(broken, actor, warned_actors)


def _split_broken(broken: list[Rule], actor: str, warned_actors: frozenset[str]) -> Verdict:
    """The `broken` rules as `actor` meets them: the first refuses, or for a warned actor the first that holds on every
    write refuses and the rules of lane entry or exit are warned."""
    if actor not in warned_actors:
        return Verdict(next(iter(broken), None))
    return Verdict(
        next((rule for rule in broken if not rule.moves), None), tuple(rule for rule in broken if rule.moves)
    )


def refusal(rules: tuple[Rule, ...], before: Record | None, after: Record, actor: str) -> Rule | None:
    """The first rule the write by `actor` from `before` (None for a create) to `after` breaks, or None for none.

    Not new: `apps/commands`' review-fix gate test calls it through the installed starpulse pin, which has no `evaluate`
    until the gitlink bump, so it stays until that caller moves."""
    return evaluate(rules, before, after, actor).refused


def standing_verdict(
    rules: tuple[Rule, ...],
    front: Mapping[str, Any],
    body: str,
    lane: str,
    actor: str = "",
    enter: Callable[[Mapping[str, Any]], Mapping[str, Any]] = lambda moved: moved,
    warned_actors: frozenset[str] = frozenset(),
) -> Verdict:
    """What the rules say of moving the task to `lane` by `actor` whatever other tasks hold: `evaluate`'s verdict on the
    move, naming every rule an `actor` in `warned_actors` is warned of. `enter` runs the lane's entry effects on the
    moved task, as the write does.

    A rule that reads another task can change its verdict without the task's file changing; the write still enforces
    it, but a standing verdict recorded with the task leaves it out."""
    read: list[str] = []

    def unread(task: str) -> None:
        read.append(task)

    def unread_pull(repo: str, number: int, _settle: bool) -> None:
        read.append(f"{repo}#{number}")

    before = Record(front, body, unread, pull_of=unread_pull)
    after = Record(enter({**front, "status": lane}), body, unread, before, unread_pull)
    broken = []
    for rule in rules:
        read.clear()
        if rule.judges(before, after, actor) and not rule.require(after) and not read:
            broken.append(rule)
    return _split_broken(broken, actor, warned_actors)


def standing_refusal(
    rules: tuple[Rule, ...],
    front: Mapping[str, Any],
    body: str,
    lane: str,
    actor: str = "",
    enter: Callable[[Mapping[str, Any]], Mapping[str, Any]] = lambda moved: moved,
) -> Rule | None:
    """The first rule that refuses moving the task to `lane` by `actor` whatever other tasks hold, or None."""
    return standing_verdict(rules, front, body, lane, actor, enter).refused


def readable_verdict(rules: tuple[Rule, ...], front: Mapping[str, Any], body: str) -> str:
    """What the first `readable` rule finds broken in the description of `body`, or "" when each reads well.

    It judges the description, not a write, so no actor exempts it and a state a rule names does not narrow it."""
    record = Record(front, body)
    return next((found for rule in rules if (found := _found(rule.require, record))), "")
