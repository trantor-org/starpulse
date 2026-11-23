"""The one-time match of each task's History to its file's archive state, run by `starpulse migrate`: an `Archived` for a
file that has left the lanes, a `Rehydrated` for a file in them whose History is archived (a reopen before the one that
recorded it), and for a task without History its import. The file wins; no file is rewritten."""

import logging
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import Engine

from starpulse.board.adapters.task_history import TaskHistory
from starpulse.board.adapters.task_parity import Filed, Replays, scanned

__all__ = ["settle_archived"]

logger = logging.getLogger(__name__)


def settle_archived(
    root: Path, engine: Engine, scan: Iterable[Filed] | None = None, rows: Replays | None = None
) -> int:
    """Match to its file's folder the archive state of each task under `root` (`scan`, when the caller already read them) in the History `engine` holds; how many changed."""
    history = TaskHistory()
    history.attach(engine)
    rows = rows or Replays(engine)
    changed = 0
    for item in scanned(root) if scan is None else scan:
        row = rows.row(item.task)
        if not row:
            done = history.imported(item.task, item.record, item.archived)
        else:
            done = row["archived"] != item.archived and history.settle(item.task, item.archived)
        if done:
            rows.drop(item.task)
            logger.info("migrate: %s matched in its History to its folder (archived: %s)", item.task, item.archived)
            changed += 1
    return changed
