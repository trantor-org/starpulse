"""The UUID every board item stores beside its key: a v7 minted at create, a v5 of (board, key) for what existed before.

`stamp_files` is the one-time backfill: it writes `uuid:` under the `id:` line of each board file that has none,
leaving every other byte as it was, so a second run changes nothing. Two files that share a key (the board has a few)
cannot share a UUID: the open one keeps the key's v5 and the other takes the v5 of its key and relative path."""

import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from starpulse.board.adapters.native_scan import _split
from starpulse.board.adapters.task_history import KIND, WRITER
from starpulse.board.model.seam import OPERATOR
from starpulse.event_log.readmodel.fold import replay
from starpulse.event_log.store import EventStore, NewEvent, StaleVersion

_TASK_FOLDERS = ("tasks", "completed", "archive/tasks")
_ID_LINE = re.compile(r"^id:.*$", re.M)


@dataclass
class Stamped:
    changed: list[Path] = field(default_factory=list)
    tasks: dict[str, str] = field(default_factory=dict)
    skipped: list[Path] = field(default_factory=list)


def mint() -> str:
    return str(uuid.uuid7())


def derive(board: str, key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"starpulse:{board}:{key}"))


def _is_task(relative: Path) -> bool:
    return any(relative.as_posix().startswith(f"{folder}/") for folder in _TASK_FOLDERS)


def _retired(relative: Path) -> bool:
    return relative.parts[0] in ("completed", "archive")


def stamp_files(root: Path, board: str) -> Stamped:
    """Give every file under `root` that names an `id:` and has no `uuid:` the v5 of `board` and its key."""
    found = []
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        text = path.read_bytes().decode()
        front, _ = _split(text)
        if not isinstance(front, dict) or not front.get("id"):
            found.append((path, relative, text, None, ""))
            continue
        key = str(front["id"])
        found.append((path, relative, text, front, key.upper() if _is_task(relative) else key))
    taken = {str(front["uuid"]) for *_, front, _ in found if front and front.get("uuid")}
    result = Stamped()
    for path, relative, text, front, key in sorted(found, key=lambda item: (_retired(item[1]), item[1])):
        if front is None:
            result.skipped.append(path)
            continue
        if stored := front.get("uuid"):
            minted = str(stored)
        else:
            minted = derive(board, key)
            if minted in taken:
                minted = derive(board, f"{key}:{relative.as_posix()}")
            taken.add(minted)
            head, divider, rest = text.partition("\n---")
            stamped = _ID_LINE.sub(lambda line: f"{line.group()}\nuuid: {minted}", head, count=1)
            path.write_bytes((stamped + divider + rest).encode())
            result.changed.append(path)
        if _is_task(relative):
            result.tasks.setdefault(key, minted)  # the open file is first: its UUID is the Task stream's
    return result


def stamp_history(store: EventStore, board: str, tasks: dict[str, str]) -> list[str]:
    """Append one `FieldsEdited` carrying the UUID to each Task stream that has none: the file's (`tasks`), else the v5 of
    (board, key). Returns the Tasks it stamped; a second run stamps none. A stream whose head moved since the read (a concurrent append) is read again."""
    stamped = []
    for task in store.heads(KIND):
        while events := store.read(KIND, task):
            if replay(events).get("meta", {}).get("uuid"):
                break
            change = NewEvent("FieldsEdited", {"meta": {"uuid": tasks.get(task) or derive(board, task)}}, OPERATOR, WRITER)
            try:
                store.append(KIND, task, events[-1].version, [change])
            except StaleVersion:
                continue
            stamped.append(task)
            break
    return stamped
