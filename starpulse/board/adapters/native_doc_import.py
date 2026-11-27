"""Index the doc files a board holds, and list where the files and the index disagree.

A doc file is `doc-<N> - <title>.<extension>` under `docs/` or `archive/docs/`, of any type: a Markdown file counts when
its front matter names an `id`, so a README or an attachment is no doc. The board imports at attach, so a file added on
disk between starts is indexed at the next one and listed by `check` until then.
"""

import os
import re
from pathlib import Path

from starpulse.board.adapters import native_docs
from starpulse.board.adapters.native_doc_index import DocIndex, Entry

_DOC = re.compile(r"(doc-\d+) - (.+)\.([A-Za-z0-9]+)")


def _entry(root: Path, path: str, name: str, stat: os.stat_result) -> Entry | None:
    if (found := _DOC.fullmatch(name)) is None or found[3] == "tmp":  # a `.tmp` file is a write in flight
        return None
    if found[3].lower() != "md":
        return Entry(os.path.relpath(path, root), found[1], found[2], "other")
    try:
        parsed = native_docs._parsed(Path(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None  # moved or removed while looking
    if parsed is None:
        return None
    front = parsed[1]
    return Entry(os.path.relpath(path, root), str(front["id"]).strip(), str(front.get("title") or ""), str(front.get("type") or "other"))


def _found(root: Path) -> dict[str, Entry]:
    """Each doc file under `docs/` and `archive/docs/`, by its path relative to `root`."""
    found: dict[str, Entry] = {}
    pending = [str(root / "docs"), str(root / "archive" / "docs")]
    while pending:
        try:
            with os.scandir(pending.pop()) as entries:
                for item in entries:
                    if item.is_dir(follow_symlinks=False):
                        pending.append(item.path)
                    elif entry := _entry(root, item.path, item.name, item.stat()):
                        found[entry.path] = entry
        except OSError:
            continue  # absent, or moved or removed while looking
    return found


def import_files(root: Path, index: DocIndex) -> int:
    """Give every doc file with no row its row, leaving the rows there alone: how many rows were added."""
    held = {entry.path for entry in index.entries()}
    new = [entry for path, entry in _found(root).items() if path not in held]
    index.put(new)
    return len(new)


def check(root: Path, index: DocIndex) -> tuple[list[str], list[str]]:
    """The doc files with no row and the rows with no file, as paths relative to `root`, each sorted."""
    found, held = set(_found(root)), {entry.path for entry in index.entries()}
    return sorted(found - held), sorted(held - found)
