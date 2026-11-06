"""StarPulse's own board: one Markdown file per task under `.starpulse/board/`, written in Python.

The files use the front matter Backlog.md's tasks use, so `starpulse.board.adapters.upstream_backlog` reads them: the lanes are the
`statuses` of `config.yml` and a task is a file under `tasks/`. This adapter adds what that one lacks, a writer that
edits the files with no `backlog` CLI, and creates the board, empty, when its directory is absent. It is the default
`[board]` adapter.
"""

from __future__ import annotations

import fcntl
import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine

from starpulse.board import criteria
from starpulse.board.adapters import native_docs, native_milestones
from starpulse.board.adapters.task_history import TaskHistory, revises_plan
from starpulse.board.adapters.upstream_backlog import (
    _CRITERIA,
    _FOLDERS,
    _HEADED_DESCRIPTION,
    _ITEM,
    _NOTES,
    DEFAULT_PREFIX,
    DEFAULT_STATUSES,
    BacklogConfig,
    _description,
    _split,
    _strings,
    lane_id,
    project_board,
    read_config,
)
from starpulse.board.adapters.upstream_backlog import (
    _profile as _profile_of,
)
from starpulse.board.model import rules
from starpulse.board.model.claims import assignee_of, claimed, released
from starpulse.board.model.guard import Guard, Validate
from starpulse.contracts.tiers import DEFAULT_TIER, TIERS
from starpulse.board.model.seam import (
    ANONYMOUS,
    FLAGGED,
    HELD,
    MERGE_EVIDENCE,
    OPERATOR,
    Board,
    MoveWriter,
    RetiredImporter,
    RetiredProjector,
    RetiredReader,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskReleaser,
    TaskRestorer,
    TaskRetirer,
    Written,
)
from starpulse.event_log.lane_events import ARCHIVED, COMPLETED
from starpulse.event_log.tables import pull_requests, retired_tasks
from starpulse.machine_engine.model.state_roles import StateRoles

if TYPE_CHECKING:
    from starpulse.board.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog

#: Where the board lives, relative to the config's directory (or the working directory without a config).
DEFAULT_PATH = ".starpulse/board"
#: The `[board]` settings this adapter reads: `path` is the board's directory, `machine` a machine file for the Board,
#: relative to the config, `criteria` the command that evaluates a task's Start Criteria (`{id}` is the task's id),
#: `validate` the `module:function` that may refuse a task write before it lands, `python_path` the directories, relative
#: to the config, put at the front of `sys.path` before `validate` is imported, `guards` the record-level rules every
#: task write must satisfy (the `rules` module of `starpulse.board.model`), `task_file_name` the form of the name a created task's
#: file is written under (`_FILE_NAMES`), `types` the names a task's `type` may take (any when absent),
#: `proposal_prefix` the id prefix of a task created in the proposed lane (its own sequence, so a proposal takes no task
#: number; absent, a proposal is numbered like any task).
_SETTINGS = {
    "type",
    "path",
    "interval",
    "machine",
    "criteria",
    "holds",
    "unfinished",
    "parked",
    "released",
    "delivered",
    "returned",
    "verifying",
    "closed",
    "validate",
    "python_path",
    "guards",
    "task_file_name",
    "types",
    "default_profiles",
    "proposal_prefix",
}
#: The forms of a created task's file name: `title` is `<id> - <Title>.md`, as Backlog.md writes it (the default), `slug`
#: is `<id>-<slug>.md`, lowercase and space-free, its slug capped at `_SLUG_MAX` characters.
_FILE_NAMES = ("title", "slug")
_SLUG_MAX = 19
#: How many retired rows a scan reads at a time, so no more than a page of their text is in memory at once.
_RETIRED_PAGE = 200
#: A trailing ISO date survives the cap, uncounted: it tells one run of a recurring task from the next.
_SLUG_DATE = re.compile(r"-\d{4}-\d{2}-\d{2}$")
#: Function words a capped slug does not end on: `task-1-re-fit-the` says no more than `task-1-re-fit`.
_SLUG_STOPWORDS = frozenset(
    {"a", "an", "and", "at", "by", "for", "from", "in", "into", "of", "on", "onto", "or", "the", "to", "with"}
)
#: The stamps' format, read as UTC.
_STAMP = "%Y-%m-%d %H:%M"
_NOTES_END = re.compile(r"\s*<!-- SECTION:NOTES:END -->")
_PLAN = re.compile(r"<!-- SECTION:PLAN:BEGIN -->(.*?)<!-- SECTION:PLAN:END -->", re.S)
_DONE = re.compile(r"<!-- DOD:BEGIN -->(.*?)<!-- DOD:END -->", re.S)
_FINAL_SUMMARY = re.compile(r"<!-- SECTION:FINAL_SUMMARY:BEGIN -->(.*?)<!-- SECTION:FINAL_SUMMARY:END -->", re.S)
_COMMENTS_SECTION = re.compile(r"<!-- COMMENTS:BEGIN -->(.*?)<!-- COMMENTS:END -->", re.S)
_COMMENT_HEAD = re.compile(r"^created: (\S+ \S+)\n(?:author: (\S+)\n)?---\n", re.M)
_SESSION_LINK = re.compile(r"^\*\*Session Link:\*\* (?:local \w+ session `([^`]+)`|(\S+))", re.M)
_NOTES_SECTION = "\n## Implementation Notes\n\n<!-- SECTION:NOTES:BEGIN -->\n{}\n<!-- SECTION:NOTES:END -->\n"


def _create(root: Path, project: str) -> None:
    """Make an empty board in `root` when it is absent: the project it belongs to, the default lanes and a `tasks/` directory, nothing else.

    The board is built beside `root` and renamed into place, so a caller that finds `root` finds it whole; of concurrent first callers one rename lands and the rest discard their copy.
    """
    if root.exists():
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    built = Path(tempfile.mkdtemp(prefix=f".{root.name}-", dir=root.parent))
    try:
        (built / "tasks").mkdir()
        (built / "config.yml").write_text(
            yaml.safe_dump(
                {"project_name": project, "statuses": list(DEFAULT_STATUSES), "task_prefix": DEFAULT_PREFIX},
                sort_keys=False,
            )
        )
        built.rename(root)
    except OSError:
        if not root.exists():
            raise
    finally:
        shutil.rmtree(built, ignore_errors=True)


#: Where `_find` last found each task, so a repeat lookup reads that one file instead of listing the board.
_FOUND: dict[tuple[Path, str, tuple[str, ...]], Path] = {}

#: A task file's record as `_reader` built it, without `start_criteria`: the file, its `_stamp` and the record.
_Held = tuple[Path, tuple[int, int], dict[str, Any]]

#: The record `_reader` last built for each task of a board, so a repeat read of a file not written since neither finds
#: nor parses it again. A record is kept only once its file is `_SETTLED_NS` old: a later write within the clock's tick
#: could leave the same stamp. Callers add fields to the copy `read` returns, never to a list or dict inside it.
_RECORDS: dict[tuple[Path, tuple[str, ...], str], _Held] = {}

#: How many records `_RECORDS` keeps: the least recently built is dropped first, so a board of any size holds a fixed
#: number of parsed task files.
_RECORDS_KEPT = 256
_RECORDS_LOCK = threading.Lock()

#: How old a file's modification time is before its record is kept: well past a kernel clock tick.
_SETTLED_NS = 1_000_000_000

#: The `*.md` names `_md_names` last listed in each folder, so a first lookup of a task the board already held when it
#: was listed does not list the folder again.
_LISTED: dict[Path, list[str]] = {}


def _find(root: Path, task: str, folders: tuple[str, ...] = ("tasks", "completed")) -> Path | None:
    """The file under `tasks/`, or `completed/` once it is completed, whose front matter holds `id: <task>` in any case;
    `folders` names where else to look.

    A file named for the id is checked first; any other is parsed only when its raw front matter has an `id:` line
    spelling the id, so a lookup parses the file it returns rather than every file on the board. The file found last
    time is tried before the folders are listed; one that was renamed, moved or rewritten for another task is a miss.
    A file named for the id is first looked for in the folders as last listed; a miss there lists them again, so a
    file added or renamed since is found, and the others are only ever checked against a fresh listing.
    """
    key = (root, task.casefold(), folders)
    spelled = _id_line(task)
    if (path := _FOUND.get(key)) is not None and _has_id(path, task, spelled, False):
        return path
    for fresh in (False, True):
        listed = [(directory, _md_names(directory, fresh)) for directory in (root / folder for folder in folders)]
        named = (directory / name for directory, names in listed for name in names if _named_for(name, task))
        others = (directory / name for directory, names in listed for name in names if not _named_for(name, task))
        for candidates, prefilter in ((named, False), (others if fresh else (), True)):
            for path in candidates:
                if _has_id(path, task, spelled, prefilter):
                    _FOUND[key] = path
                    return path
    _FOUND.pop(key, None)
    return None


