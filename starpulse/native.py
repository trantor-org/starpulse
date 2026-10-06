"""StarPulse's own board: one Markdown file per task under `.starpulse/board/`, written in Python.

The files use the front matter Backlog.md's tasks use, so `starpulse.upstream_backlog` reads them: the lanes are the
`statuses` of `config.yml` and a task is a file under `tasks/`. This adapter adds what that one lacks, a writer that
edits the files with no `backlog` CLI, and creates the board, empty, when its directory is absent. It is the default
`[board]` adapter.
"""

from __future__ import annotations

import os
import re
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from starpulse.board import Board, MoveWriter, TaskCreator, Written
from starpulse.upstream_backlog import (
    _FOLDERS,
    DEFAULT_PREFIX,
    DEFAULT_STATUSES,
    BacklogConfig,
    _split,
    lane_id,
    project_board,
)

#: Where the board lives, relative to the config's directory (or the working directory without a config).
DEFAULT_PATH = ".starpulse/board"
#: The `[board]` settings this adapter reads: `path` is the board's directory, `machine` a machine file for the Board,
#: relative to the config.
_SETTINGS = {"type", "path", "interval", "machine"}
_NOTES_END = re.compile(r"\s*<!-- SECTION:NOTES:END -->")
_NOTES_SECTION = "\n## Implementation Notes\n\n<!-- SECTION:NOTES:BEGIN -->\n{}\n<!-- SECTION:NOTES:END -->\n"


def _create(root: Path) -> None:
    """Make an empty board in `root` when it is absent: the default lanes and a `tasks/` directory, nothing else."""
    if not root.exists():
        (root / "tasks").mkdir(parents=True)
        (root / "config.yml").write_text(
            yaml.safe_dump({"statuses": list(DEFAULT_STATUSES), "task_prefix": DEFAULT_PREFIX}, sort_keys=False)
        )


def _find(root: Path, task: str) -> Path | None:
    """The file under `tasks/` whose front matter holds `id: <task>`."""
    for path in sorted((root / "tasks").glob("*.md")):
        try:
            frontmatter, _ = _split(path.read_text())
        except OSError:
            continue  # moved or removed while looking
        if isinstance(frontmatter, dict) and str(frontmatter.get("id") or "").strip() == task:
            return path
    return None


def _update(root: Path, task: str, edit: Callable[[dict, str], str]) -> Written:
    """Rewrite the file of `task` with its front matter edited in place and its body as `edit` returns it."""
    if (path := _find(root, task)) is None:
        return Written(False, f"{task} has no task file in {root / 'tasks'}")
    try:
        frontmatter, body = _split(path.read_text())
        body = edit(frontmatter, body)
        scratch = path.with_name(f"{path.name}.tmp")  # not a `.md` file, so a scan never reads it half written
        scratch.write_text(f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---{body}")
        os.replace(scratch, path)
    except OSError as error:
        return Written(False, f"{path}: {error}")
    return Written(True, f"Updated task {task}")


def _holder(body: str, session: str) -> str:
    """`body` with `**Holder:** <session>` appended to its notes, which the board reads the holder from."""
    line = f"**Holder:** {session}"
    if _NOTES_END.search(body):
        return _NOTES_END.sub(lambda end: f"\n{line}{end.group()}", body, count=1)
    return body.rstrip("\n") + "\n" + _NOTES_SECTION.format(line)


def _writer(root: Path, statuses: tuple[str, ...]) -> MoveWriter:
    """A board writer that sets a status in the task's file. A lane's status is the board's own spelling of it.

    An agent's claim (a move to `In Progress` that names its session) also records the session as the task's holder.
    """
    spelled = {lane_id(status): status for status in statuses}

    def write(task: str, status: str, actor: str, session: str = "") -> Written:
        claim = actor != "operator" and session and lane_id(status) == "in_progress"

        def edit(frontmatter: dict, body: str) -> str:
            frontmatter["status"] = spelled.get(lane_id(status), status)
            return _holder(body, session) if claim else body

        return _update(root, task, edit)

    return write


def _next_id(root: Path, prefix: str) -> str:
    """`<prefix>-N` with N one past the highest on the board, its completed and archived tasks included."""
    number = re.compile(rf"{re.escape(prefix)}-(\d+)", re.I)
    highest = 0
    for folder, _ in _FOLDERS:
        for path in (root / folder).glob("*.md"):
            try:
                frontmatter, _ = _split(path.read_text())
            except OSError:
                continue  # moved or removed while looking
            if isinstance(frontmatter, dict) and (found := number.fullmatch(str(frontmatter.get("id") or "").strip())):
                highest = max(highest, int(found[1]))
    return f"{prefix}-{highest + 1}"


def _creator(root: Path, config: BacklogConfig) -> TaskCreator:
    """A board writer that makes a task file in the first lane with the next id, `<id> - <title as a slug>.md`."""
    lock = threading.Lock()  # two creates must not both read the same highest id

    def create(title: str, /) -> Written:
        with lock:
            task = _next_id(root, config.prefix)
            slug = re.sub(r"[^\w-]+", "-", title).strip("-")[:60].strip("-") or "Task"
            path = root / "tasks" / f"{task} - {slug}.md"
            scratch = path.with_name(f"{path.name}.tmp")  # not a `.md` file, so a scan never reads it half written
            frontmatter = {"id": task, "title": title, "status": config.statuses[0]}
            try:
                scratch.write_text(f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---\n")
                os.replace(scratch, path)
            except OSError as error:
                return Written(False, f"{path}: {error}")
        return Written(True, task)

    return create


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The native board at `settings["path"]` (default `.starpulse/board`), created empty when absent, polled every `interval` seconds.

    Moves, assignee changes and creates write the task files directly. Any lane reaches any other unless `machine` names a
    machine file, whose transitions and `writers` then decide which moves are offered, and to whom.
    """
    if unknown := sorted(settings.keys() - _SETTINGS):
        raise ValueError(f"board: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_SETTINGS))}")
    root = base / str(settings.get("path", DEFAULT_PATH))
    _create(root)

    def assign(task: str, assignee: str, /) -> Written:
        def edit(frontmatter: dict, body: str) -> str:
            frontmatter["assignee"] = [assignee]
            return body

        return _update(root, task, edit)

    return project_board(
        root,
        settings,
        base,
        lambda config: {"writer": _writer(root, config.statuses), "assign": assign, "create": _creator(root, config)},
    )
