"""Finding one task's file on the native board, and the file reads that lookup shares with the board's writers."""

import os
import re
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from starpulse.board.adapters.native_scan import _split

#: Where `_find` last found each task, so a repeat lookup reads that one file instead of listing the board.
_FOUND: dict[tuple[Path, str, tuple[str, ...]], Path] = {}

#: How old a file's modification time is before its record is kept: well past a kernel clock tick.
_SETTLED_NS = 1_000_000_000

#: The `*.md` names `_md_names` last listed in each folder, so a first lookup of a task the board already held when it
#: was listed does not list the folder again.
_LISTED: dict[Path, list[str]] = {}

#: The folders' modification times when `_find` last missed each task, so a repeat lookup of an id the board lacks reads
#: no file until a task file is added, renamed or removed. Kept only once every folder is `_SETTLED_NS` old.
_MISSED: dict[tuple[Path, str, tuple[str, ...]], tuple[int, ...]] = {}
_MISSED_KEPT = 4096


def _stamps(root: Path, folders: tuple[str, ...]) -> tuple[int, ...]:
    stamps = []
    for folder in folders:
        try:
            stamps.append((root / folder).stat().st_mtime_ns)
        except FileNotFoundError:
            stamps.append(-1)
    return tuple(stamps)


def _find(root: Path, task: str, folders: tuple[str, ...] = ("tasks", "completed")) -> Path | None:
    """The file under `tasks/`, or `completed/` once it is completed, whose front matter holds `id: <task>` in any case;
    `folders` names where else to look.

    A file named for the id is checked first; any other is parsed only when its raw front matter has an `id:` line
    spelling the id, so a lookup parses the file it returns rather than every file on the board. The file found last
    time, then the same name in each other folder (a completed task's file moves with its name), is tried before the
    folders are listed; one that was renamed or rewritten for another task is a miss.
    A miss on folders unchanged since the last miss reads nothing.
    A file named for the id is first looked for in the folders as last listed; a miss there lists them again, so a
    file added or renamed since is found, and the others are only ever checked against a fresh listing.
    """
    key = (root, task.casefold(), folders)
    spelled = _id_line(task)
    if (path := _FOUND.get(key)) is not None:
        for kept in (path, *(root / folder / path.name for folder in folders)):
            if _has_id(kept, task, spelled, False):
                _FOUND[key] = kept
                return kept
    stamps = _stamps(root, folders)
    if _MISSED.get(key) == stamps:
        return None
    for fresh in (False, True):
        listed = [(directory, _md_names(directory, fresh)) for directory in (root / folder for folder in folders)]
        named = (directory / name for directory, names in listed for name in names if _named_for(name, task))
        others = (
            directory / name
            for (directory, names), stamp in zip(listed, stamps, strict=True)
            if not _folder_lacks(directory, stamp, names, task)
            for name in names
            if not _named_for(name, task)
        )
        for candidates, held in ((named, False), (others if fresh else (), True)):
            for path in candidates:
                if _spells_id(path, task, spelled) if held else _has_id(path, task, spelled, False):
                    _FOUND[key] = path
                    _MISSED.pop(key, None)
                    return path
    _FOUND.pop(key, None)
    if max(stamps) < time.time_ns() - _SETTLED_NS:
        if len(_MISSED) >= _MISSED_KEPT:
            _MISSED.clear()
        _MISSED[key] = stamps
    return None


def _md_names(directory: Path, fresh: bool) -> list[str]:
    """The names of the `*.md` files in `directory`, in order, as last listed unless `fresh`; a `Path` is built only
    for a name worth opening."""
    if not fresh and (names := _LISTED.get(directory)) is not None:
        return names
    try:
        with os.scandir(directory) as entries:
            names = sorted(entry.name for entry in entries if entry.name.endswith(".md"))
    except FileNotFoundError:
        names = []
    _LISTED[directory] = names
    return names


def _has_id(path: Path, task: str, spelled: re.Pattern[str], prefilter: bool) -> bool:
    """Whether the file's front matter has `id: <task>`; `prefilter` skips the parse of a file whose raw text does not spell it."""
    try:
        text = path.read_text()
    except OSError:
        return False  # moved or removed while looking
    if prefilter and not spelled.search(_front_matter(text)):
        return False
    frontmatter, _ = _split(text)
    if not isinstance(frontmatter, dict):
        return False
    ids = [str(frontmatter.get("id") or "").strip(), str(frontmatter.get("uuid") or "").strip(), *_aliases(frontmatter)]
    return task.casefold() in {found.casefold() for found in ids}


