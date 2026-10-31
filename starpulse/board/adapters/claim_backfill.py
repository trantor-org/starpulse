"""One-shot backfill: each task file's last claim marker becomes its frontmatter `assignee` (and `released_from`).

    python -m starpulse.board.adapters.claim_backfill <board root>

The notes keep their markers, a file whose field is set or that holds no marker is not touched, and `updated_date` stays,
so a second run changes nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from starpulse.board.adapters.native import _ATTEMPTS, _STALE, _land, _split
from starpulse.board.model.claims import assignee_of, released_from
from starpulse.board.model.guard import Guard

__all__ = ["backfill"]

_FOLDERS = ("tasks", "completed", "archive/tasks")


def _filled(frontmatter: dict, body: str) -> bool:
    """Set the claim fields `body`'s markers name and `frontmatter` lacks, and say whether any was set."""
    found = {"assignee": assignee_of({}, body), "released_from": released_from({}, body)}
    missing = {key: value for key, value in found.items() if value and key not in frontmatter}
    frontmatter |= missing
    return bool(missing)


def _backfilled(path: Path) -> bool:
    """Fill `path`'s claim fields from its notes and say so; a file another writer changed meanwhile is read again."""
    for _ in range(_ATTEMPTS):
        before = path.read_text()
        frontmatter, body = _split(before)
        if not isinstance(frontmatter, dict) or not _filled(frontmatter, body):
            return False
        if _land(path, before, frontmatter, body, Guard(), "backfill") is None:
            return True
    raise RuntimeError(f"{path}: {_STALE.output}")


def backfill(root: Path) -> int:
    """Fill the claim fields of every task file under `root`'s `tasks`, `completed` and `archive/tasks`; the number changed."""
    return sum(_backfilled(path) for folder in _FOLDERS for path in sorted((root / folder).glob("*.md")))


if __name__ == "__main__":
    print(f"backfilled {backfill(Path(sys.argv[1]))} task files")
