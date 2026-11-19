"""The one-time move of a task's key label to its `source`, run by `starpulse migrate`: a `FieldsEdited` in the task's
History, which a task without one is first imported into. The task file is not rewritten; the StarPulse
Operations doc's Board Lane Disagrees With the Task File section holds the contract."""

import logging
import re
from pathlib import Path

from sqlalchemy import Engine

from starpulse.board.adapters.native import _record_of
from starpulse.board.adapters.native_scan import _FOLDERS
from starpulse.board.adapters.task_history import KIND, TaskHistory
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore

__all__ = ["move_key_labels"]

logger = logging.getLogger(__name__)


def move_key_labels(root: Path, pattern: str, engine: Engine) -> int:
    """Move each task's key label under `root` to its `source` in the History `engine` holds; how many tasks moved."""
    key = re.compile(pattern)
    store, history = EventStore(engine), TaskHistory()
    history.attach(engine)
    moved = 0
    for folder, settled in _FOLDERS:
        for path in sorted((root / folder).glob("*.md")):
            record = _record_of(path.read_text())
            if not any(key.fullmatch(label) for label in record["labels"]):
                continue
            task = record["id"] or path.stem
            history.imported(task, record, settled is not None)
            row = replay(store.read(KIND, task))
            keys = [label for label in row["labels"] if key.fullmatch(label)]
            if not keys:
                continue
            if row["meta"].get("source") or len(keys) > 1:
                logger.info("migrate: %s keeps its labels: %s", path.name, "source already set" if row["meta"].get("source") else "several key labels")
                continue
            kept = [label for label in row["labels"] if label != keys[0]]
            history.edited(task, {"changes": {"labels": kept}, "meta": {"source": keys[0]}})
            logger.info("migrate: %s moved label %s to source", path.name, keys[0])
            moved += 1
    return moved
