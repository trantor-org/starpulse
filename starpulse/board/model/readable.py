"""The `readable` guard primitive: whether a task's description follows a configured template.

It counts and prefix-matches, never judges meaning: ordered `headings` (each required unless `optional`, with a
`max_sentences` cap and `no_paths`), `commands` that start a line only inside a fenced block, `max_paths_per_sentence`,
and a `blast_radius` format whose axis and rollback rules read the headings it names. A path in prose belongs in
backticks. The verdict is the first broken rule with its line in the description, or "" when it reads well.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ["Template", "broken", "parse"]

_FENCE = re.compile(r"^\s*(```|~~~)")
_HEADING = re.compile(r"^## +(\S.*?) *$")
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_REGION = re.compile(r"<!-- SECTION:DESCRIPTION:BEGIN -->\n?(.*?)<!-- SECTION:DESCRIPTION:END -->", re.S)
_CODE = re.compile(r"`[^`]*`")
_URL = re.compile(r"https?://\S+")
_TARGET = re.compile(r"\]\([^)]*\)")
_ABBREVIATION = re.compile(r"\b(e\.g|i\.e|etc|vs)\.")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?![a-z])")
#: A path: one that opens with `./`, `../`, `~/` or `/`, has two slashes, or ends in a file extension.
_PATH = re.compile(r"(?<![\w/.~-])(?:\.{0,2}/|~/)?[\w.-]+(?:/[\w.-]+)+/?|(?<![\w/.~-])[\w-]+(?:\.[\w-]+)*\.[a-z]{1,5}\b")
_FILE = re.compile(r"\.[a-z]{1,5}$")
_RADIUS = re.compile(r"^reach ([0-3]) · data ([0-3]) · undo ([0-3]) · detect ([0-3])\. \S")
_AXES = ("reach", "data", "undo", "detect")
_TEMPLATE_KEYS = {"headings", "commands", "max_paths_per_sentence", "blast_radius", "board_written"}
_HEADING_KEYS = {"name", "optional", "max_sentences", "no_paths"}
_RADIUS_KEYS = {"heading", "stops", "rollback", "stop_at", "rollback_at"}


@dataclass(frozen=True)
class Heading:
    name: str
    optional: bool = False
    max_sentences: int | None = None
    no_paths: bool = False


@dataclass(frozen=True)
class BlastRadius:
    heading: str
    stops: str
    rollback: str
    stop_at: int = 3
    rollback_at: int = 2


@dataclass(frozen=True)
class Template:
    headings: tuple[Heading, ...]
    commands: tuple[str, ...] = ()
    max_paths: int | None = None
    blast_radius: BlastRadius | None = None
    board_written: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Section:
    name: str
    line: int
    rows: tuple[tuple[int, str], ...]


def _count(spec: Mapping[str, Any], key: str, where: str, floor: int = 1) -> int | None:
    value = spec.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value < floor:
        raise ValueError(f"{where}: {key} must be a whole number of at least {floor}")
    return value


def _table(spec: object, keys: set[str], where: str) -> Mapping[str, Any]:
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: expected a table")
    if unknown := sorted(spec.keys() - keys):
        raise ValueError(f"{where}: no key {', '.join(unknown)}; known: {', '.join(sorted(keys))}")
    return spec


def _text(spec: Mapping[str, Any], key: str, where: str) -> str:
    value = spec.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: needs `{key}`, a non-empty name")
    return value.strip()


def parse(spec: Mapping[str, Any], where: str) -> Template:
    """The template a `readable` primitive declares; a ValueError names what it cannot read."""
    _table(spec, _TEMPLATE_KEYS, where)
    declared = spec.get("headings")
    if not isinstance(declared, list) or not declared:
        raise ValueError(f"{where}: readable needs `headings`, the ordered list of `## ` headings")
    headings = []
    for number, item in enumerate(declared):
        here = f"{where}.headings[{number}]"
        item = _table(item, _HEADING_KEYS, here)
        headings.append(
            Heading(
                _text(item, "name", here),
                bool(item.get("optional")),
                _count(item, "max_sentences", here),
                bool(item.get("no_paths")),
            )
        )
    commands = spec.get("commands", [])
    if not isinstance(commands, list) or not all(isinstance(prefix, str) and prefix for prefix in commands):
        raise ValueError(f"{where}: readable `commands` is a list of the prefixes a command line starts with")
    radius = None
    if "blast_radius" in spec:
        here = f"{where}.blast_radius"
        table = _table(spec["blast_radius"], _RADIUS_KEYS, here)
        radius = BlastRadius(
            _text(table, "heading", here),
            _text(table, "stops", here),
            _text(table, "rollback", here),
            _count(table, "stop_at", here, 0) or 3,
            _count(table, "rollback_at", here, 0) or 2,
        )
    written = spec.get("board_written", [])
    if not isinstance(written, list) or not all(isinstance(name, str) and name for name in written):
        raise ValueError(f"{where}: readable `board_written` is a list of the `## ` headings the board writes")
    return Template(tuple(headings), tuple(commands), _count(spec, "max_paths_per_sentence", where), radius, tuple(written))


def description(body: str) -> str:
    found = _REGION.search(body)
    return found.group(1) if found else body


def judged(template: Template, body: str) -> str:
    """The description in `body` without the `board_written` sections, which the board writes and no template judges."""
    kept: list[str] = []
    fenced = skipping = False
    for line in description(body).splitlines(keepends=True):
        if _FENCE.match(line):
            fenced = not fenced
        heading = None if fenced else _HEADING.match(line)
        if heading:
            skipping = heading.group(1) in template.board_written
        if not skipping:
            kept.append(line)
    return "".join(kept).rstrip()


def _sections(text: str) -> tuple[list[tuple[int, str]], list[_Section]]:
    """The description's lines before its first heading and its `## ` sections, fenced lines marked with a `\\0` prefix."""
    preamble: list[tuple[int, str]] = []
    sections: list[tuple[str, int, list[tuple[int, str]]]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if _FENCE.match(line):
            fenced = not fenced
        heading = None if fenced else _HEADING.match(line)
        if heading:
            sections.append((heading.group(1), number, []))
            continue
        row = (number, f"\0{line}" if fenced or _FENCE.match(line) else line)
        (sections[-1][2] if sections else preamble).append(row)
    return preamble, [_Section(name, line, tuple(rows)) for name, line, rows in sections]


def _prose(section: _Section) -> list[tuple[int, str]]:
    return [(number, line) for number, line in section.rows if not line.startswith("\0")]


def _blocks(rows: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The paragraphs and list items of `rows`, each with the line it starts on."""
    blocks: list[tuple[int, list[str]]] = []
    open_block = False
    for number, line in rows:
        if not line.strip():
            open_block = False
        elif open_block and not _ITEM.match(line):
            blocks[-1][1].append(line.strip())
        else:
            blocks.append((number, [_ITEM.sub("", line).strip()]))
            open_block = True
    return [(number, " ".join(parts)) for number, parts in blocks]


def _plain(text: str) -> str:
    """`text` without the dots that do not end a sentence or name a path: abbreviations, link targets and URLs."""
    return _ABBREVIATION.sub(lambda match: match.group(0).replace(".", ""), _URL.sub("U", _TARGET.sub("]", text)))


def _sentences(rows: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """The sentences of the paragraphs and list items of `rows`, each with the line its block starts on."""
    return [
        (number, piece.replace("`", ""))
        for number, block in _blocks(rows)
        for piece in _SENTENCE_END.split(_plain(block))
        if piece.strip()
    ]


def _paths(text: str) -> list[str]:
    """The paths `text` names: a token with a slash that opens a path or ends in an extension, or a file name."""
    named = (found.group(0).rstrip(".") for found in _PATH.finditer(_plain(text)))
    return [path for path in named if path.count("/") > 1 or path.startswith(("/", ".", "~")) or _FILE.search(path)]


def _structure(template: Template, found: list[_Section], last: int) -> str:
    position = 0
    for heading in template.headings:
        if position < len(found) and found[position].name == heading.name:
            position += 1
        elif not heading.optional:
            if position < len(found):
                return f"expected heading `{heading.name}`, found `{found[position].name}` (line {found[position].line})"
            return f"missing heading `{heading.name}` (line {last + 1})"
    if position < len(found):
        return f"heading `{found[position].name}` is out of order or not in the template (line {found[position].line})"
    return ""


def _prose_rules(template: Template, section: _Section, rules: Mapping[str, Heading]) -> str:
    rows = _prose(section)
    for number, line in rows:
        text = _ITEM.sub("", line).strip()
        if command := next((prefix for prefix in template.commands if re.match(rf"{re.escape(prefix)}(\s|$)", text)), ""):
            return f"command `{command}` is not in a fenced block (line {number})"
    sentences = _sentences(rows)
    heading = rules.get(section.name)
    if heading and heading.max_sentences is not None and len(sentences) > heading.max_sentences:
        return (
            f"`{section.name}` has {len(sentences)} sentences, at most {heading.max_sentences} "
            f"(line {sentences[heading.max_sentences][0]})"
        )
    for number, line in rows:
        if heading and heading.no_paths and (named := _paths(line)):
            return f"`{section.name}` names the path `{named[0]}` (line {number})"
        if named := _paths(_CODE.sub(" ", line)):
            return f"the path `{named[0]}` is not in backticks (line {number})"
    for number, sentence in sentences:
        count = len(_paths(sentence))
        if template.max_paths is not None and count > template.max_paths:
            return f"a sentence names {count} paths, at most {template.max_paths}: list them (line {number})"
    return ""


def _radius(template: Template, found: list[_Section]) -> str:
    radius = template.blast_radius
    by_name = {section.name: section for section in found}
    if radius is None or radius.heading not in by_name:
        return ""
    section = by_name[radius.heading]
    first = next(((number, line.strip()) for number, line in _prose(section) if line.strip()), None)
    scores = _RADIUS.match(first[1]) if first else None
    if first is None or scores is None:
        return (
            f"`{radius.heading}` opens with `reach N · data N · undo N · detect N. <sentence>`, each N 0 to 3 "
            f"(line {first[0] if first else section.line})"
        )
    stops = by_name.get(radius.stops)
    stop_text = " ".join(line.lower() for _, line in _prose(stops)) if stops else ""
    for axis, score in zip(_AXES, scores.groups()):
        if int(score) >= radius.stop_at and not re.search(rf"\b{axis}\b", stop_text):
            return f"`{axis}` is {score} and no `{radius.stops}` bullet names it (line {stops.line if stops else first[0]})"
    if int(scores.group(3)) >= radius.rollback_at and radius.rollback not in by_name:
        return f"`undo` is {scores.group(3)}, so a `{radius.rollback}` section is required (line {first[0]})"
    return ""


def broken(template: Template, body: str) -> str:
    """The first rule the description in `body` breaks, with its line in the description, or "" when it reads well."""
    text = judged(template, body)
    preamble, found = _sections(text)
    if stray := next(((number, line) for number, line in preamble if line.strip()), None):
        return f"text before the first heading (line {stray[0]})"
    if why := _structure(template, found, len(text.splitlines())):
        return why
    rules = {heading.name: heading for heading in template.headings}
    for section in found:
        if why := _prose_rules(template, section, rules):
            return why
    return _radius(template, found)
