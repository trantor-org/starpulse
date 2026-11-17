"""The one-time move of a task's key label to its `source`, run by `starpulse migrate`.

A task carrying a label that fully matches the board's `source_labels` pattern and holding no `source` has that label
moved to `source`. A task whose `source` is set, or that carries more than one such label, is left alone and reported.
Nothing else in the task file changes, and a second run finds no label to move.
"""

import logging
import os
import re
from pathlib import Path

import yaml

from starpulse.board.adapters.native_scan import _FOLDERS, _split

__all__ = ["move_key_labels"]

logger = logging.getLogger(__name__)


def move_key_labels(root: Path, pattern: str) -> int:
    """Move each task's key label under `root` to its `source`; how many tasks moved."""
    key = re.compile(pattern)
    moved = 0
    for folder, _settled in _FOLDERS:
        for path in sorted((root / folder).glob("*.md")):
            moved += _move(path, key)
    return moved


def _move(path: Path, key: re.Pattern[str]) -> bool:
    text = path.read_text()
    frontmatter, body = _split(text)
    if not isinstance(frontmatter, dict) or not isinstance(frontmatter.get("labels"), list):
        return False
    keys = [label for label in frontmatter["labels"] if isinstance(label, str) and key.fullmatch(label)]
    if not keys:
        return False
    if frontmatter.get("source") or len(keys) > 1:
        logger.info("migrate: %s keeps its labels: %s", path.name, "source already set" if frontmatter.get("source") else "several key labels")
        return False
    kept = [label for label in frontmatter["labels"] if label != keys[0]]
    frontmatter = {**frontmatter, "labels": kept, "source": keys[0]}
    if not kept:
        del frontmatter["labels"]
    scratch = path.with_name(f".{path.name}.migrating")
    scratch.write_text(f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---{body}")
    os.replace(scratch, path)
    logger.info("migrate: %s moved label %s to source", path.name, keys[0])
    return True
