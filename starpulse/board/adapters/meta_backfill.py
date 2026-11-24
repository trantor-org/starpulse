"""The one-time backfill of task meta the files carry and the History lacks, run by `starpulse migrate`: one
`FieldsEdited` per task recording the file's `needsAttention`, `source`, `profile`, authored start criteria, `follows`, `dependencyNeeds`, `actorMemory`, `createdBy` and `aliases`, and the comment stamps an import left unrecorded. The file
wins, bar an empty `source`, which only a History-side label move leaves; a start criterion differing only by an evaluator's status fields counts as agreeing. A task without History is
first imported. The task file is not rewritten."""

import logging
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import Engine

from starpulse.board.adapters.task_history import TaskHistory
from starpulse.board.adapters.task_parity import Filed, Replays, filed
from starpulse.board.model import criteria

__all__ = ["backfill_meta"]

logger = logging.getLogger(__name__)

_KEYS = (
    "needsAttention",
    "source",
    "profile",
    "start_criteria",
    "follows",
    "dependencyNeeds",
    "actorMemory",
    "createdBy",
    "aliases",
)


def _stamped(held: list[dict], file: list[dict]) -> list[dict] | None:
    """The History's comments with the file's `created` stamps, when some lack one and the two agree on every text."""
    if len(held) != len(file) or any(a["text"] != b.get("text") for a, b in zip(held, file, strict=True)):
        return None
    if all(item.get("created") for item in held):
        return None
    return [{**item, "created": item.get("created") or mine.get("created", "")} for item, mine in zip(held, file, strict=True)]


def backfill_meta(
    root: Path, engine: Engine, items: Iterable[Filed] | None = None, rows: Replays | None = None
) -> int:
    """Record each task's file meta (`items`, when the caller already read them) in the History `engine` holds where it differs; how many tasks got an edit."""
    history = TaskHistory()
    history.attach(engine)
    rows = rows or Replays(engine)
    edited = 0
    for item in filed(root, engine) if items is None else items:
        if not rows.row(item.task) and history.imported(item.task, item.record, item.archived):
            rows.drop(item.task)
        held = dict(rows.row(item.task)["meta"])
        held["start_criteria"] = criteria.bare(held.get("start_criteria") or [])
        file = item.record
        # an empty `source` is a key label `move_key_labels` moved in the History only
        changes = {key: file.get(key) or None for key in _KEYS if (file.get(key) or None) != (held.get(key) or None) and (key != "source" or file.get(key))}
        stamped = _stamped(rows.row(item.task)["comments"], list(file.get("comments") or []))
        if changes or stamped:
            history.edited(item.task, {"meta": changes, **({"changes": {"comments": stamped}} if stamped else {})})
            rows.drop(item.task)
            logger.info("migrate: %s meta recorded: %s", item.task, ", ".join([*changes, *(["comments"] if stamped else [])]))
            edited += 1
    return edited
