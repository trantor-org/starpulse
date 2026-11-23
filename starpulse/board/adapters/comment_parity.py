"""The one-time bringing of each task's comments in its file and in its History to one list, run by `starpulse migrate`.

The list holds the file's text (the archive verb's `Archived: ` prefix is the file's), History's order, and every note
either side held alone: a note only History holds goes to the file with its time and actor, and one only the file holds
to History as one `FieldsEdited` of the whole list, since a comment's text can be set no other way. The StarPulse
Operations doc's Board Lane Disagrees With the Task File section holds the contract."""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, select, update
from sqlalchemy.dialects import sqlite

from starpulse.board.adapters.native import _COMMENTS_SECTION, _STAMP, _record_of, _Retired
from starpulse.board.adapters.native_scan import _FOLDERS
from starpulse.board.adapters.task_history import KIND, TaskHistory
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore
from starpulse.event_log.tables import retired_tasks, settings

__all__ = ["reconcile_comments"]

logger = logging.getLogger(__name__)

_PREFIX = "Archived: "
#: The setting that records the reconcile done, so a later migrate walks no task: a boot check rehearses migrate on a copy.
_RECONCILED = "comment_parity_reconciled"
_CLOCK = ZoneInfo("America/Phoenix")
_Entry = dict[str, Any]


def _stamped(created: str) -> float:
    try:
        return datetime.strptime(created, _STAMP).replace(tzinfo=_CLOCK).timestamp()
    except ValueError:
        return 0.0


def _merged(filed: list[dict[str, str]], held: list[dict[str, Any]]) -> list[_Entry]:
    """The comments of `filed` (a file's) and `held` (a History's) as one list: History's order, the file's text, and each
    file-only note after the entry the file lists before it."""
    free = list(range(len(filed)))
    pairs: dict[int, int] = {}
    for i, note in enumerate(held):
        for text in (note["text"], _PREFIX + note["text"]):
            if (found := next((j for j in free if filed[j]["text"] == text), None)) is not None:
                pairs[i] = found
                free.remove(found)
                break
    after: dict[int, list[int]] = {}
    for j in free:
        anchor = max((i for i, matched in pairs.items() if matched < j), default=-1)
        after.setdefault(anchor, []).append(j)
    entries = [_filed(filed[j]) for j in after.get(-1, [])]
    for i, note in enumerate(held):
        entries.append(_held(note, filed[pairs[i]]["text"] if i in pairs else note["text"]))
        entries += [_filed(filed[j]) for j in after.get(i, [])]
    return entries


def _filed(note: dict[str, str]) -> _Entry:
    return {"text": note["text"], "at": _stamped(note["created"]), "actor": note.get("author", "")}


def _held(note: dict[str, Any], text: str) -> _Entry:
    return {"text": text, "at": note["at"], "actor": note["actor"]}


def _rendered(entries: list[_Entry], filed: list[dict[str, str]]) -> str:
    """`entries` as a file's comment entries, each of the file's own keeping its stamp and author."""
    kept = {note["text"]: note for note in filed}
    out = []
    for entry in entries:
        own = kept.get(entry["text"])
        created = own["created"] if own else datetime.fromtimestamp(entry["at"], _CLOCK).strftime(_STAMP)
        author = own.get("author", "") if own else entry["actor"]
        out.append(f"created: {created}\n{f'author: {author}\n' if author else ''}---\n{entry['text']}\n---\n\n")
    return "".join(out)


def _with_comments(text: str, block: str) -> str:
    if _COMMENTS_SECTION.search(text):
        return _COMMENTS_SECTION.sub(lambda _: f"<!-- COMMENTS:BEGIN -->\n{block}<!-- COMMENTS:END -->", text, count=1)
    return text.rstrip("\n") + f"\n\n## Comments\n\n<!-- COMMENTS:BEGIN -->\n{block}<!-- COMMENTS:END -->\n"


def _brought(task: str, text: str, archived: bool, history: TaskHistory, store: EventStore) -> tuple[str, bool]:
    """`text` (a task's file, or its retired row) with the comments its History holds alone, and whether the History
    took the comments the file holds alone or the file's text."""
    record = _record_of(text)
    history.imported(task, record, archived)
    held = replay(store.read(KIND, task))["comments"]
    filed = record["comments"]
    entries = _merged(filed, held)
    texts = [entry["text"] for entry in entries]
    in_history = texts != [note["text"] for note in held]
    if in_history:
        history.edited(task, {"changes": {"comments": entries}})
    if texts != [note["text"] for note in filed]:
        text = _with_comments(text, _rendered(entries, filed))
    return text, in_history


def reconcile_comments(root: Path, engine: Engine, *, rehearsing: bool = False) -> int:
    """Bring each task file under `root`, each retired task's row and its History to one comment list; how many tasks
    changed on either side.

    A task without History is first imported, as `move_key_labels` does. It runs once per store: a later call finds
    `_RECONCILED` set and changes nothing, and a `rehearsing` run, which migrates a copy the live store never gets back, skips
    it."""
    with engine.connect() as db:
        if rehearsing or db.execute(select(settings.c.key).where(settings.c.key == _RECONCILED)).first():
            return 0
    store, history = EventStore(engine), TaskHistory()
    history.attach(engine)
    changed = 0
    for folder, settled in _FOLDERS:
        for path in sorted((root / folder).glob("*.md")):
            text = path.read_text()
            task = _record_of(text)["id"] or path.stem
            brought, in_history = _brought(task, text, settled is not None, history, store)
            if brought != text:
                scratch = path.with_name(f".{path.name}.comments")
                scratch.write_text(brought)
                os.replace(scratch, path)
            if brought != text or in_history:
                logger.info("migrate: %s comments reconciled (file %s, history %s)", path.name, brought != text, in_history)
                changed += 1
    retired = _Retired()
    retired.engine = engine
    for task, text in retired.pairs():
        brought, in_history = _brought(task, text, True, history, store)
        if brought != text:
            with engine.begin() as db:
                db.execute(update(retired_tasks).where(retired_tasks.c.task == task).values(text=brought))
        if brought != text or in_history:
            logger.info("migrate: retired %s comments reconciled (row %s, history %s)", task, brought != text, in_history)
            changed += 1
    now = time.time()
    with engine.begin() as db:
        db.execute(
            sqlite.insert(settings).values(key=_RECONCILED, value=True, updated_at=now).on_conflict_do_nothing()
        )
    return changed