def _md_names(directory: Path, fresh: bool) -> list[str]:
    """The names of the `*.md` files in `directory`, in order, as last listed unless `fresh`; a `Path` is built only
    for a name worth opening."""
    if not fresh and (names := _LISTED.get(directory)) is not None:
        return names
    try:
        with os.scandir(directory) as entries:
            names = sorted(entry.name for entry in entries if entry.name.endswith(".md"))
    except FileNotFoundError:
        names = []
    _LISTED[directory] = names
    return names


def _has_id(path: Path, task: str, spelled: re.Pattern[str], prefilter: bool) -> bool:
    """Whether the file's front matter has `id: <task>`; `prefilter` skips the parse of a file whose raw text does not spell it."""
    try:
        text = path.read_text()
    except OSError:
        return False  # moved or removed while looking
    if prefilter and not spelled.search(_front_matter(text)):
        return False
    frontmatter, _ = _split(text)
    if not isinstance(frontmatter, dict):
        return False
    ids = [str(frontmatter.get("id") or "").strip(), *_aliases(frontmatter)]
    return task.casefold() in {found.casefold() for found in ids}


def _named_for(name: str, task: str) -> bool:
    """Whether the file's name starts with the id, as `task-5 - Title.md` does for `task-5` but not for `task-50`."""
    return name[: len(task)].lower() == task.lower() and not name[len(task) : len(task) + 1].isalnum()


def _front_matter(text: str) -> str:
    """The raw text between a file's `---` fences, empty for a file with none."""
    text = text.replace("\r\n", "\n")
    end = text.find("\n---", 4)
    return text[4:end] if text.startswith("---\n") and end != -1 else ""


def _id_line(task: str) -> re.Pattern[str]:
    """A front matter line that spells `task` as the `id:` or as a list item (an `aliases:` entry), quoted or not, in
    any case; the parse decides which list the item is in."""
    return re.compile(rf"^(?:id:|-)[ \t]*[\"']?{re.escape(task)}[\"']?[ \t]*$", re.M | re.I)


def _aliases(frontmatter: Mapping[str, Any]) -> list[str]:
    """The ids a task answers to besides its own `id`, as its `aliases` front matter lists them."""
    aliases = frontmatter.get("aliases")
    return [str(alias).strip() for alias in aliases] if isinstance(aliases, list) else []


def _pull_of(retired: _Retired) -> Callable[[str, int], dict[str, Any] | None]:
    """A lookup of the stored pull request `(repository, number)` as `{draft, checks, threads, mergeable, body, files}`,
    None when the store holds none; `files` is None for a record saved before the store kept them. A board that has not started has no store."""

    def read(repo: str, number: int) -> dict[str, Any] | None:
        if retired.engine is None:
            return None
        columns = (
            pull_requests.c.is_draft,
            pull_requests.c.checks,
            pull_requests.c.threads,
            pull_requests.c.mergeable,
            pull_requests.c.body,
            pull_requests.c.detail,
        )
        query = select(*columns).where(pull_requests.c.repo == repo, pull_requests.c.number == number)
        with retired.engine.connect() as db:
            row = db.execute(query).first()
        if row is None:
            return None
        return {
            "draft": row.is_draft,
            "checks": row.checks,
            "threads": row.threads,
            "mergeable": row.mergeable,
            "body": row.body,
            "files": (row.detail or {}).get("files"),
        }

    return read


def _state_of(root: Path, retired: _Retired) -> Callable[[str], str | None]:
    """A lookup of the state (its lane id) a task's file is in, or its retired file was in, None for a task with neither."""

    def state(task: str) -> str | None:
        if (path := _find(root, task)) is None:
            kept = retired.rows(task)
            text = kept[0]["text"] if kept else ""
        else:
            try:
                text = path.read_text()
            except OSError:
                return None  # moved or removed while looking
        frontmatter, _ = _split(text)
        return lane_id(str(frontmatter.get("status") or "").strip()) if isinstance(frontmatter, dict) else None

    return state


def _python_path(setting: object, base: Path) -> None:
    """Put each directory the `python_path` setting lists, relative to `base`, at the front of `sys.path`."""
    names = [setting] if isinstance(setting, str) else setting or []
    if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
        raise ValueError("board: python_path must be a list of directory names")
    found = [(base / name).resolve() for name in names]
    if missing := [str(path) for path in found if not path.is_dir()]:
        raise ValueError(f"board: python_path names no directory: {', '.join(missing)}")
    for path in reversed(found):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _hook(setting: object) -> Validate | None:
    """The function a `validate` setting names as `module:function`, or None without one."""
    if setting is None:
        return None
    module, _, name = str(setting).partition(":")
    try:
        found = getattr(importlib.import_module(module), name, None) if module and name else None
    except ImportError as error:
        raise ValueError(f"board: validate {setting!r}: {error}") from error
    if not callable(found):
        raise ValueError(f"board: validate {setting!r} names no function (expected module:function)")
    return found


def _types(settings: Mapping[str, Any]) -> tuple[str, ...]:
    """The names the `types` setting declares, empty when it declares none."""
    declared = settings.get("types", ())
    if not isinstance(declared, (list, tuple)) or not all(isinstance(name, str) and name.strip() for name in declared):
        raise ValueError("board: types must be a list of non-empty names")
    return tuple(declared)


def _stamped(frontmatter: dict, *, created: bool = False) -> dict:
    """`frontmatter` with `updated_date` (and `created_date` on a new task) set to now in UTC, after the profile or status."""
    now = f"{datetime.now(timezone.utc):{_STAMP}}"
    stamps = {key: now for key in ("created_date", "updated_date") if created or key == "updated_date"}
    anchor = next((key for key in ("profile", "assignee") if key in frontmatter), "status")
    stamped: dict[str, Any] = {}
    for key, value in frontmatter.items():
        stamped[key] = stamps.get(key, value)
        if key == anchor:
            stamped |= {stamp: now for stamp in stamps if stamp not in frontmatter}
    return stamped


def _split_record(text: str) -> tuple[dict, str]:
    frontmatter, body = _split(text)
    return (frontmatter if isinstance(frontmatter, dict) else {}), body


#: Returned by `_land` when the file no longer holds the text the write was made over.
_STALE = Written(False, "the task file changed while it was being written")
#: How many times `_update` redoes an edit on a file that changed under it before it gives up.
_ATTEMPTS = 5


def _land(path: Path, before: str | None, frontmatter: dict, body: str, guard: Guard, actor: str) -> Written | None:
    """Write the task file at `path` in one rename, unless `guard` refuses `actor`'s write or the file no longer holds
    `before`: the refusal (`_STALE` for a changed file), or None once it landed."""
    text = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---{body}"
    earlier = None if before is None else rules.Record(*_split_record(before))
    if refused := guard.refusal(path, before, earlier, frontmatter, body, text, actor):
        return refused
    if before is not None and path.read_text() != before:
        return _STALE
    # Unique per write, so concurrent writers never share a scratch file; not a `.md` file, so a scan never reads it half written.
    scratch = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    scratch.write_text(text)
    os.replace(scratch, path)
    return None


def _update(
    root: Path, task: str, edit: Callable[[dict, str], str], guard: Guard = Guard(), actor: str = OPERATOR
) -> Written:
    """Rewrite the file of `task` with its front matter edited in place, its body as `edit` returns it and a new
    `updated_date`, as `actor`.

    A file that changed between the read and the write is read and edited again, so another writer's change is kept;
    after `_ATTEMPTS` such races the edit is refused."""
    if (path := _find(root, task)) is None:
        return Written(False, f"{task} has no task file in {root / 'tasks'}")
    try:
        for _ in range(_ATTEMPTS):
            before = path.read_text()
            frontmatter, body = _split(before)
            body = edit(frontmatter, body)
            if (refused := _land(path, before, _stamped(frontmatter), body, guard, actor)) is None:
                return Written(True, f"Updated task {task}")
            if refused is not _STALE:
                return refused
    except OSError as error:
        return Written(False, f"{path}: {error}")
    return _STALE


def _section(pattern: re.Pattern[str], body: str) -> str:
    """The text between a section's markers, trimmed; empty when the section is absent."""
    found = pattern.search(body)
    return found.group(1).strip() if found else ""


def _items(pattern: re.Pattern[str], body: str) -> list[dict[str, Any]]:
    """The checklist between a section's markers as `{n, text, checked}`, in file order."""
    found = pattern.search(body)
    return [
        {"n": int(number), "text": text, "checked": mark != " "}
        for mark, number, text in _ITEM.findall(found.group(1) if found else "")
    ]