#: Per file, the words on the `id:`, `aliases:` and list-item lines of its raw front matter as last seen at a stamp
#: (mtime_ns, size), casefolded, so a quote, a flow list or a trailing comment hides none: a superset of its ids, so a miss on a settled board stats each file instead of reading it. Kept only once the file
#: is `_SETTLED_NS` old, as `native._FILE_IDS` is.
_SPELLED: dict[Path, tuple[tuple[int, int], frozenset[str]]] = {}
_SPELLED_KEPT = 16384
_SPELLED_LINE = re.compile(r"^[ \t]*(?:id:|uuid:|aliases:|-)(.*)$", re.M)
_SPELLED_TOKEN = re.compile(r"[^\s,\[\]{}\"'#]+")

#: Per folder, the union of its files' spelled lines at the folder's mtime. A write replaces a file, which moves the
#: folder's mtime, so a folder settled at the same mtime holds the same lines and a miss skips it with no stat.
_DIR_SPELLED: dict[Path, tuple[int, frozenset[str]]] = {}


def _spelled_lines(path: Path) -> frozenset[str]:
    stamp = _stamp(path)
    held = _SPELLED.get(path)
    if held is None or held[0] != stamp:
        lines = _SPELLED_LINE.findall(_front_matter(path.read_text()))
        held = (stamp, frozenset(token.casefold() for line in lines for token in _SPELLED_TOKEN.findall(line)))
        if stamp[0] < time.time_ns() - _SETTLED_NS:
            if len(_SPELLED) >= _SPELLED_KEPT:
                _SPELLED.clear()
            _SPELLED[path] = held
    return held[1]


def _spells_id(path: Path, task: str, spelled: re.Pattern[str]) -> bool:
    """Whether the file's front matter has `id: <task>`, reading the file only when it was written since its spelled
    lines were held or when it spells the id."""
    try:
        lines = _spelled_lines(path)
    except OSError:
        return False  # moved or removed while looking
    return task.casefold() in lines and _has_id(path, task, spelled, True)


def _folder_lacks(directory: Path, stamp: int, names: list[str], task: str) -> bool:
    """Whether no file of the folder, settled at `stamp` (its mtime read before `names` was listed), spells `task`."""
    if stamp >= time.time_ns() - _SETTLED_NS:
        return False
    held = _DIR_SPELLED.get(directory)
    if held is None or held[0] != stamp:
        union: set[str] = set()
        for name in names:
            try:
                union |= _spelled_lines(directory / name)
            except OSError:
                continue  # moved or removed while looking
        held = (stamp, frozenset(union))
        _DIR_SPELLED[directory] = held
    return task.casefold() not in held[1]


def _named_for(name: str, task: str) -> bool:
    """Whether the file's name starts with the id, as `task-5 - Title.md` does for `task-5` but not for `task-50`."""
    return name[: len(task)].lower() == task.lower() and not name[len(task) : len(task) + 1].isalnum()


def _front_matter(text: str) -> str:
    """The raw text between a file's `---` fences, empty for a file with none."""
    text = text.replace("\r\n", "\n")
    end = text.find("\n---", 4)
    return text[4:end] if text.startswith("---\n") and end != -1 else ""


def _id_line(task: str) -> re.Pattern[str]:
    """A front matter line of the `id:`, `aliases:` or list-item kind that holds `task` as a word, quoted or not, in a
    flow list, before a comment, in any case; the parse decides whether it is the id or an alias."""
    return re.compile(rf"^[ \t]*(?:id:|uuid:|aliases:|-)[^\n]*(?<![\w-]){re.escape(task)}(?![\w-])", re.M | re.I)


def _aliases(frontmatter: Mapping[str, Any]) -> list[str]:
    """The ids a task answers to besides its own `id`, as its `aliases` front matter lists them."""
    aliases = frontmatter.get("aliases")
    return [str(alias).strip() for alias in aliases] if isinstance(aliases, list) else []


def _stamp(path: Path) -> tuple[int, int]:
    """The file's modification time and size, which differ when it was written since."""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size
