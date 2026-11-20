"""The one-time match of each task's History to its file's archive state, run by `starpulse migrate`: an `Archived` for a
file that has left the lanes, a `Rehydrated` for a file in them whose History is archived (a reopen before the one that
recorded it), and for a task without History its import. The file wins; no file is rewritten."""

import logging
from pathlib import Path

from sqlalchemy import Engine

from starpulse.board.adapters.native import _record_of
from starpulse.board.adapters.native_scan import _FOLDERS
from starpulse.board.adapters.task_history import TaskHistory

__all__ = ["settle_archived"]

logger = logging.getLogger(__name__)


def settle_archived(root: Path, engine: Engine) -> int:
    """Match to its file's folder the archive state of each task under `root` in the History `engine` holds; how many changed."""
    history = TaskHistory()
    history.attach(engine)
    changed = 0
    for folder, settled in _FOLDERS:
        for path in sorted((root / folder).glob("*.md")):
            record = _record_of(path.read_text())
            task = record["id"] or path.stem
            if history.imported(task, record, settled is not None) or history.settle(task, settled is not None):
                logger.info("migrate: %s matched in its History to its folder %s", path.name, folder)
                changed += 1
    return changed
