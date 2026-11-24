"""The parity of a board's files with its Task History: which tasks have no History, and which
replay to a rendering that differs from their file's.

A task's file and its replayed row are compared through `markdown.render`, plus the columns the rendering omits: the
meta (start criteria by their authored fields only), the assignee, the comments' text and whether the task is archived."""

import difflib
import hashlib
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
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

__all__ = ["Filed", "Parity", "Pending", "Replays", "align_claims", "check", "filed", "import_missing", "pending", "scanned"]

Record = Mapping[str, Any]
_SHOWN = 6


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


class Pending(NamedTuple):
    """The tasks a migrate must check, and the ledger it leaves: `{key: [digest, task, version]}`, the file (or retired
    row) text's digest and the task's History version when it was read."""

    files: list[Filed]
    retired: list[Filed]
    ledger: dict[str, list[Any]]

    @property
    def items(self) -> list[Filed]:
        return [*self.files, *self.retired]


def pending(root: Path, engine: Engine, checked: Mapping[str, Sequence[Any]]) -> Pending:
    """The files under `root` and the retired tasks of the store that `checked` (a former run's ledger) does not vouch for: a
    task whose text and History version both match its entry is in parity, so it is neither parsed nor replayed."""
    versions = EventStore(engine).heads(KIND)
    files: list[Filed] = []
    retired: list[Filed] = []
    ledger: dict[str, list[Any]] = {}
    held: set[str] = set()

    def keep(key: str, text: str, make: Callable[[str], Filed], out: list[Filed]) -> None:
        digest = hashlib.sha256(text.encode()).hexdigest()
        if (old := checked.get(key)) and old[0] == digest and versions.get(old[1], 0) == old[2]:
            held.add(old[1])
            ledger[key] = list(old)
            return
        item = make(text)
        held.add(item.task)
        ledger[key] = [digest, item.task, versions.get(item.task, 0)]
        out.append(item)

    for folder, settled in _FOLDERS:
        for path in sorted((root / folder).glob("*.md")):
            keep(f"{folder}/{path.name}", path.read_text(), partial(_in_folder, path.stem, settled is not None), files)
    store = _Retired()
    store.engine = engine
    for task, text in store.pairs():
        if task not in held:  # a file holding the id outranks an old row of another task
            keep(f"retired/{task}", text, partial(_retired, task), retired)
    return Pending(files, retired, ledger)


class Replays:
    """Each task's History replayed once, `{}` for a task with none, until the caller that appended to it drops it (`drop`; no task drops all)."""

    def __init__(self, engine: Engine) -> None:
        self._store = EventStore(engine)
        self._rows: dict[str, dict[str, Any]] = {}

    def row(self, task: str) -> dict[str, Any]:
        if (row := self._rows.get(task)) is None:
            row = self._rows[task] = replay(self._store.read(KIND, task))
        return row

    def drop(self, task: str | None = None) -> None:
        if task is None:
            self._rows.clear()
        else:
            self._rows.pop(task, None)


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
    found += [f"{name}: file {a!r}, replay {b!r}" for name, a, b in zip(names, ours[1:], theirs[1:], strict=True) if a != b]
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


def import_missing(items: Iterable[Filed], engine: Engine) -> list[str]:
    """Give each of `items` without History its `TaskImported`; the tasks that got one."""
    history = TaskHistory()
    history.attach(engine)
    return [item.task for item in items if history.imported(item.task, item.record, item.archived)]


def align_claims(items: Iterable[Filed], engine: Engine, rows: Replays | None = None) -> list[str]:
    """Set the claim of each of `items` whose History holds another to its file's, a `FieldsEdited` of `assignee`; the tasks that got one."""
    history = TaskHistory()
    history.attach(engine)
    rows = rows or Replays(engine)
    aligned = []
    for item in items:
        held = item.record.get("assignee") or ""
        if (row := rows.row(item.task)) and row["assignee"] != held:
            history.edited(item.task, {"changes": {"assignee": held}})
            rows.drop(item.task)
            aligned.append(item.task)
    return aligned