def _comments(body: str) -> list[dict[str, str]]:
    """The task's comments as `{created, text}`, oldest first, as `_comment` and the Backlog this workspace runs write them."""
    found = _COMMENTS_SECTION.search(body)
    region = found.group(1) if found else ""
    heads = list(_COMMENT_HEAD.finditer(region))
    ends = [*(head.start() for head in heads[1:]), len(region)]
    return [
        {
            "created": head[1],
            "text": region[head.end() : end].rstrip().removesuffix("---").strip(),
            **({"author": head[2]} if head[2] else {}),
        }
        for head, end in zip(heads, ends, strict=False)
    ]


def _recorded(text: str, comments: list[dict[str, str]]) -> bool:
    """Whether the task already records `text`: merge evidence anywhere, a hold or flag only as its latest of its kind."""
    texts = [c["text"] for c in comments]
    if text.startswith(MERGE_EVIDENCE):
        return text.strip() in texts
    prefix = next((each for each in (HELD, FLAGGED) if text.startswith(each)), None)
    latest = [t for t in texts if prefix and t.startswith(prefix)]
    return bool(latest) and latest[-1] == text.strip()


def _session(notes: str, comments: list[dict[str, str]]) -> str:
    """The link of the latest `**Session Link:**` line: the newest comment that has one, else the notes', else empty.

    A local-session line names its session UUID, not the word `local` that opens it.
    """
    texts = [notes, *(comment["text"] for comment in comments)]
    links = [local or link for text in texts for local, link in _SESSION_LINK.findall(text)]
    return links[-1] if links else ""


def _reader(
    root: Path,
    evaluate: Callable[[str, str], list[dict[str, Any]]],
    done: str | None = None,
    folders: tuple[str, ...] = ("tasks", "completed"),
) -> TaskReader:
    """A board reader: the record of the task's file under `folders`, keyed by the fields the task view draws and edits.

    `start_criteria` is the description's Start Criteria, each with the result `evaluate` gives it; a Done task's is empty."""

    def read(task: str, /) -> dict[str, Any] | None:
        key = (root, folders, task.casefold())
        held = _RECORDS.get(key)
        if held is None or not _unchanged(held):
            try:
                if (path := _find(root, task, folders)) is None:
                    return None
                held = (path, _stamp(path), _record_of(path.read_text(), task, _no_criteria))
            except OSError:
                return None  # moved or removed while reading
            if held[1][0] < time.time_ns() - _SETTLED_NS:
                with _RECORDS_LOCK:
                    _RECORDS.pop(key, None)
                    while len(_RECORDS) >= _RECORDS_KEPT:
                        del _RECORDS[next(iter(_RECORDS))]
                    _RECORDS[key] = held
        finished = lane_id(held[2]["status"]) == done  # a Done task has nothing left to start: no evaluator run for it
        return {**held[2], "start_criteria": [] if finished else evaluate(task, held[2]["description"])}

    return read


def _stamp(path: Path) -> tuple[int, int]:
    """The file's modification time and size, which differ when it was written since."""
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _unchanged(held: _Held) -> bool:
    """Whether the file `held` was built from is still there, with the stamp it had."""
    try:
        return _stamp(held[0]) == held[1]
    except OSError:
        return False


def _no_criteria(*_: object) -> list[dict[str, Any]]:
    """The `evaluate` of a record kept without `start_criteria`: the result changes without the file."""
    return []


def _record_of(text: str, task: str, evaluate: Callable[[str, str], list[dict[str, Any]]]) -> dict[str, Any]:
    """The record of the task file `text`, keyed by the fields the task view draws and edits."""
    frontmatter, body = _split(text)
    description = _description(body)
    notes, comments = _section(_NOTES, body), _comments(body)
    return {
        "id": str(frontmatter.get("id") or ""),
        "title": str(frontmatter.get("title") or ""),
        "type": str(frontmatter.get("type") or ""),
        "status": str(frontmatter.get("status") or ""),
        "profile": _profile_of(frontmatter),
        "assignee": str(frontmatter.get("assignee") or ""),
        "priority": str(frontmatter.get("priority") or ""),
        "impact": str(frontmatter.get("impact") or ""),
        "urgency": str(frontmatter.get("urgency") or ""),
        "tier": str(frontmatter.get("tier") or ""),
        "labels": list(_strings(frontmatter.get("labels"))),
        "milestone": str(frontmatter.get("milestone") or ""),
        "source": str(frontmatter.get("source") or ""),
        "follows": str(frontmatter.get("follows") or ""),
        "dependencies": list(_strings(frontmatter.get("dependencies"))),
        "dependencyNeeds": list(_strings(frontmatter.get("dependency_needs"))),
        "references": list(_strings(frontmatter.get("references"))),
        "documentation": list(_strings(frontmatter.get("documentation"))),
        "modifiedFiles": list(_strings(frontmatter.get("modified_files"))),
        "verifyPlan": list(_strings(frontmatter.get("verify_plan"))),
        "description": description,
        "start_criteria": evaluate(task, description),
        "plan": _section(_PLAN, body),
        "notes": notes,
        "finalSummary": _section(_FINAL_SUMMARY, body),
        "comments": comments,
        "session": assignee_of(frontmatter) or _session(notes, comments),
        "createdBy": str(frontmatter.get("created_by") or ""),
        "acceptanceCriteria": _items(_CRITERIA, body),
        "definitionOfDone": _items(_DONE, body),
    }


#: The sections an edit rewrites as text: the field's name, the markers' name and the heading a new section gets.
_TEXT_SECTIONS = {
    "description": ("DESCRIPTION", "Description"),
    "plan": ("PLAN", "Implementation Plan"),
    "notes": ("NOTES", "Implementation Notes"),
    "finalSummary": ("FINAL_SUMMARY", "Final Summary"),
    "needsAttention": ("NEEDS_ATTENTION", "Needs attention"),
}
#: The checklists an edit rewrites: the field's name, the markers' name, the heading a new section gets and its pattern.
_CHECKLISTS = {
    "acceptanceCriteria": ("AC", "Acceptance Criteria", _CRITERIA),
    "definitionOfDone": ("DOD", "Definition of Done", _DONE),
}
#: The creation bookkeeping a detail names in camelCase and the task file keeps under a snake_case front matter key.
_FRONT_KEYS = {
    "adrNeeded": "adr_needed",
    "duplicateSearch": "duplicate_search",
    "duplicateResolution": "duplicate_resolution",
    "follows": "follows",
}
_SCALARS = {
    "title": "title",
    "assignee": "assignee",
    "type": "type",
    "priority": "priority",
    "impact": "impact",
    "urgency": "urgency",
    "tier": "tier",
    "milestone": "milestone",
    "source": "source",
    **_FRONT_KEYS,
}
_LISTS = {
    "labels": "labels",
    "dependencies": "dependencies",
    "dependencyNeeds": "dependency_needs",
    "references": "references",
    "documentation": "documentation",
    "modifiedFiles": "modified_files",
    "verifyPlan": "verify_plan",
}
#: The lists whose key a task file leaves out while it holds nothing.
_OPTIONAL_LISTS = {"references", "documentation", "modified_files", "verify_plan", "dependency_needs"}
_COMMENTS = re.compile(r"[ \t]*<!-- COMMENTS:END -->")


