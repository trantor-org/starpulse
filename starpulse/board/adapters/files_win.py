"""The one-time bring of each differing task's History to its file, run by `starpulse migrate` with `[board] files_win`:
the file wins every own field, criterion and lane, as `FieldsEdited`, `Criterion*` and `Transitioned` Events appended to
the History. A task whose rendering matches, or that differs only in its meta, claim or comments, is left alone, and so is
one without History (`starpulse parity --import`); no file is rewritten."""

from collections.abc import Iterable

from sqlalchemy import Engine

from starpulse.board.adapters.task_history import _META, KIND, TaskHistory
from starpulse.board.adapters.task_parity import Filed, _replayed
from starpulse.board.model.markdown import render
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore

__all__ = ["bring_to_files"]


def bring_to_files(items: Iterable[Filed], engine: Engine) -> int:
    """Append to each of `items` whose History replays differently from its file the Events that bring it to the file; how many got any."""
    store, history = EventStore(engine), TaskHistory()
    history.attach(engine)
    brought = 0
    for item in items:
        events = store.read(KIND, item.task)
        if not events:
            continue
        held = _replayed(replay(events))
        if render(item.record) == render(held):
            continue
        shown = {**item.record, **{key: held[key] for key in _META}, "comments": held["comments"], "assignee": None}
        brought += history.brought_to(item.task, {**held, "assignee": None}, shown)
    return brought
