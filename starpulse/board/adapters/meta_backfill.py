"""The one-time backfill of task meta the files carry and the History lacks, run by `starpulse migrate`: one
`FieldsEdited` per task recording the file's `needsAttention`, `source`, `profile` and authored start criteria. The file
wins, bar an empty `source`, which only a History-side label move leaves; a start criterion differing only by an evaluator's status fields counts as agreeing. A task without History is
first imported. The task file is not rewritten."""

import logging
from pathlib import Path

from sqlalchemy import Engine

from starpulse.board.adapters.task_history import KIND, TaskHistory
from starpulse.board.adapters.task_parity import filed
from starpulse.board.model import criteria
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore

__all__ = ["backfill_meta"]

logger = logging.getLogger(__name__)

_KEYS = ("needsAttention", "source", "profile", "start_criteria")


def backfill_meta(root: Path, engine: Engine) -> int:
    """Record each task's file meta in the History `engine` holds where it differs; how many tasks got an edit."""
    store, history = EventStore(engine), TaskHistory()
    history.attach(engine)
    edited = 0
    for item in filed(root, engine):
        history.imported(item.task, item.record, item.archived)
        held = replay(store.read(KIND, item.task))["meta"]
        held["start_criteria"] = criteria.bare(held.get("start_criteria") or [])
        file = item.record
        # an empty `source` is a key label `move_key_labels` moved in the History only
        changes = {key: file.get(key) or None for key in _KEYS if (file.get(key) or None) != (held.get(key) or None) and (key != "source" or file.get(key))}
        if changes:
            history.edited(item.task, {"meta": changes})
            logger.info("migrate: %s meta recorded: %s", item.task, ", ".join(changes))
            edited += 1
    return edited
