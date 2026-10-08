"""Milestone records on the native board: Backlog.md's `milestones/m-N - slug.md` files.

A file holds `id` and `title` in its front matter and, under `## Description`, the sections a milestone is read by:
`## Outcome`, `## Spec`, `## ADRs` and `## Retro`. `Spec` and `ADRs` are bullet lines, one entry each. The file's name is
`<id> - <title as a slug>.md`, and an archived milestone is the same file under `archive/milestones/`. A section these
verbs do not name, and prose before the first heading, are kept as they are when a milestone is edited.
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from starpulse.adapters.boards.seam import (
    MilestoneArchiver,
    MilestoneCreator,
    MilestoneEditor,
    MilestoneLister,
    MilestoneReader,
    Written,
)
from starpulse.adapters.boards.upstream_backlog import _split

#: The sections a milestone is composed of, in the order they are written, and the detail each takes.
_ORDER = (("Outcome", "outcome"), ("Spec", "specs"), ("ADRs", "adrs"), ("Retro", "retro"))
_LISTS = {"specs", "adrs"}
_DETAILS = {field for _, field in _ORDER}
_HEADING = re.compile(r"^## (.+?)[ \t]*$", re.M)
_DESCRIPTION = re.compile(r"^## Description[ \t]*$", re.M)


def _description(body: str) -> str:
    heading = _DESCRIPTION.search(body)
    return body[heading.end() :].strip() if heading else ""


def _sections(description: str) -> dict[str, str]:
    """The text under each `## ` heading of a milestone's description, trimmed, in file order; prose before the first is `""`."""
    found = list(_HEADING.finditer(description))
    preface = description[: found[0].start() if found else None].strip()
    return {"": preface} | {
        heading[1]: description[heading.end() : following.start() if following else None].strip()
        for heading, following in zip(found, [*found[1:], None], strict=True)
    }


def _bullets(text: str) -> list[str]:
    return [line[2:].strip() for line in text.splitlines() if line.startswith("- ") and line[2:].strip()]


def _files(root: Path) -> list[tuple[Path, dict, str]]:
    """Each open milestone's file with its front matter and body, by ascending number."""
    found = []
    for path in (root / "milestones").glob("m-*.md"):
        try:
            frontmatter, body = _split(path.read_text())
        except OSError:
            continue  # moved or removed while looking
        if isinstance(frontmatter, dict) and str(frontmatter.get("id") or "").strip():
            found.append((path, frontmatter, body))
    return sorted(found, key=lambda file: int(re.sub(r"\D", "", str(file[1]["id"])) or 0))


def _find(root: Path, milestone: str) -> tuple[Path, dict, str] | None:
    return next((file for file in _files(root) if str(file[1]["id"]).strip() == milestone), None)


def _record(frontmatter: dict, body: str) -> dict[str, Any]:
    description = _description(body)
    sections = _sections(description)
    return {
        "id": str(frontmatter["id"]).strip(),
        "title": str(frontmatter.get("title") or ""),
        "outcome": sections.get("Outcome", ""),
        "specs": _bullets(sections.get("Spec", "")),
        "adrs": _bullets(sections.get("ADRs", "")),
        "retro": sections.get("Retro", ""),
        "description": description,
    }


def lister(root: Path) -> MilestoneLister:
    """A board reader of every open milestone under `milestones/`, by ascending number."""
    return lambda: [_record(frontmatter, body) for _, frontmatter, body in _files(root)]


def reader(root: Path) -> MilestoneReader:
    """A board reader of one open milestone's record, or None."""

    def read(milestone: str, /) -> dict[str, Any] | None:
        found = _find(root, milestone)
        return _record(found[1], found[2]) if found else None

    return read


def _slug(title: str) -> str:
    """The file-name slug Backlog.md gives a title: lower case, runs of space as `-`, no path characters, 50 at most."""
    return re.sub(r'[<>:"/\\|?*]', "", re.sub(r"\s+", "-", title.lower()))[:50]


