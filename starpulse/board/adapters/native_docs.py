"""Doc records on the native board: Backlog.md's `docs/**/doc-N - slug.<extension>` files, found through the doc index.

A Markdown file holds `id`, `title`, `type`, `created_date` and `updated_date` in its front matter and the doc's text after
it; a file of any other type holds the content alone, and its title and type live in its index row. Folders under `docs/`
(such as `specs/`) are kept: a doc stays in the folder it was filed in until it is moved. The file's name is
`<id> - <title as a slug>.<extension>`, and an archived doc is the same file in `archive/docs/`. An edit rewrites only the front
matter lines and the body it is given, so any other line, and a doc nobody changes, stay byte for byte.
"""

import os
import re
import threading
import uuid
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy.exc import SQLAlchemyError

import yaml

try:  # libyaml's loader: the same safe schema and errors, a tenth of the pure-Python parse time over a whole board
    from yaml import CSafeLoader as _FrontmatterLoader
except ImportError:
    from yaml import SafeLoader as _FrontmatterLoader

from starpulse.board.adapters import item_uuid
from starpulse.board.adapters.native_doc_index import DocIndex, Entry
from starpulse.board.model.seam import (
    DocArchiver,
    DocCreator,
    DocEditor,
    DocMover,
    DocReader,
    DocRestorer,
    Written,
)

_TYPES = ("specification", "guide", "readme", "postmortem", "other")
_CREATE = {"type", "folder", "body", "extension"}
_EDIT = {"title", "type", "body"}
_FOLDER = re.compile(r"[\w -]+(/[\w -]+)*")


def _stamp() -> str:
    """Now, in UTC, as Backlog.md writes a doc's dates."""
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M")


def _parts(text: str) -> tuple[str, str] | None:
    """A doc file's front matter lines and the text after its closing `---` line; None for a file with no front matter."""
    text = text.replace("\r\n", "\n")
    end = text.find("\n---", 4)
    if not text.startswith("---\n") or end == -1 or text[end + 4 : end + 5] not in ("", "\n"):
        return None
    return text[4 : end + 1], text[end + 5 :]


@lru_cache(maxsize=2048)
def _parsed(path: Path, mtime_ns: int, size: int) -> tuple[str, dict, str] | None:
    """A doc file's front matter lines, parsed front matter and body; None for a file that is not a doc.

    Keyed by the file's modification time and size, so a file read twice unchanged is parsed once and a rewrite is read anew.
    """
    parts = _parts(path.read_text())
    if parts is None:
        return None
    try:
        frontmatter = yaml.load(parts[0], Loader=_FrontmatterLoader)
    except yaml.YAMLError:
        return None
    return (
        (parts[0], frontmatter, parts[1])
        if isinstance(frontmatter, dict) and str(frontmatter.get("id") or "").strip()
        else None
    )


class _Doc(NamedTuple):
    """A doc's file, its index row, its front matter lines and parsed front matter (a file with none is given its row's), and its body."""

    path: Path
    head: str
    front: dict
    body: str
    entry: Entry


def _stamp_of(mtime: float) -> str:
    return datetime.fromtimestamp(mtime, UTC).strftime("%Y-%m-%d %H:%M")


def _load(root: Path, index: DocIndex, doc: str, archived: bool = False) -> _Doc | None:
    """The doc `doc` names, its row found by the index and its file read alone; None when the index has no such row or its file is gone.

    A Markdown file's front matter is the record's; any other file has the row's id, title and type, its modification time
    for both dates, and its text as the body (empty for a file that is not text).
    """
    if (entry := index.find(doc, archived)) is None:
        return None
    path = root / entry.path
    try:
        stat = path.stat()
        if path.suffix.lower() == ".md":
            parsed = _parsed(path, stat.st_mtime_ns, stat.st_size)
            return _Doc(path, *parsed, entry) if parsed is not None else None
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            text = ""
    except OSError:
        return None  # moved or removed while looking
    when = _stamp_of(stat.st_mtime)
    front = {"id": entry.id, "title": entry.title, "type": entry.type, "created_date": when, "updated_date": when}
    return _Doc(path, "", front, text, entry)