def _text(field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    return value.strip()


def _marked(body: str, marker: str, heading: str, inner: str, *, after: str = "") -> str:
    """`body` with the section between `marker`'s comments holding `inner`, which a body without the section gets appended."""
    section = re.compile(rf"(<!-- {marker}:BEGIN -->).*?(<!-- {marker}:END -->)", re.S)
    if section.search(body):
        return section.sub(lambda found: f"{found[1]}{inner}{found[2]}", body, count=1)
    return body.rstrip("\n") + f"\n\n## {heading}\n{after}<!-- {marker}:BEGIN -->{inner}<!-- {marker}:END -->\n"


def _set_text(body: str, field: str, value: Any) -> str:
    name, heading = _TEXT_SECTIONS[field]
    text = _text(field, value)
    if field == "description" and not re.search(r"<!-- SECTION:DESCRIPTION:BEGIN -->", body):
        if headed := _HEADED_DESCRIPTION.search(body):  # a description under its heading, with no markers
            marked = f"\n<!-- SECTION:DESCRIPTION:BEGIN -->\n{text}\n<!-- SECTION:DESCRIPTION:END -->\n\n"
            return body[: headed.start(1)] + marked + body[headed.end(1) :]
    return _marked(body, f"SECTION:{name}", heading, f"\n{text}\n", after="\n")


def _set_items(task: str, body: str, field: str, value: Any) -> str:
    """`body` with the checklist `field` set to `value`: an item with a number keeps it and one without takes the next
    after the highest number given, so a list given without numbers is numbered from 1."""
    marker, heading, pattern = _CHECKLISTS[field]
    if not isinstance(value, list) or not all(
        isinstance(item, dict)
        and isinstance(item.get("text"), str)
        and item["text"].strip()
        and isinstance(item.get("checked"), bool)
        for item in value
    ):
        raise ValueError(f"{field} must be a list of items, each with text and checked")
    known = {item["n"] for item in _items(pattern, body)}
    if unknown := [item["n"] for item in value if "n" in item and item["n"] not in known]:
        raise ValueError(f"{task} has no {heading} item #{unknown[0]}")
    following = max((item["n"] for item in value if "n" in item), default=0)
    lines = []
    for item in value:
        if "n" not in item:
            following += 1
        lines.append(f"- [{'x' if item['checked'] else ' '}] #{item.get('n', following)} {item['text'].strip()}\n")
    return _marked(body, marker, heading, "\n" + "".join(lines), after="")


def _comment(body: str, text: str, actor: str = OPERATOR) -> str:
    """`body` with `text` appended to its comments by `actor`, as the Backlog this workspace runs writes one."""
    entry = f"created: {datetime.now():%Y-%m-%d %H:%M}\nauthor: {actor}\n---\n{text.strip()}\n---\n\n"
    if _COMMENTS.search(body):
        return _COMMENTS.sub(lambda end: f"{entry}{end.group()}", body, count=1)
    return body.rstrip("\n") + f"\n\n## Comments\n\n<!-- COMMENTS:BEGIN -->\n{entry}<!-- COMMENTS:END -->\n"


def _append_notes(body: str, text: str) -> str:
    """`body` with `text` on a new line at the end of its notes, which a body without notes gets as its first."""
    if _NOTES_END.search(body):
        return _NOTES_END.sub(lambda end: f"\n{text}{end.group()}", body, count=1)
    return body.rstrip("\n") + "\n" + _NOTES_SECTION.format(text)


def _tier(text: str) -> str:
    """`text` as a tier the board names (blank stays blank, which clears it), or raise."""
    tier = text.strip().lower()
    if tier and tier not in TIERS:
        raise ValueError(f"tier must be one of {', '.join(TIERS)}, not {text!r}")
    return tier


def _set_front(frontmatter: dict, field: str, value: Any, spelled: Mapping[str, str]) -> bool:
    """Set `field` in `frontmatter` and say so, or say it is no front matter field, leaving `frontmatter` as it was."""
    if field in _SCALARS:
        key = _SCALARS[field]
        text = _text(field, value)
        if not text and field == "title":
            raise ValueError("title cannot be empty")
        if field == "tier":
            text = _tier(text)
        frontmatter[key] = text
        if not text:
            del frontmatter[key]
    elif field == "profile":
        frontmatter["profile"] = [_text(field, value)]
        if not frontmatter["profile"][0]:
            del frontmatter["profile"]
    elif field == "status":
        if lane_id(_text(field, value)) not in spelled:
            raise ValueError(f"{value!r} is not a status of this board: {', '.join(spelled.values())}")
        frontmatter["status"] = spelled[lane_id(value)]
    elif field in _LISTS:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{field} must be a list of text")
        key = _LISTS[field]
        frontmatter[key] = [item.strip() for item in value if item.strip()]
        if not frontmatter[key] and key in _OPTIONAL_LISTS:
            del frontmatter[key]
    else:
        return False
    return True


def _set_body(task: str, body: str, field: str, value: Any) -> str:
    """`body` with the section or checklist `field` set to `value`; `appendNotes` adds to the notes instead."""
    if field == "appendNotes":
        if not _text(field, value):
            raise ValueError("appendNotes cannot be empty")
        return _append_notes(body, value.strip())
    if field in _TEXT_SECTIONS:
        return _set_text(body, field, value)
    if field in _CHECKLISTS:
        return _set_items(task, body, field, value)
    raise ValueError(f"{field} is not an editable field")


def _apply(task: str, frontmatter: dict, body: str, changes: Mapping[str, Any], spelled: Mapping[str, str]) -> str:
    """Set each field of `changes` in `frontmatter` or `body`, returning the body; a field it cannot set raises ValueError."""
    for field, value in changes.items():
        if not _set_front(frontmatter, field, value, spelled):
            body = _set_body(task, body, field, value)
    return body


_DOC_ID = re.compile(r"doc-\d+")
_Linker = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _unlinked(changes: Mapping[str, Any]) -> Mapping[str, Any]:
    return changes


def _doc_linker(root: Path, base: Path) -> _Linker:
    """`changes` with each doc id in its `documentation` list read as that open doc's file, keeping one link per file; an
    id no open doc has raises ValueError.

    The file is named from the repository the board sits in (the nearest folder above it holding `.git`), as a task's
    other links are, else from `base`.
    """
    read = native_docs.reader(root)

    def prefix() -> Path:
        board = root.resolve()
        top = next((folder for folder in board.parents if (folder / ".git").exists()), base.resolve())
        return Path(os.path.relpath(board, top))

    def link(changes: Mapping[str, Any]) -> Mapping[str, Any]:
        listed = changes.get("documentation")
        if not isinstance(listed, list) or not all(isinstance(item, str) for item in listed):
            return changes  # `_set_front` refuses a value that is not a list of text
        paths = []
        for item in listed:
            if _DOC_ID.fullmatch(doc := item.strip()):
                if (record := read(doc)) is None:
                    raise ValueError(f"{doc} is not an open doc")
                item = (prefix() / "docs" / record["path"]).as_posix()
            paths.append(item)
        return {**changes, "documentation": list(dict.fromkeys(paths))}

    return link


def _unstarted(roles: StateRoles) -> frozenset[str]:
    """The lanes where work has not begun: where a task starts, is ready, waits on dependencies or is only proposed."""
    return frozenset(lane for lane in (roles.initial, roles.ready, roles.waiting, roles.proposed) if lane)


def _editor(
    root: Path,
    statuses: tuple[str, ...],
    guard: Guard = Guard(),
    link: _Linker = _unlinked,
    attention: str | None = None,
    unstarted: frozenset[str] = frozenset(),
) -> TaskEditor:
    """A board writer that applies every change to a task's file in one write, or refuses the whole edit.

    `changes` holds the new value of each field `read` names except `comments`, which `comment` appends to: one text, or a
    list appended in order, each blank one skipped; `appendNotes` is one more, text added to the end of the notes. An
    empty priority, milestone, profile or type and an empty references, documentation or modified-files list removes its
    key, a status is spelled as its lane is, a checklist item without a number is new, and `link` reads a doc id in the
    documentation list as its file. A move to the `attention` lane with comment text also writes that text as the task's
    `## Needs attention` section, the reason the lane's guard reads. `planReason` is no field: a plan rewritten on a task
    outside the `unstarted` lanes needs one, and the History records it.
    """
    spelled = {lane_id(status): status for status in statuses}

    def edit(task: str, changes: Mapping[str, Any], comment: str | Sequence[str], /, actor: str = OPERATOR) -> Written:
        texts = [comment] if isinstance(comment, str) else comment
        status = str(changes.get("status") or "")
        reason = "\n".join(text.strip() for text in texts if text.strip())
        if attention and reason and lane_id(status) == lane_id(attention):
            changes = {**changes, "needsAttention": reason}

        plan_reason = str(changes.get("planReason") or "").strip()
        changes = {field: value for field, value in changes.items() if field != "planReason"}

        def apply(frontmatter: dict, body: str) -> str:
            if "plan" in changes and not plan_reason:
                started = str(frontmatter.get("status") or "")
                if revises_plan(started, _section(_PLAN, body), str(changes["plan"] or "").strip(), unstarted):
                    raise ValueError("the plan needs a reason once work has started: pass --reason")
            body = _apply(task, frontmatter, body, link(changes), spelled)
            for text in texts:
                recorded = _recorded(text, _comments(body))
                body = _comment(body, text, actor) if text.strip() and not recorded else body
            return body

        # A comment changes no field a rule or the validate hook judges, and the comment that names a refusal must land.
        judged = guard if changes else replace(guard, rules=(), validate=None)
        try:
            written = _update(root, task, apply, judged, actor)
        except ValueError as refusal:  # raised before the file is written, so a refusal writes nothing
            return Written(False, f"{task}: {refusal}")
        return _moved(written, spelled.get(lane_id(status), status)) if status else written

    return edit


def _open_tasks(root: Path, done: str | None) -> Iterator[tuple[str, dict]]:
    """The id and front matter of each task under `tasks/` that is not Done, in file order."""
    for path in sorted((root / "tasks").glob("*.md")):
        try:
            frontmatter, _ = _split(path.read_text())
        except OSError:
            continue  # moved or removed while looking
        if isinstance(frontmatter, dict) and lane_id(str(frontmatter.get("status") or "")) != done:
            yield str(frontmatter.get("id") or path.stem).strip(), frontmatter


def _open_dependents(root: Path, task: str, done: str | None) -> list[str]:
    """Ids of the tasks under `tasks/` that are not Done and list `task` as a dependency, in file order."""
    wanted = task.casefold()
    return [
        found
        for found, frontmatter in _open_tasks(root, done)
        if wanted in {dependency.casefold() for dependency in _strings(frontmatter.get("dependencies"))}
    ]


def _holders(root: Path, done: str | None) -> Callable[[str, str], list[str]]:
    """A lookup of the ids of the open tasks whose front matter `field` holds `value`."""

    def holders(field: str, value: str) -> list[str]:
        return [found for found, frontmatter in _open_tasks(root, done) if value in _strings(frontmatter.get(field))]

    return holders


def _needs(need: str, task: str) -> bool:
    """Whether the dependency need `TASK-N#K` is of `task`."""
    return need.partition("#")[0].casefold() == task.casefold()


def _unlinker(task: str, reason: str, ready: str | None, waiting: str | None) -> Callable[[dict, str], str]:
    """An edit that drops `task` from a task's dependencies and says why; a Waiting task left with no dependency and
    no Start Criteria moves to `ready`, since the release pass reads only Waiting tasks that still have one."""
    note = f"Removed dependency on {task}: archived" + (f" ({reason.strip()})" if reason.strip() else "")

    def edit(frontmatter: dict, body: str) -> str:
        kept = [name for name in _strings(frontmatter.get("dependencies")) if name.casefold() != task.casefold()]
        frontmatter["dependencies"] = kept
        if needs := [need for need in _strings(frontmatter.get("dependency_needs")) if not _needs(need, task)]:
            frontmatter["dependency_needs"] = needs
        else:
            frontmatter.pop("dependency_needs", None)
        held = lane_id(str(frontmatter.get("status") or "")) == waiting
        if held and not kept and ready is not None and not criteria.authored(body):
            frontmatter["status"] = ready
            return _comment(body, f"{note}; no dependency is left, so it moved to {ready}.")
        return _comment(body, note)

    return edit


def _archiver(root: Path, statuses: tuple[str, ...], roles: StateRoles, guard: Guard = Guard()) -> TaskArchiver:
    """A board writer that moves a task's file to `archive/tasks/`, from any lane, after recording a non-blank reason as a comment.

    An archived task never reaches Done, so each open task that depends on it has that dependency removed first, with
    a comment saying why; a Waiting one left with no dependency is released to Ready."""
    ready = {lane_id(status): status for status in statuses}.get(roles.ready or "")

    def archive(task: str, reason: str, /, actor: str = OPERATOR) -> Written:
        if (path := _find(root, task)) is None:
            return Written(False, f"{task} has no task file in {root / 'tasks'}")
        if (
            reason.strip()
            and not (
                noted := _update(
                    root, task, lambda _, body: _comment(body, f"Archived: {reason.strip()}", actor), guard, actor
                )
            ).ok
        ):
            return noted
        dependents = _open_dependents(root, task, roles.done)
        for dependent in dependents:
            if not (unlinked := _update(root, dependent, _unlinker(task, reason, ready, roles.waiting), guard, actor)).ok:
                return unlinked
        target = root / "archive" / "tasks" / path.name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
        except OSError as error:
            return Written(False, f"{path}: {error}")
        unlinked = f"; removed it from the dependencies of {', '.join(dependents)}" if dependents else ""
        return _moved(Written(True, f"Archived task {task}{unlinked}"), ARCHIVED)

    return archive


class _Retired:
    """The board's retired tasks, rows of the history store's `starpulse_retired_tasks`, once `start` binds the store.

    A board that has not started has no store: it reads no retired task and refuses to keep one. A task is matched by
    its id in any case, as `_find` matches a file."""

    def __init__(self) -> None:
        self.engine: Engine | None = None

    def rows(self, task: str = "", milestone: str = "") -> list[dict[str, str]]:
        """The retired task `task` as `[{task, name, text}]`, empty when it is not retired; every one, by id, for "".
        A `milestone` keeps only the tasks whose front matter names it."""
        return list(self.each(task, milestone))

    def projected(self, project: Callable[[str], Any], task: str = "", milestone: str = "") -> list[tuple[str, Any]]:
        """`rows` as `[(id, project(text))]`: only what `project` keeps outlives its page."""
        return [(row["task"], project(row["text"])) for row in self.each(task, milestone)]

    def each(self, task: str, milestone: str) -> Iterator[dict[str, str]]:
        """The rows `rows` answers, by id, a page of them at a time."""
        after = ""
        while self.engine is not None:
            query = (
                select(retired_tasks.c.task, retired_tasks.c.name, retired_tasks.c.text)
                .where(retired_tasks.c.task > after)
                .order_by(retired_tasks.c.task)
                .limit(_RETIRED_PAGE)
            )
            if task:
                query = query.where(func.lower(retired_tasks.c.task) == task.lower())
            if milestone:  # the text search narrows the rows; the front matter decides
                query = query.where(retired_tasks.c.text.contains(milestone))
            with self.engine.connect() as db:
                page = [dict(row._mapping) for row in db.execute(query)]
            for row in page:
                if not milestone or str(_split_record(row["text"])[0].get("milestone") or "").strip() == milestone:
                    yield row
            if len(page) < _RETIRED_PAGE:
                return
            after = page[-1]["task"]

    def aliases(self) -> list[str]:
        """The ids the retired tasks answer to besides their own: those their `aliases` front matter lists."""
        if self.engine is None:
            return []
        query = select(retired_tasks.c.text).where(retired_tasks.c.text.contains("\naliases:"))
        with self.engine.connect() as db:
            texts = [row.text for row in db.execute(query)]
        return [alias for text in texts for alias in _aliases(_split_record(text)[0])]

    def texts(self) -> Iterator[str]:
        """Every retired task's text, by id, a page of rows at a time, so no more than a page is held at once."""
        return (text for _, text in self.pairs())

    def pairs(self) -> Iterator[tuple[str, str]]:
        """Every retired `(task, text)`, by id, a page of rows at a time."""
        after = ""
        while self.engine is not None:
            query = (
                select(retired_tasks.c.task, retired_tasks.c.text)
                .where(retired_tasks.c.task > after)
                .order_by(retired_tasks.c.task)
                .limit(_RETIRED_PAGE)
            )
            with self.engine.connect() as db:
                page = db.execute(query).all()
            yield from ((row.task, row.text) for row in page)
            if len(page) < _RETIRED_PAGE:
                return
            after = page[-1].task

    def changes(self) -> Callable[[bool], Iterator[str] | None]:
        """A reader of every retired task's text that answers None while the rows are as it last read them, unless
        `force` asks for the text again; it keeps the rows' count and newest `retired_at`, never their text."""
        seen: tuple[int, float | None] | None = None

        def read(force: bool = False) -> Iterator[str] | None:
            nonlocal seen
            if self.engine is None:
                return None
            with self.engine.connect() as db:
                now = tuple(db.execute(select(func.count(), func.max(retired_tasks.c.retired_at))).one())
            if now == seen and not force:
                return None
            seen = now
            return self.texts()

        return read

    def ids(self) -> list[str]:
        """Every retired task's id."""
        if self.engine is None:
            return []
        with self.engine.connect() as db:
            return list(db.execute(select(retired_tasks.c.task)).scalars())

    def keep(self, task: str, name: str, text: str) -> str | None:
        """Keep `task`'s file `name` with `text`: why it is refused (the board has not started, or `task` is retired
        with other text), or None once it is kept. The same task with the same text is kept already."""
        if self.engine is None:
            return "the board keeps no retired tasks until it starts"
        with self.engine.begin() as db:
            held = db.execute(
                select(retired_tasks.c.text).where(func.lower(retired_tasks.c.task) == task.lower())
            ).scalar()
            if held is None:
                db.execute(insert(retired_tasks).values(task=task, name=name, text=text, retired_at=time.time()))
        return None if held in (None, text) else f"{task} is already retired with other text"

    def take(self, task: str, directory: Path) -> Written | None:
        """Write the retired `task` back into `directory` under its own name and drop its row; None when it is not
        retired. A file already at that name is never replaced: the restore is refused and the row stays."""
        if not (kept := self.rows(task)):
            return None
        target = directory / kept[0]["name"]
        try:
            with target.open("xb") as file:
                file.write(kept[0]["text"].encode())
        except FileExistsError:
            return Written(False, f"{task}: {target} already exists")
        except OSError as error:
            return Written(False, f"{target}: {error}")
        assert self.engine is not None  # rows found one
        with self.engine.begin() as db:
            db.execute(delete(retired_tasks).where(retired_tasks.c.task == kept[0]["task"]))
        return Written(True, f"Restored task {task}")


#: Where a finished task's file may be retired from: a Done task's lanes, or the archive whatever its state.
_RETIRABLE = ("tasks", "completed", "archive/tasks")


def _retirer(root: Path, retired: _Retired, roles: StateRoles) -> TaskRetirer:
    """A board writer that takes a Done or archived task's file off the board into `retired`, byte for byte.

    The file is first renamed to a name no scan reads, so a write meeting the retire finds no file rather than losing
    its change; a retire the store refuses renames it back."""

    def retire(task: str, /) -> Written:
        if (path := _find(root, task, _RETIRABLE)) is None:
            return Written(False, f"{task} has no task file on the board")
        frontmatter, _ = _split(text := path.read_bytes().decode())
        status = str(frontmatter.get("status") or "") if isinstance(frontmatter, dict) else ""
        if path.parent != root / "archive" / "tasks" and lane_id(status) != roles.done:
            return Written(False, f"{task} is {status or 'without a status'}, neither Done nor archived")
        held = path.with_name(f"{path.name}.retiring")
        try:
            os.replace(path, held)
            if refused := retired.keep(str(frontmatter["id"]).strip(), path.name, held.read_bytes().decode()):
                os.replace(held, path)
                return Written(False, refused)
            held.unlink()
        except OSError as error:
            return Written(False, f"{path}: {error}")
        return Written(True, f"Retired task {task}")

    return retire


def _retired_reader(retired: _Retired) -> RetiredReader:
    def read(task: str, milestone: str, /) -> Iterable[Mapping[str, str]]:
        rows = retired.each(task, milestone)
        return list(rows) if task else rows

    return read


def _importer(root: Path, retired: _Retired) -> RetiredImporter:
    """A board writer that keeps a task file another client retired, `name` and `text`, among `retired`."""

    def import_retired(name: str, text: str, /) -> Written:
        if Path(name).name != name or not name.endswith(".md"):
            return Written(False, f"{name!r} is not a plain task file name")
        frontmatter, _ = _split(text)
        if not (task := str(frontmatter.get("id") or "").strip() if isinstance(frontmatter, dict) else ""):
            return Written(False, f"{name} names no task id in its front matter")
        if _find(root, task, _RETIRABLE) is not None:
            return Written(False, f"{task} is on the board")
        if refused := retired.keep(task, name, text):
            return Written(False, refused)
        return Written(True, task)

    return import_retired


def _restorer(
    root: Path, retired: _Retired, statuses: tuple[str, ...], migrations: Mapping[str, str], guard: Guard
) -> TaskRestorer:
    """A board writer that returns an archived or retired task's file to `tasks/` under its own name.

    An archived task keeps the State it was archived in. When the active definition lacks it, the file lands in the
    State its `migrations` entry names, and a State with no entry refuses the restore.

    The task is refused while its number is open or completed, and when the name is taken: an archived file is linked
    into place and a retired one written only as a new file, so a file another writer put there first is never
    replaced."""

    def restore(task: str, /) -> Written:
        if _find(root, task) is not None:
            return Written(False, f"{task} is already on the board")
        if (path := _find(root, task, ("archive/tasks",))) is None:
            return retired.take(task, root / "tasks") or Written(
                False, f"{task} has no archived task file in {root / 'archive' / 'tasks'} and is not retired"
            )
        held = str(_split(path.read_text())[0].get("status") or "")
        spelled = {lane_id(status): status for status in statuses}
        landing = held if lane_id(held) in spelled else spelled.get(migrations.get(lane_id(held), ""))
        if landing is None:
            return Written(False, f"{task} was archived in {held}, which the active definition lacks and no migrations entry names")
        target = root / "tasks" / path.name
        try:
            os.link(path, target)
            path.unlink()
        except FileExistsError:
            return Written(False, f"{task}: {target} already exists")
        except OSError as error:
            return Written(False, f"{path}: {error}")
        if landing == held:
            return Written(True, f"Restored task {task}")

        def land(frontmatter: dict, body: str) -> str:
            frontmatter["status"] = landing
            return body

        return _update(root, task, land, guard)

    return restore


class _Claims:
    """Where the board records an agent's refused claim once `attach` binds the event log: one `board:claims` entry."""

    def __init__(self) -> None:
        self.log: EventLog | None = None

    def refused(self, task: str, actor: str, reason: str) -> None:
        """Append the refusal of `actor`'s claim of `task` with its `reason` and the time, fail-open."""
        if self.log is not None:
            from starpulse.board.claim_refusals import CLAIMS_STREAM  # noqa: PLC0415 - loading a board loads no feed

            self.log.publish(CLAIMS_STREAM, {"task": task, "actor": actor, "reason": reason, "time": time.time()})


def _moved(written: Written, lane: str) -> Written:
    """`written` once it landed, with the `lane` it put the task in and the moment, for the server to record with the
    request's actor; a refused write moved nothing."""
    return written._replace(lane=lane, at=time.time()) if written.ok else written


def _writer(
    root: Path, statuses: tuple[str, ...], roles: StateRoles, guard: Guard = Guard(), claims: _Claims = _Claims()
) -> MoveWriter:
    """A board writer that sets a status in the task's file. A lane's status is the board's own spelling of it.

    An agent's claim (a move to the working State that names its session) also records the session as the task's assignee,
    and a refused claim is recorded on `board:claims`.
    """
    spelled = {lane_id(status): status for status in statuses}

    def write(task: str, status: str, actor: str, session: str = "") -> Written:
        claim = actor != OPERATOR and session and lane_id(status) == roles.working

        def edit(frontmatter: dict, body: str) -> str:
            frontmatter["status"] = spelled.get(lane_id(status), status)
            if claim:
                claimed(frontmatter, session)
            return body

        written = _update(root, task, edit, guard, actor)
        if claim and not written.ok:
            claims.refused(task, actor, written.output)
        return _moved(written, spelled.get(lane_id(status), status))

    return write


class _Unheld(Exception):
    """The task file no longer holds the claim a release judged."""


def _releaser(root: Path, guard: Guard = Guard()) -> TaskReleaser:
    """A board writer that ends `session`'s claim on a task still in `status`: it loses its `assignee` field, gains
    `released_from` and keeps its State. A file another writer moved off `status` or whose claim `session` no longer holds
    is refused untouched, so a release judged from a stale row cannot undo a later move."""

    def release(task: str, status: str, /, session: str, actor: str = ANONYMOUS) -> Written:
        def edit(frontmatter: dict, body: str) -> str:
            held = str(frontmatter.get("status") or "")
            holder = assignee_of(frontmatter)
            if lane_id(held) != lane_id(status) or holder != session:
                raise _Unheld(f"{task} is {held or 'without a status'} held by {holder or 'no session'}")
            released(frontmatter)
            return body

        try:
            return _update(root, task, edit, guard, actor)
        except _Unheld as unheld:
            return Written(False, str(unheld))

    return release


def _completer(root: Path, statuses: tuple[str, ...], roles: StateRoles) -> TaskCompleter:
    """A board writer that moves a Done task's file to `completed/`, where the reader and the projection still find it.

    The move enters the `completed` lane where the board has one; a board without it keeps the task in Done."""
    swept = COMPLETED if COMPLETED in {lane_id(status) for status in statuses} else None

    def complete(task: str, /) -> Written:
        if (path := _find(root, task)) is None:
            return Written(False, f"{task} has no task file in {root / 'tasks'}")
        if path.parent.name == "completed":
            return Written(False, f"{task} is already completed")
        status = str(_split(path.read_text())[0].get("status") or "")
        if lane_id(status) != roles.done:
            return Written(False, f"{task} is {status or 'without a status'}, not Done")
        target = root / "completed" / path.name
        try:
            target.parent.mkdir(exist_ok=True)
            os.replace(path, target)
        except OSError as error:
            return Written(False, f"{path}: {error}")
        written = Written(True, f"Completed task {task}")
        return written if swept is None else _moved(written, swept)

    return complete


def _reidentified(root: Path, path: Path, new: str, file_name: str, *, restore: bool = False) -> Written:
    """Give the task in `path` the id `new`, rename its file for it and point the dependencies on its old id at `new`.

    The old id joins the task's `aliases`, so a link to it still finds the task; with `restore`, `new` is an id the
    task held before, which leaves the aliases instead. The answer's output is the old id."""
    try:
        before = path.read_text()
        frontmatter, body = _split_record(before)
        old = str(frontmatter.get("id") or "")
        held = [alias for alias in _aliases(frontmatter) if alias != new]
        aliases = held if restore else [*held, old]
        renamed = {**{key: value for key, value in frontmatter.items() if key != "aliases"}, "id": new}
        target = path.with_name(_file_name(new, str(frontmatter.get("title") or ""), file_name))
        if refused := _land(
            path, before, _stamped({**renamed, **({"aliases": aliases} if aliases else {})}), body, Guard(), OPERATOR
        ):
            return refused
        os.replace(path, target)
        _repointed(root, old, new)
    except OSError as error:
        return Written(False, f"{path}: {error}")
    return Written(True, old)


def _repointed(root: Path, old: str, new: str) -> None:
    """Rewrite each open task's dependency on `old` to `new`."""
    for path in (root / "tasks").glob("*.md"):
        text = path.read_text()
        if old not in text:
            continue
        frontmatter, body = _split_record(text)
        dependencies = list(_strings(frontmatter.get("dependencies")))
        if old not in dependencies:
            continue
        repointed = [new if dependency == old else dependency for dependency in dependencies]
        _land(path, text, _stamped({**frontmatter, "dependencies": repointed}), body, Guard(), OPERATOR)


def _renumberer(root: Path, prefix: str, retired: _Retired, file_name: str) -> Callable[[str], Written]:
    """A board writer that gives a task the next id of the board's task sequence and keeps its old id as an alias, so a
    link to the old id still finds it. The answer's output is the new id."""
    lock = threading.Lock()  # two renumbers, in this process or another, must not both read the same highest id

    def renumber(task: str) -> Written:
        with lock, _allocating(root):
            if (path := _find(root, task)) is None:
                return Written(False, f"{task} is not on the board")
            new = _next_id(root, prefix, retired)
            done = _reidentified(root, path, new, file_name)
            return Written(True, new) if done.ok else done

    return renumber


def _promoter(
    write: MoveWriter,
    read: Callable[[str], Mapping[str, Any] | None],
    renumber: Callable[[str], Written],
    leaves: tuple[str, str],
) -> MoveWriter:
    """`write` that renumbers a `<prefix>-N` proposal it moves out of the proposed lane, unless the move is the drop to
    the `final` lane. A proposal that still holds a task number keeps it. `leaves` is `(proposed lane, final lane,
    prefix)`."""
    proposed, final, prefix = leaves
    own = f"{prefix.casefold()}-"

    def promote(task: str, status: str, actor: str, session: str = "") -> Written:
        before = read(task)
        written = write(task, status, actor, session) if session else write(task, status, actor)
        in_proposed = before is not None and lane_id(str(before.get("status", ""))) == proposed
        held = str(before.get("id") or task) if before is not None else task
        proposal = in_proposed and held.casefold().startswith(own)
        if not (written.ok and proposal and lane_id(status) not in (proposed, final)):
            return written
        renumbered = renumber(task)
        return written._replace(renumbered=renumbered.output) if renumbered.ok else written

    return promote


def _next_id(root: Path, prefix: str, retired: _Retired) -> str:
    """`<prefix>-N` with N one past the highest on the board, its completed, archived and retired tasks included."""
    number = re.compile(rf"{re.escape(prefix)}-(\d+)", re.I)
    taken = [*retired.ids(), *retired.aliases()]
    highest = max((int(found[1]) for task in taken if (found := number.fullmatch(task))), default=0)
    for folder, _ in _FOLDERS:
        for path in (root / folder).glob("*.md"):
            try:
                frontmatter, _ = _split(path.read_text())
            except OSError:
                continue  # moved or removed while looking
            if not isinstance(frontmatter, dict):
                continue
            for taken_id in (str(frontmatter.get("id") or "").strip(), *_aliases(frontmatter)):
                if found := number.fullmatch(taken_id):
                    highest = max(highest, int(found[1]))
    return f"{prefix}-{highest + 1}"


#: The details `_new_task` writes itself; any other detail is set as `edit` sets that field.
_NEW_TASK_DETAILS = {
    "profile",
    "assignee",  # the legacy name of `profile`
    "labels",
    "milestone",
    "dependencies",
    "priority",
    "impact",
    "urgency",
    "tier",
    "description",
    "acceptanceCriteria",
    "created_by",
    *_FRONT_KEYS,
}


def _new_task(task: str, title: str, status: str, details: Mapping[str, Any]) -> str:
    """A new task file as Backlog.md writes one: its front matter, then its Description and Acceptance Criteria."""
    frontmatter: dict[str, Any] = {"id": task, "title": title, "status": status}
    if profile := details.get("profile", details.get("assignee")):
        frontmatter["profile"] = [profile]
    keys = ("labels", "milestone", "dependencies", "priority", "impact", "urgency", "created_by")
    frontmatter |= {key: details[key] for key in keys if key in details}
    frontmatter["tier"] = _tier(str(details.get("tier") or "")) or DEFAULT_TIER
    frontmatter |= {_FRONT_KEYS[field]: details[field] for field in _FRONT_KEYS if field in details}
    text = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---\n"
    if description := details.get("description"):
        text += (
            f"\n## Description\n\n<!-- SECTION:DESCRIPTION:BEGIN -->\n{description}\n<!-- SECTION:DESCRIPTION:END -->\n"
        )
    if criteria := details.get("acceptanceCriteria"):
        items = "".join(f"- [ ] #{n} {item}\n" for n, item in enumerate(criteria, 1))
        text += f"\n## Acceptance Criteria\n<!-- AC:BEGIN -->\n{items}<!-- AC:END -->\n"
    return text


def _slug(title: str) -> str:
    """`title` as a lowercase, hyphen-only slug of at most `_SLUG_MAX` characters, cut at a word and past any trailing date."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    dated = _SLUG_DATE.search(slug)
    date = slug[dated.start() :] if dated else ""
    if dated:
        slug = slug[: dated.start()]
    if len(slug) > _SLUG_MAX:
        head = slug[:_SLUG_MAX]
        boundary = slug.rfind("-", 0, _SLUG_MAX + 1)
        words = (slug[:boundary] if boundary > 0 else head).strip("-").split("-")
        while len(words) > 1 and words[-1] in _SLUG_STOPWORDS:
            words.pop()
        slug = "-".join(words)
    return f"{slug}{date}".strip("-") or "untitled"


def _file_name(task: str, title: str, form: str) -> str:
    """The name of the file a task created as `title` is written under, in the `form` of `_FILE_NAMES`."""
    if form == "slug":
        return f"{task.lower()}-{_slug(title)}.md"
    return f"{task} - {re.sub(r'[^\w-]+', '-', title).strip('-')[:60].strip('-') or 'Task'}.md"


@contextmanager
def _allocating(root: Path) -> Iterator[None]:
    """Lock the board directory itself: a create in another process on the same board waits until this one has
    written, and no lock file lands among the board's files."""
    held = os.open(root, os.O_RDONLY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX)
        yield
    finally:
        os.close(held)


def _creator(
    root: Path,
    config: BacklogConfig,
    retired: _Retired,
    guard: Guard = Guard(),
    file_name: str = "title",
    link: _Linker = _unlinked,
    proposals: tuple[str, str] = ("", ""),
) -> TaskCreator:
    """A board writer that makes a task file with the next id, named in the `file_name` form, in one write.

    It starts in the first lane; any detail beyond the ones the page fills (a `status`, `type`, `references`,
    `documentation`, `definitionOfDone`, `plan`, `notes` or other field `edit` sets) is set as `edit` sets it, so a
    detail it cannot set refuses the create and nothing is written. A refused create leaves its id to the next one.
    `proposals` is the proposed lane and the id prefix of its own sequence; a create in that lane takes its id there.
    """
    proposed_lane, proposal_prefix = proposals
    lock = threading.Lock()  # two creates, in this process or another, must not both read the same highest id
    spelled = {lane_id(status): status for status in config.statuses}

    def create(title: str, details: Mapping[str, Any], /, actor: str = OPERATOR) -> Written:
        with lock, _allocating(root):
            proposed = bool(proposal_prefix) and lane_id(str(details.get("status", ""))) == proposed_lane
            task = _next_id(root, proposal_prefix if proposed else config.prefix, retired)
            path = root / "tasks" / _file_name(task, title, file_name)
            frontmatter, body = _split(_new_task(task, title, config.statuses[0], details))
            rest = {field: value for field, value in details.items() if field not in _NEW_TASK_DETAILS}
            try:
                body = _apply(task, frontmatter, body, link(rest), spelled)
                if refused := _land(path, None, _stamped(frontmatter, created=True), body, guard, actor):
                    return refused
            except ValueError as refusal:
                return Written(False, f"{title}: {refusal}")
            except OSError as error:
                return Written(False, f"{path}: {error}")
        return _moved(Written(True, task), str(frontmatter.get("status") or config.statuses[0]))

    return create


#: Seconds a `holds`, `unfinished` or notice hook may run. Each starts a Python process and reads the board over HTTP, which takes
#: 20 s under load where the evaluator's `criteria.TIMEOUT` gives up at 10 s; a timeout holds the task until the next pass.
HOOK_TIMEOUT = 60.0


def _holds(command: object, base: Path) -> Callable[[str], list[str]] | None:
    """The `holds` or `unfinished` command, run in `base` with `{id}` replaced by the task's id: it prints a JSON array
    of the reasons the task's `deps_done` is withheld, or of the work a merged task has left. Output that is no such array
    raises, which holds the task."""
    if not command:
        return None
    parts = shlex.split(str(command))

    def holds(task: str) -> list[str]:
        argv = [part.replace("{id}", task) for part in parts]
        done = subprocess.run(argv, cwd=base, capture_output=True, text=True, timeout=HOOK_TIMEOUT, check=False)
        try:
            printed = json.loads(done.stdout)
        except ValueError:
            printed = None
        if not isinstance(printed, list) or not all(isinstance(reason, str) for reason in printed):
            said = done.stderr.strip() or done.stdout.strip() or "printed nothing"
            raise ValueError(f"{shlex.join(argv)}: exit {done.returncode}: {said}")
        return printed

    return holds


def _notice(command: object, base: Path) -> Callable[[str], None] | None:
    """The `parked`, `released`, `delivered`, `returned`, `verifying` or `closed` command, run in `base` with `{id}`
    replaced by the task's id, after the task actor moves a task from the working lane to Waiting, from Waiting to Ready,
    sees its delivery finish (with `{verdict}` replaced by the run's verdict), sends it from Review back to the working
    lane, moves it on a merge that leaves its post-merge QA to run, or moves it to Done. A nonzero exit raises with what
    the command said."""
    if not command:
        return None
    parts = shlex.split(str(command))

    def notice(task: str, verdict: str = "") -> None:
        argv = [part.replace("{id}", task).replace("{verdict}", verdict) for part in parts]
        done = subprocess.run(argv, cwd=base, capture_output=True, text=True, timeout=HOOK_TIMEOUT, check=False)
        if done.returncode:
            said = done.stderr.strip() or done.stdout.strip() or "printed nothing"
            raise ValueError(f"{shlex.join(argv)}: exit {done.returncode}: {said}")

    return notice


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The native board at `settings["path"]` (default `.starpulse/board`), created empty when absent, as the project named for `base`'s directory, polled every `interval` seconds.

    Moves, profile changes, creates, edits and archives write the task files directly, and `read` returns a task's record from its file. Any lane reaches any other unless `machine` names a
    machine file, whose transitions and `writers` then decide which moves are offered, and to whom.
    """
    if "rules" in settings:
        raise ValueError("board: `[[board.rules]]` is now `[[board.guards]]`; rename the table")
    if unknown := sorted(settings.keys() - _SETTINGS):
        raise ValueError(f"board: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_SETTINGS))}")
    file_name = str(settings.get("task_file_name", _FILE_NAMES[0]))
    if file_name not in _FILE_NAMES:
        raise ValueError(f"board: task_file_name {file_name!r} is not one of {', '.join(sorted(_FILE_NAMES))}")
    proposal_prefix = str(settings.get("proposal_prefix", ""))
    _python_path(settings.get("python_path"), base)
    root = base / str(settings.get("path", DEFAULT_PATH))
    _create(root, base.resolve().name)
    link = _doc_linker(root, base)
    evaluate = criteria.evaluator(settings.get("criteria"), base)
    migrations: Mapping[str, str] = {}
    if "machine" in settings:
        from starpulse.machine_engine.adapters.machine_loader import (  # noqa: PLC0415 - import cost, paid on first use
            _read,
        )

        migrations = _read(base / str(settings["machine"])).get("migrations", {})
    retired = _Retired()
    claims = _Claims()
    guard = Guard(
        rules.load(settings.get("guards")),
        _hook(settings.get("validate")),
        _state_of(root, retired),
        pull_of=_pull_of(retired),
        types=_types(settings),
    )

    def assign(task: str, profile: str, /, actor: str = OPERATOR) -> Written:
        def edit(frontmatter: dict, body: str) -> str:
            frontmatter["profile"] = [profile]
            return body

        return _update(root, task, edit, guard, actor)

    def surfaces(config: BacklogConfig, roles: StateRoles) -> dict[str, Any]:
        ready = next((status for status in config.statuses if lane_id(status) == roles.ready), "")
        gate = replace(guard, waiting=roles.waiting, ready=ready, holders=_holders(root, roles.done))
        proposals = (roles.proposed or "", proposal_prefix)
        return {
                "writer": _writer(root, config.statuses, roles, gate, claims),
                "release": _releaser(root, gate),
                "assign": assign,
                "create": _creator(root, config, retired, gate, file_name, link, proposals),
                "read": _reader(
                    root, evaluate.latest if isinstance(evaluate, criteria.Evaluator) else evaluate, roles.done
                ),
                "read_archived": _reader(root, _no_criteria, roles.done, ("archive/tasks",)),
                "evaluate": evaluate,
                "holds": _holds(settings.get("holds"), base),
                "unfinished": _holds(settings.get("unfinished"), base),
                "parked": _notice(settings.get("parked"), base),
                "released": _notice(settings.get("released"), base),
                "delivered": _notice(settings.get("delivered"), base),
                "returned": _notice(settings.get("returned"), base),
                "verifying": _notice(settings.get("verifying"), base),
                "closed": _notice(settings.get("closed"), base),
                "edit": _editor(root, config.statuses, gate, link, roles.attention, _unstarted(roles)),
                "archive": _archiver(root, config.statuses, roles, gate),
                "restore": _restorer(root, retired, config.statuses, migrations, gate),
                "complete": _completer(root, config.statuses, roles),
                "retire": _retirer(root, retired, roles),
                "retired": _retired_reader(retired),
                "retired_projected": retired.projected,
                "import_retired": _importer(root, retired),
                "docs": native_docs.lister(root),
                "read_doc": native_docs.reader(root),
                "create_doc": native_docs.creator(root),
                "edit_doc": native_docs.editor(root),
                "archive_doc": native_docs.archiver(root),
                "restore_doc": native_docs.restorer(root),
                "milestones": native_milestones.lister(root),
                "read_milestone": native_milestones.reader(root),
                "create_milestone": native_milestones.creator(root),
                "edit_milestone": native_milestones.editor(root),
                "archive_milestone": native_milestones.archiver(root),
        }

    made = project_board(
        root,
        settings,
        base,
        surfaces,
        retired.changes(),
        guard.standing,
        guard.readable,
    )

    history = TaskHistory()

    def attach(log: EventLog) -> None:
        retired.engine = log.engine  # the retired tasks live in the view's history store
        claims.log = log
        history.attach(log.engine)
        history.import_retired(retired.pairs(), lambda text: _record_of(text, "", lambda *_: []))

    def start(feed: BoardFeed, group: str, log: EventLog) -> None:
        attach(log)
        made.start(feed, group, log)
        sweep(feed, log, lambda _expiries: None)  # this process serves its own sweep's expiries

    def sweep(feed: BoardFeed, log: EventLog, persist: Callable[[dict[str, float]], None]) -> None:
        from starpulse.board.adapters import claim_ttl  # noqa: PLC0415 — keeps the board's import light

        claim_ttl.start(replace(made, **recorded), feed, log, settings, persist)

    read = made.read

    def promoted(write: MoveWriter) -> MoveWriter:
        """`write`, a proposal it moves into the task lanes renumbered when the board has a proposal prefix."""
        if not (proposal_prefix and made.roles.proposed):
            return write
        renumber = history.renumbered(_renumberer(root, read_config(root).prefix, retired, file_name), read)
        return _promoter(write, read, renumber, (made.roles.proposed, made.roles.final or "", proposal_prefix))

    recorded = {
        "writer": promoted(history.recorded(made.writer, read, actor_at=1)),
        "assign": history.recorded(made.assign, read),
        "release": history.recorded(made.release, read, actor_at=1),
        "edit": history.recorded(made.edit, read, unstarted=_unstarted(made.roles)),
        "archive": history.recorded(
            made.archive, read, reason_at=0, also=lambda task: _open_dependents(root, task, None)
        ),
        "restore": history.recorded(made.restore, read),
        "complete": history.recorded(made.complete, read),
        "retire": history.recorded(made.retire, read),
        "create": history.created(made.create, read),
        "reconcile": history.reconciled(_own(root, read)),
        "files": lambda: [(task, _aliases(frontmatter)) for task, frontmatter in _open_tasks(root, made.roles.done)],
    }
    return replace(made, start=start, sweep=sweep, attach=attach, standing=_standing(root, guard), readable=guard.readable, **recorded)


def _own(root: Path, read: Callable[[str], Any]) -> Callable[[str], Any]:
    """`read`, but None for an id only another task's file lists as an alias: that id's task is gone, renamed."""

    def own(task: str) -> Any:
        path = _find(root, task)
        try:
            frontmatter, _ = _split(path.read_text()) if path else ({}, "")
        except OSError:
            return None
        held = str(frontmatter.get("id") or "").strip() or task
        return read(task) if path and held.casefold() == task.casefold() else None

    return own


def _standing(root: Path, guard: Guard) -> Callable[[str, str], dict[str, Any] | None]:
    """The board rules' verdict on moving the task `task` to `lane` as its file stands now, or None for a task with no
    file or no refusing rule."""

    def standing(task: str, lane: str) -> dict[str, Any] | None:
        if (path := _find(root, task)) is None:
            return None
        try:
            front, body = _split_record(path.read_text())
        except OSError:
            return None
        return guard.standing(front, body, lane)

    return standing
