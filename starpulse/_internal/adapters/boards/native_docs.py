"""Doc records on the native board: Backlog.md's `docs/**/doc-N - slug.md` files.

A file holds `id`, `title`, `type`, `created_date` and `updated_date` in its front matter and the doc's text after it. Folders
under `docs/` (such as `specs/`) are kept: a doc stays in the folder it was filed in. The file's name is
`<id> - <title as a slug>.md`, and an archived doc is the same file in `archive/docs/`. An edit rewrites only the front
matter lines and the body it is given, so any other line, and a doc nobody changes, stay byte for byte.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from starpulse._internal.adapters.boards.seam import DocArchiver, DocCreator, DocEditor, DocLister, DocReader, Written

_TYPES = ("specification", "guide", "readme", "other")
_CREATE = {"type", "folder", "body"}
_EDIT = {"title", "type", "body"}
_FOLDER = re.compile(r"[\w -]+(/[\w -]+)*")


def _stamp() -> str:
    """Now, in the host's local time, as Backlog.md writes a doc's dates."""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _parts(text: str) -> tuple[str, str] | None:
    """A doc file's front matter lines and the text after its closing `---` line; None for a file with no front matter."""
    text = text.replace("\r\n", "\n")
    end = text.find("\n---", 4)
    if not text.startswith("---\n") or end == -1 or text[end + 4 : end + 5] not in ("", "\n"):
        return None
    return text[4 : end + 1], text[end + 5 :]


def _files(root: Path) -> list[tuple[Path, str, dict, str]]:
    """Each open doc's file with its front matter lines, parsed front matter and body, by ascending number."""
    found = []
    for path in (root / "docs").rglob("doc-*.md"):
        try:
            parts = _parts(path.read_text())
        except OSError:
            continue  # moved or removed while looking
        if parts is None:
            continue
        try:
            frontmatter = yaml.safe_load(parts[0])
        except yaml.YAMLError:
            continue
        if isinstance(frontmatter, dict) and str(frontmatter.get("id") or "").strip():
            found.append((path, parts[0], frontmatter, parts[1]))
    return sorted(found, key=lambda file: int(re.sub(r"\D", "", str(file[2]["id"])) or 0))


def _find(root: Path, doc: str) -> tuple[Path, str, dict, str] | None:
    return next((file for file in _files(root) if str(file[2]["id"]).strip() == doc), None)


def _record(root: Path, path: Path, frontmatter: dict) -> dict[str, Any]:
    return {
        "id": str(frontmatter["id"]).strip(),
        "title": str(frontmatter.get("title") or ""),
        "type": str(frontmatter.get("type") or ""),
        "created_date": str(frontmatter.get("created_date") or ""),
        "updated_date": str(frontmatter.get("updated_date") or ""),
        "path": path.relative_to(root / "docs").as_posix(),
    }


def lister(root: Path) -> DocLister:
    """A board reader of every open doc under `docs/`, body left out, by ascending number."""
    return lambda: [_record(root, path, frontmatter) for path, _, frontmatter, _ in _files(root)]


def reader(root: Path) -> DocReader:
    """A board reader of one open doc's record with its body, or None."""

    def read(doc: str, /) -> dict[str, Any] | None:
        found = _find(root, doc)
        return {**_record(root, found[0], found[2]), "body": found[3]} if found else None

    return read


def _slug(title: str) -> str:
    """The file-name slug Backlog.md gives a doc title: `<>:"/\\|?*` read as a space, `'(),` dropped, runs of space as `-`."""
    return re.sub(r"\s+", "-", re.sub(r"['(),]", "", re.sub(r'[<>:"/\\|?*]', " ", title)).strip())


def _line(key: str, value: str) -> str:
    """A front matter line, quoted by YAML only when the value needs it."""
    return yaml.safe_dump({key: value}, allow_unicode=True, width=10**9)


def _set(head: str, key: str, line: str) -> str:
    """`head` with the `key` line (and any lines it continues onto) replaced by `line`, or `line` added at its end."""
    pattern = re.compile(rf"^{key}:.*\n(?:[ \t]+.*\n)*", re.M)
    return pattern.sub(lambda _: line, head, count=1) if pattern.search(head) else head + line