def front(root: Path, index: DocIndex, doc: str) -> dict[str, Any] | None:
    """The front matter of the open doc `doc` (its row's id, title and type for a file that is not Markdown), or None."""
    return found.front if (found := _load(root, index, doc)) else None


def counts(index: DocIndex) -> Counter[str]:
    """The open docs by `type`; a doc with none, or one outside `_TYPES`, counts as `other`."""
    by_type: Counter[str] = Counter()
    for kind, number in index.counts().items():
        by_type[kind if kind in _TYPES else "other"] += number
    return by_type


def _record(prefix: str, path: Path, frontmatter: dict, archived: bool = False) -> dict[str, Any]:
    return {
        "id": str(frontmatter["id"]).strip(),
        "title": str(frontmatter.get("title") or ""),
        "type": str(frontmatter.get("type") or ""),
        "created_date": str(frontmatter.get("created_date") or ""),
        "updated_date": str(frontmatter.get("updated_date") or ""),
        "path": str(path).removeprefix(prefix),
        "archived": archived,
    }


def reader(root: Path, index: DocIndex) -> DocReader:
    """A board reader of one doc's record with its body, an archived doc's included, or None."""

    def read(doc: str, /) -> dict[str, Any] | None:
        if found := _load(root, index, doc):
            return {**_record(f"{root / 'docs'}/", found.path, found.front), "body": found.body}
        if found := _load(root, index, doc, archived=True):
            return {**_record(f"{root / 'archive' / 'docs'}/", found.path, found.front, archived=True), "body": found.body}
        return None

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
    # Unique per write, so concurrent writers never share a scratch file; not a `.md` file, so a scan never reads it half written.
    scratch = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    scratch.write_text(text)
    os.replace(scratch, path)


_EXTENSION = re.compile(r"[A-Za-z0-9]{1,8}")
_UNSTORED = (OSError, SQLAlchemyError)


def _rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root))


def creator(root: Path, index: DocIndex) -> DocCreator:
    """A board writer that files a doc: the next id, `<id> - <title as a slug>.<extension>`, in the folder it names under
    `docs/`, and its index row. A Markdown doc (the default) holds front matter; any other extension holds the body alone."""
    lock = threading.Lock()  # two creates must not both read the same highest id

    def create(title: str, details: Mapping[str, Any], /) -> Written:
        if not title.strip():
            return Written(False, "a doc needs a title")
        try:
            if unknown := sorted(details.keys() - _CREATE):
                raise ValueError(f"{unknown[0]} is not a doc detail")
            kind, body = _kind(details.get("type", "other")), _body(details.get("body", ""))
            folder, extension = details.get("folder", ""), details.get("extension") or "md"
            if folder and not (isinstance(folder, str) and _FOLDER.fullmatch(folder)):
                raise ValueError("folder must be a path of plain names under docs/")
            if not (isinstance(extension, str) and _EXTENSION.fullmatch(extension)):
                raise ValueError("extension must be 1 to 8 letters or digits")
        except ValueError as refusal:
            return Written(False, str(refusal))
        with lock:
            doc, now = f"doc-{index.highest() + 1}", _stamp()
            path = root / "docs" / folder / f"{doc} - {_slug(title.strip())}.{extension.lower()}"
            head = (
                f"id: {doc}\nuuid: {item_uuid.mint()}\n{_line('title', title.strip())}type: {kind}\n"
                f"created_date: '{now}'\nupdated_date: '{now}'\n"
            )
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                _write(path, f"---\n{head}---\n{body}" if path.suffix == ".md" else body)
                index.put([Entry(_rel(root, path), doc, title.strip(), kind)])
            except _UNSTORED as error:
                path.unlink(missing_ok=True)
                return Written(False, f"{path}: {error}")
        return Written(True, doc)

    return create


