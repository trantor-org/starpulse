"""The one-time bring of each differing task's History to its file, run by `starpulse migrate` with `[board] files_win`:
the file wins every own field, criterion and lane, as `FieldsEdited`, `Criterion*` and `Transitioned` Events appended to
the History. A task whose rendering matches, or that differs only in its meta, claim or comments, is left alone, and so is
one without History (`starpulse parity --import`); no file is rewritten."""

from collections.abc import Iterable

from sqlalchemy import Engine

from starpulse.board.adapters.task_history import _META, TaskHistory
from starpulse.board.adapters.task_parity import Filed, Replays, _replayed
from starpulse.board.model.markdown import render

__all__ = ["bring_to_files"]


def bring_to_files(items: Iterable[Filed], engine: Engine, rows: Replays | None = None) -> int:
    """Append to each of `items` whose History replays differently from its file the Events that bring it to the file; how many got any."""
    history = TaskHistory()
    history.attach(engine)
    rows = rows or Replays(engine)
    brought = 0
    for item in items:
        if not (row := rows.row(item.task)):
            continue
        held = _replayed(row)
        if render(item.record) == render(held):
            continue
        shown = {**item.record, **{key: held[key] for key in _META}, "comments": held["comments"], "assignee": None}
        if history.brought_to(item.task, {**held, "assignee": None}, shown):
            rows.drop(item.task)
            brought += 1
    return brought
