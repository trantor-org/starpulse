"""The parity of a board's files with its Task History: which tasks have no History, and which
replay to a rendering that differs from their file's.

A task's file and its replayed row are compared through `markdown.render`, plus the columns the rendering omits: the
meta (start criteria by their authored fields only), the assignee, the comments' text and whether the task is archived."""

import difflib
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import Engine

from starpulse.board.adapters.native import _Retired, _record_of
from starpulse.board.adapters.native_scan import _FOLDERS
from starpulse.board.adapters.task_history import KIND, TaskHistory, _replayed, seed
from starpulse.board.model import criteria
from starpulse.board.model.markdown import render
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore

__all__ = ["Filed", "Parity", "backfill_answers", "check", "filed", "import_missing", "scanned", "unfile"]

Record = Mapping[str, Any]
_SHOWN = 6
BATCH = 50
PAUSE_S = 1.0


class Filed(NamedTuple):
    """A task as the board holds it outside History: its record, and whether it has left the lanes (a completed,
    archived or retired task)."""

    task: str
    record: Record
    archived: bool


@dataclass
class Parity:
    checked: int = 0
    missing: list[str] = field(default_factory=list)
    differing: dict[str, list[str]] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not (self.missing or self.differing)


def _in_folder(stem: str, archived: bool, text: str) -> Filed:
    record = _record_of(text)
    return Filed(record["id"] or stem, record, archived)


def _retired(task: str, text: str) -> Filed:
    return Filed(task, _record_of(text), True)


def scanned(root: Path) -> Iterator[Filed]:
    """Every open, completed and archived task file under `root`."""
    for folder, settled in _FOLDERS:
        for path in sorted((root / folder).glob("*.md")):
            yield _in_folder(path.stem, settled is not None, path.read_text())


def unfile(root: Path) -> int:
    """Remove every file the open, completed and archived task folders under `root` hold, a leftover write included; the count removed."""
    paths = [path for folder, _ in _FOLDERS for path in sorted((root / folder).glob("*")) if path.is_file()]
    for path in paths:
        path.unlink()
    return len(paths)


def filed(root: Path, engine: Engine) -> Iterator[Filed]:
    """Every open, completed and archived task file under `root`, then every retired task of the store whose id no file holds."""
    held: set[str] = set()
    for item in scanned(root):
        held.add(item.task)
        yield item
    retired = _Retired()
    retired.engine = engine
    for task, text in retired.pairs():
        if task not in held:  # a file holding the id outranks an old row of another task
            yield _retired(task, text)


def _shown(record: Record, archived: bool) -> tuple[str, dict[str, Any], str, list[str], bool]:
    columns = seed(record, 0.0)
    meta = {key: value for key, value in columns["meta"].items() if value}
    if "start_criteria" in meta:
        meta["start_criteria"] = criteria.bare(meta["start_criteria"])
    texts = [item["text"] for item in record.get("comments") or []]
    return render(record), meta, columns["assignee"], texts, archived


def _differences(item: Filed, row: Record) -> list[str]:
    """What differs between `item`'s file and the replay of `row`: the differing rendering lines, then the other columns."""
    ours, theirs = _shown(item.record, item.archived), _shown(_replayed(row), bool(row["archived"]))
    if ours == theirs:
        return []
    lines = difflib.unified_diff(ours[0].splitlines(), theirs[0].splitlines(), "file", "replay", lineterm="", n=0)
    found = [line for line in lines if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    names = ("meta", "assignee", "comments", "archived")
    found += [
        f"{name}: file {a!r}, replay {b!r}" for name, a, b in zip(names, ours[1:], theirs[1:], strict=True) if a != b
    ]
    return found[:_SHOWN]


def check(items: Iterable[Filed], store: EventStore) -> Parity:
    """Each of `items` with no History, and each whose replay differs from its file."""
    report = Parity()
    for item in items:
        report.checked += 1
        events = store.read(KIND, item.task)
        if not events:
            report.missing.append(item.task)
        elif found := _differences(item, replay(events)):
            report.differing[item.task] = found
    return report


def _paced(wrote: Iterable[tuple[str, bool]], batch: int, pause: Callable[[float], None]) -> list[str]:
    """The tasks of `wrote` that got a write, pausing `PAUSE_S` after each `batch` writes so served reads proceed between them."""
    done: list[str] = []
    for task, written in wrote:
        if written:
            done.append(task)
            if len(done) % batch == 0:
                pause(PAUSE_S)
    return done


def import_missing(
    items: Iterable[Filed], engine: Engine, *, batch: int = BATCH, pause: Callable[[float], None] = time.sleep
) -> list[str]:
    """Give each of `items` without History its `TaskImported`, pausing after each `batch`; the tasks that got one."""
    history = TaskHistory()
    history.attach(engine)
    return _paced(((item.task, history.imported(item.task, item.record, item.archived)) for item in items), batch, pause)


def backfill_answers(
    items: Iterable[Filed], engine: Engine, *, batch: int = BATCH, pause: Callable[[float], None] = time.sleep
) -> list[str]:
    """Give each of `items` with a History the creation answers its file holds and the History lacks, pausing after each
    `batch`; the tasks that got them."""
    history = TaskHistory()
    history.attach(engine)
    return _paced(((item.task, history.backfilled(item.task, item.record)) for item in items), batch, pause)