def editor(root: Path, index: DocIndex) -> DocEditor:
    """A board writer that applies every change to a doc's file and row, or refuses the whole edit.

    A changed title renames the file to its new slug in the same folder; the id never changes. A change that changes
    nothing writes nothing, so `updated_date` moves only when the file does. A doc that is not Markdown has no front
    matter: its title and type live in its row.
    """

    def edit(doc: str, changes: Mapping[str, Any], /) -> Written:
        if (found := _load(root, index, doc)) is None:
            return Written(False, f"{doc} has no doc file in {root / 'docs'}")
        path, head, frontmatter, text, entry = found
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
        was = _record(f"{root / 'docs'}/", path, frontmatter)
        if (title, kind, body) == (was["title"], was["type"], text):
            return Written(True, f"Updated doc {doc}")
        markdown = path.suffix.lower() == ".md"
        if markdown:
            if title != was["title"]:
                head = _set(head, "title", _line("title", title))
            if kind != was["type"]:
                head = _set(head, "type", f"type: {kind}\n")
            head = _set(head, "updated_date", f"updated_date: '{_stamp()}'\n")
        target = path.with_name(f"{entry.id} - {_slug(title)}{path.suffix}")
        try:
            if markdown:
                _write(target, f"---\n{head}---\n{body}")
            elif body != text or target != path:
                _write(target, body)
            index.put([Entry(_rel(root, target), entry.id, title, kind)], replacing=entry.path)
            if target != path:
                path.unlink()
        except _UNSTORED as error:
            return Written(False, f"{path}: {error}")
        return Written(True, f"Updated doc {doc}")

    return edit


def archiver(root: Path, index: DocIndex) -> DocArchiver:
    """A board writer that moves a doc's file to `archive/docs/`, its row with it."""

    def archive(doc: str, /) -> Written:
        if (found := _load(root, index, doc)) is None:
            return Written(False, f"{doc} has no doc file in {root / 'docs'}")
        target = root / "archive" / "docs" / found.path.name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(found.path, target)
            index.put([found.entry._replace(path=_rel(root, target))], replacing=found.entry.path)
        except _UNSTORED as error:
            return Written(False, f"{found.path}: {error}")
        return Written(True, f"Archived doc {doc}")

    return archive


def _relink(root: Path, index: DocIndex, found: _Doc, target: Path) -> Written | None:
    """Move the doc's file to `target`, never replacing a file already there, and its row with it; a refusal, else None."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.link(found.path, target)
        found.path.unlink()
        index.put([found.entry._replace(path=_rel(root, target))], replacing=found.entry.path)
    except FileExistsError:
        return Written(False, f"{found.entry.id}: {target} already exists")
    except _UNSTORED as error:
        return Written(False, f"{found.path}: {error}")
    return None


def restorer(root: Path, index: DocIndex) -> DocRestorer:
    """A board writer that returns an archived doc's file to the folder it names under `docs/`, unchanged."""

    def restore(doc: str, folder: str = "", /) -> Written:
        if folder and not (isinstance(folder, str) and _FOLDER.fullmatch(folder)):
            return Written(False, "folder must be a path of plain names under docs/")
        if (open_doc := _load(root, index, doc)) is not None:
            return Written(False, f"{doc} is already on the board at {open_doc.path}")
        if (found := _load(root, index, doc, archived=True)) is None:
            return Written(False, f"{doc} has no archived doc file in {root / 'archive' / 'docs'}")
        return _relink(root, index, found, root / "docs" / folder / found.path.name) or Written(True, f"Restored doc {doc}")

    return restore


def mover(root: Path, index: DocIndex) -> DocMover:
    """A board writer that moves an open doc's file to the folder it names under `docs/`, unchanged, and its row with it."""

    def move(doc: str, folder: str, /) -> Written:
        if folder and not (isinstance(folder, str) and _FOLDER.fullmatch(folder)):
            return Written(False, "folder must be a path of plain names under docs/")
        if (found := _load(root, index, doc)) is None:
            return Written(False, f"{doc} has no doc file in {root / 'docs'}")
        target = root / "docs" / folder / found.path.name
        if target == found.path:
            return Written(True, f"Moved doc {doc}")
        return _relink(root, index, found, target) or Written(True, f"Moved doc {doc}")

    return move