def _text(field: str, value: Any) -> str:
    """A detail as the text its section holds, or a ValueError naming what it must be."""
    if field in _LISTS:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{field} must be a list of text")
        return "\n".join(f"- {item.strip()}" for item in value if item.strip())
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    return value.strip()


def _render(milestone: str, title: str, sections: Mapping[str, str]) -> str:
    """A milestone file: its front matter, then each non-empty section under `## Description`."""
    body = "\n\n".join(f"## {name}\n\n{text}" if name else text for name, text in sections.items() if text)
    return (
        f"---\nid: {milestone}\ntitle: {json.dumps(title, ensure_ascii=False)}\n---\n\n## Description\n\n"
        f"{body}{chr(10) if body else ''}"
    )


def _write(path: Path, text: str) -> None:
    scratch = path.with_name(f"{path.name}.tmp")  # not a `.md` file, so a scan never reads it half written
    scratch.write_text(text)
    os.replace(scratch, path)


def _next_id(root: Path) -> str:
    """`m-N` with N one past the highest on the board, its archived milestones included."""
    highest = -1
    for folder in ("milestones", "archive/milestones"):
        for path in (root / folder).glob("m-*.md"):
            if found := re.match(r"m-(\d+) - ", path.name):
                highest = max(highest, int(found[1]))
    return f"m-{highest + 1}"


def creator(root: Path) -> MilestoneCreator:
    """A board writer that opens a milestone: the next id, `<id> - <title as a slug>.md`, its details as sections."""
    lock = threading.Lock()  # two adds must not both read the same highest id

    def create(title: str, details: Mapping[str, Any], /) -> Written:
        if not title.strip():
            return Written(False, "a milestone needs a title")
        try:
            if unknown := sorted(details.keys() - _DETAILS):
                raise ValueError(f"{unknown[0]} is not a milestone detail")
            sections = {name: _text(field, details[field]) for name, field in _ORDER if field in details}
        except ValueError as refusal:
            return Written(False, str(refusal))
        with lock:
            milestone = _next_id(root)
            path = root / "milestones" / f"{milestone} - {_slug(title.strip())}.md"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write(path, _render(milestone, title.strip(), sections))
            except OSError as error:
                return Written(False, f"{path}: {error}")
        return Written(True, milestone)

    return create


def editor(root: Path) -> MilestoneEditor:
    """A board writer that applies every change to a milestone's file in one write, or refuses the whole edit.

    A changed title renames the file to its new slug; the id never changes.
    """

    def edit(milestone: str, changes: Mapping[str, Any], /) -> Written:
        if (found := _find(root, milestone)) is None:
            return Written(False, f"{milestone} has no milestone file in {root / 'milestones'}")
        path, frontmatter, body = found
        try:
            if unknown := sorted(changes.keys() - _DETAILS - {"title"}):
                raise ValueError(f"{unknown[0]} is not an editable field")
            title = str(frontmatter.get("title") or "")
            if "title" in changes:
                if not isinstance(changes["title"], str) or not changes["title"].strip():
                    raise ValueError("title must be text that is not blank")
                title = changes["title"].strip()
            sections = _sections(_description(body))
            for name, field in _ORDER:
                if field in changes:
                    sections[name] = _text(field, changes[field])
        except ValueError as refusal:  # raised before any file is written, so a refusal writes nothing
            return Written(False, f"{milestone}: {refusal}")
        target = path.with_name(f"{milestone} - {_slug(title)}.md")
        try:
            _write(target, _render(milestone, title, sections))
            if target != path:
                path.unlink()
        except OSError as error:
            return Written(False, f"{path}: {error}")
        return Written(True, f"Updated milestone {milestone}")

    return edit


def archiver(root: Path) -> MilestoneArchiver:
    """A board writer that moves a milestone's file to `archive/milestones/`."""

    def archive(milestone: str, /) -> Written:
        if (found := _find(root, milestone)) is None:
            return Written(False, f"{milestone} has no milestone file in {root / 'milestones'}")
        target = root / "archive" / "milestones" / found[0].name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(found[0], target)
        except OSError as error:
            return Written(False, f"{found[0]}: {error}")
        return Written(True, f"Archived milestone {milestone}")

    return archive
