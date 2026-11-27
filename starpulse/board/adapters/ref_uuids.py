"""The `uuids` front matter map of a task: the stored UUID of each board item its references name, beside the key.

The string lists (`dependencies`, `references`, `documentation`) and the scalars (`milestone`, `follows`) keep naming
items by key, so every reader stays on keys until it moves to the UUID; the map is the second reference the move needs.
A key no item holds has no entry.
"""

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from starpulse.board.adapters import native_docs, native_milestones
from starpulse.board.adapters.native_scan import _strings

_LISTS = ("dependencies", "references", "documentation")
_SCALARS = ("milestone", "follows")
_KEY = re.compile(r"[A-Za-z][A-Za-z0-9]*-\d+")
_DOC = re.compile(r"doc-\d+")
_MILESTONE = re.compile(r"m-\d+")


def _named(frontmatter: Mapping[str, Any]) -> list[str]:
    """The keys the front matter's reference fields name, in order, each once. A `documentation` entry is a file path
    that names its doc by the id its file name starts with; a `TASK-5#2` dependency names `TASK-5`."""
    entries = [
        entry.partition("#")[0].strip() for field in (*_LISTS, *_SCALARS) for entry in _strings(frontmatter.get(field))
    ]
    named = [found.group(0) if (found := _DOC.match(Path(entry).name)) else entry for entry in entries]
    return list(dict.fromkeys(key for key in named if _KEY.fullmatch(key)))


def _uuid_of(root: Path, key: str, tasks: Callable[[str], str]) -> str:
    if _DOC.fullmatch(key):
        found = native_docs._find(root, key)
        front = found[2] if found else None
    elif _MILESTONE.fullmatch(key):
        found = native_milestones._find(root, key)
        front = found[1] if found else None
    else:
        return tasks(key)
    return str(front.get("uuid") or "") if isinstance(front, dict) else ""


def stamp(root: Path, frontmatter: dict, tasks: Callable[[str], str]) -> None:
    """Set `frontmatter`'s `uuids` to the UUID of each item it names: one it holds already is kept, a new key is looked
    up under `root` (a task's by `tasks`, from its History), and a key it no longer names is dropped."""
    kept = frontmatter.get("uuids")
    kept = kept if isinstance(kept, dict) else {}
    uuids = {key: found for key in _named(frontmatter) if (found := kept.get(key) or _uuid_of(root, key, tasks))}
    if uuids:
        frontmatter["uuids"] = uuids
    else:
        frontmatter.pop("uuids", None)