def _body(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("body must be text")
    return value + "\n" if value and not value.endswith("\n") else value


def _kind(value: Any) -> str:
    if value not in _TYPES:
        raise ValueError(f"type must be one of {', '.join(_TYPES)}")
    return value


def _write(path: Path, text: str) -> None:
    scratch = path.with_name(f"{path.name}.tmp")  # not a `.md` file, so a scan never reads it half written
    scratch.write_text(text)
    os.replace(scratch, path)


def _next_id(root: Path) -> str:
    """`doc-N` with N one past the highest on the board, its archived docs included."""
    highest = 0
    for folder in ("docs", "archive/docs"):
        for path in (root / folder).rglob("doc-*.md"):
            if found := re.match(r"doc-(\d+) - ", path.name):
                highest = max(highest, int(found[1]))
    return f"doc-{highest + 1}"


def creator(root: Path) -> DocCreator:
    """A board writer that files a doc: the next id, `<id> - <title as a slug>.md`, in the folder it names under `docs/`."""
    lock = threading.Lock()  # two creates must not both read the same highest id

    def create(title: str, details: Mapping[str, Any], /) -> Written:
        if not title.strip():
            return Written(False, "a doc needs a title")
        try:
            if unknown := sorted(details.keys() - _CREATE):
                raise ValueError(f"{unknown[0]} is not a doc detail")
            kind, body = _kind(details.get("type", "other")), _body(details.get("body", ""))
            folder = details.get("folder", "")
            if folder and not (isinstance(folder, str) and _FOLDER.fullmatch(folder)):
                raise ValueError("folder must be a path of plain names under docs/")
        except ValueError as refusal:
            return Written(False, str(refusal))
        with lock:
            doc, now = _next_id(root), _stamp()
            path = root / "docs" / folder / f"{doc} - {_slug(title.strip())}.md"
            head = (
                f"id: {doc}\n{_line('title', title.strip())}type: {kind}\n"
                f"created_date: '{now}'\nupdated_date: '{now}'\n"
            )
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write(path, f"---\n{head}---\n{body}")
            except OSError as error:
                return Written(False, f"{path}: {error}")
        return Written(True, doc)

    return create


def editor(root: Path) -> DocEditor:
    """A board writer that applies every change to a doc's file in one write, or refuses the whole edit.

    A changed title renames the file to its new slug in the same folder; the id never changes. A change that changes
    nothing writes nothing, so `updated_date` moves only when the file does.
    """

    def edit(doc: str, changes: Mapping[str, Any], /) -> Written:
        if (found := _find(root, doc)) is None:
            return Written(False, f"{doc} has no doc file in {root / 'docs'}")
        path, head, frontmatter, text = found
        try:
            if unknown := sorted(changes.keys() - _EDIT):
                raise ValueError(f"{unknown[0]} is not an editable field")
            title, kind, body = str(frontmatter.get("title") or ""), str(frontmatter.get("type") or ""), text
            if "title" in changes:
                if not isinstance(changes["title"], str) or not changes["title"].strip():
                    raise ValueError("title must be text that is not blank")
                title = changes["title"].strip()
            if "type" in changes:
                kind = _kind(changes["type"])
            if "body" in changes:
                body = _body(changes["body"])
        except ValueError as refusal:  # raised before any file is written, so a refusal writes nothing
            return Written(False, f"{doc}: {refusal}")
        was = _record(root, path, frontmatter)
        if (title, kind, body) == (was["title"], was["type"], text):
            return Written(True, f"Updated doc {doc}")
        if title != was["title"]:
            head = _set(head, "title", _line("title", title))
        if kind != was["type"]:
            head = _set(head, "type", f"type: {kind}\n")
        head = _set(head, "updated_date", f"updated_date: '{_stamp()}'\n")
        target = path.with_name(f"{doc} - {_slug(title)}.md")
        try:
            _write(target, f"---\n{head}---\n{body}")
            if target != path:
                path.unlink()
        except OSError as error:
            return Written(False, f"{path}: {error}")
        return Written(True, f"Updated doc {doc}")

    return edit


def archiver(root: Path) -> DocArchiver:
    """A board writer that moves a doc's file to `archive/docs/`."""

    def archive(doc: str, /) -> Written:
        if (found := _find(root, doc)) is None:
            return Written(False, f"{doc} has no doc file in {root / 'docs'}")
        target = root / "archive" / "docs" / found[0].name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(found[0], target)
        except OSError as error:
            return Written(False, f"{found[0]}: {error}")
        return Written(True, f"Archived doc {doc}")

    return archive
