"""StarPulse's own board: one Markdown file per task under `.starpulse/board/`, written in Python.

The files use the front matter Backlog.md's tasks use, so `starpulse._internal.board.upstream_backlog` reads them: the lanes are the
`statuses` of `config.yml` and a task is a file under `tasks/`. This adapter adds what that one lacks, a writer that
edits the files with no `backlog` CLI, and creates the board, empty, when its directory is absent. It is the default
`[board]` adapter.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlalchemy import delete, func, insert, select
from sqlalchemy.engine import Engine

from starpulse._internal.board import native_docs, native_milestones, rules
from starpulse._internal.board.seam import (
    HELD,
    MERGE_EVIDENCE,
    OPERATOR,
    Board,
    MoveWriter,
    RetiredImporter,
    RetiredReader,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskRestorer,
    TaskRetirer,
    Written,
)
from starpulse._internal.board.task_history import TaskHistory
from starpulse._internal.board.upstream_backlog import (
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
)
from starpulse._internal.board.upstream_backlog import (
    _assignee as _assignee_of,
)
from starpulse._internal.board.upstream_backlog import (
    _profile as _profile_of,
)
from starpulse._internal.eventlog.lane_events import ARCHIVED, COMPLETED
from starpulse._internal.eventlog.tables import retired_tasks
from starpulse._internal.feed import criteria
from starpulse._internal.machines.state_roles import StateRoles

if TYPE_CHECKING:
    from starpulse._internal.eventlog.event_log import EventLog
    from starpulse._internal.feed.board_feed import BoardFeed

#: Where the board lives, relative to the config's directory (or the working directory without a config).
DEFAULT_PATH = ".starpulse/board"
#: The `[board]` settings this adapter reads: `path` is the board's directory, `machine` a machine file for the Board,
#: relative to the config, `criteria` the command that evaluates a task's Start Criteria (`{id}` is the task's id),
#: `validate` the `module:function` that may refuse a task write before it lands, `guards` the record-level rules every
#: task write must satisfy (the `rules` module of `starpulse._internal.board`), `task_file_name` the form of the name a created task's
#: file is written under (`_FILE_NAMES`), `types` the names a task's `type` may take (any when absent).
_SETTINGS = {"type", "path", "interval", "machine", "criteria", "holds", "validate", "guards", "task_file_name", "types"}
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
#: A task write's check: the file's path, its text before (None for a create) and the text about to be written; it
#: returns why the write is refused, or None to let it land.
Validate = Callable[[Path, "str | None", str], "str | None"]
#: The stamps' format, read as UTC.
_STAMP = "%Y-%m-%d %H:%M"
_NOTES_END = re.compile(r"\s*<!-- SECTION:NOTES:END -->")
_PLAN = re.compile(r"<!-- SECTION:PLAN:BEGIN -->(.*?)<!-- SECTION:PLAN:END -->", re.S)
_DONE = re.compile(r"<!-- DOD:BEGIN -->(.*?)<!-- DOD:END -->", re.S)
_FINAL_SUMMARY = re.compile(r"<!-- SECTION:FINAL_SUMMARY:BEGIN -->(.*?)<!-- SECTION:FINAL_SUMMARY:END -->", re.S)
_COMMENTS_SECTION = re.compile(r"<!-- COMMENTS:BEGIN -->(.*?)<!-- COMMENTS:END -->", re.S)
_COMMENT_HEAD = re.compile(r"^created: (\S+ \S+)\n---\n", re.M)
_SESSION_LINK = re.compile(r"^\*\*Session Link:\*\* (\S+)", re.M)
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


def _find(root: Path, task: str, folders: tuple[str, ...] = ("tasks", "completed")) -> Path | None:
    """The file under `tasks/`, or `completed/` once it is completed, whose front matter holds `id: <task>` in any case;
    `folders` names where else to look.

    A file named for the id is checked first; any other is parsed only when its raw front matter has an `id:` line
    spelling the id, so a lookup parses the file it returns rather than every file on the board. The file found last
    time is tried before the folders are listed; one that was renamed, moved or rewritten for another task is a miss.
    """
    key = (root, task.casefold(), folders)
    if (path := _FOUND.get(key)) is not None and _has_id(path, task, _id_line(task), False):
        return path
    paths = [path for folder in folders for path in sorted((root / folder).glob("*.md"))]
    named = [path for path in paths if _named_for(path, task)]
    others = [path for path in paths if not _named_for(path, task)]
    spelled = _id_line(task)
    for candidates, prefilter in ((named, False), (others, True)):
        for path in candidates:
            if _has_id(path, task, spelled, prefilter):
                _FOUND[key] = path
                return path
    _FOUND.pop(key, None)
    return None


def _has_id(path: Path, task: str, spelled: re.Pattern[str], prefilter: bool) -> bool:
    """Whether the file's front matter has `id: <task>`; `prefilter` skips the parse of a file whose raw text does not spell it."""
    try:
        text = path.read_text()
    except OSError:
        return False  # moved or removed while looking
    if prefilter and not spelled.search(_front_matter(text)):
        return False
    frontmatter, _ = _split(text)
    return isinstance(frontmatter, dict) and str(frontmatter.get("id") or "").strip().casefold() == task.casefold()


def _named_for(path: Path, task: str) -> bool:
    """Whether the file's name starts with the id, as `task-5 - Title.md` does for `task-5` but not for `task-50`."""
    name = path.name
    return name[: len(task)].lower() == task.lower() and not name[len(task) : len(task) + 1].isalnum()


def _front_matter(text: str) -> str:
    """The raw text between a file's `---` fences, empty for a file with none."""
    text = text.replace("\r\n", "\n")
    end = text.find("\n---", 4)
    return text[4:end] if text.startswith("---\n") and end != -1 else ""


def _id_line(task: str) -> re.Pattern[str]:
    """A front matter line that spells `task` as the `id:`, quoted or not, in any case."""
    return re.compile(rf"^id:[ \t]*[\"']?{re.escape(task)}[\"']?[ \t]*$", re.M | re.I)


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


@dataclass(frozen=True)
class _Guard:
    """What a task write must pass before it lands: the declared `types`, the board's rules, then its `validate` hook."""

    rules: tuple[rules.Rule, ...] = ()
    validate: Validate | None = None
    #: The state of another task (a dependency a rule reads), or None when the board has none.
    state_of: Callable[[str], str | None] = lambda _: None
    #: The names a task's `type` may take; empty accepts any.
    types: tuple[str, ...] = ()

    def standing(self, front: Mapping[str, Any], body: str, lane: str) -> tuple[str, str] | None:
        """The reason and skill of the board rule that refuses moving the task to `lane`, or None (`rules.standing_refusal`)."""
        broken = rules.standing_refusal(self.rules, front, body, lane)
        return None if broken is None else (broken.reason, broken.skill)

    def refusal(
        self, path: Path, before: str | None, frontmatter: dict, body: str, text: str, actor: str
    ) -> Written | None:
        """Why the write of `text` over `before` (None for a create) by `actor` is refused, or None to let it land."""
        kind = str(frontmatter.get("type") or "")
        was = str(
            _split_record(before or "")[0].get("type") or ""
        )  # a write that leaves the type alone is not refused for it
        if self.types and kind and kind != was and kind not in self.types:
            return Written(False, f"type {kind!r} is not one of this board's types: {', '.join(self.types)}")
        if self.rules:
            earlier = None if before is None else rules.Record(*_split_record(before))
            if broken := rules.refusal(self.rules, earlier, rules.Record(frontmatter, body, self.state_of), actor):
                return Written(False, broken.reason, broken.skill)
        if self.validate is not None and (reason := self.validate(path, before, text)):
            return Written(False, reason)
        return None


def _split_record(text: str) -> tuple[dict, str]:
    frontmatter, body = _split(text)
    return (frontmatter if isinstance(frontmatter, dict) else {}), body


#: Returned by `_land` when the file no longer holds the text the write was made over.
_STALE = Written(False, "the task file changed while it was being written")
#: How many times `_update` redoes an edit on a file that changed under it before it gives up.
_ATTEMPTS = 5


def _land(path: Path, before: str | None, frontmatter: dict, body: str, guard: _Guard, actor: str) -> Written | None:
    """Write the task file at `path` in one rename, unless `guard` refuses `actor`'s write or the file no longer holds
    `before`: the refusal (`_STALE` for a changed file), or None once it landed."""
    text = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---{body}"
    if refused := guard.refusal(path, before, frontmatter, body, text, actor):
        return refused
    if before is not None and path.read_text() != before:
        return _STALE
    # Unique per write, so concurrent writers never share a scratch file; not a `.md` file, so a scan never reads it half written.
    scratch = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    scratch.write_text(text)
    os.replace(scratch, path)
    return None


def _update(
    root: Path, task: str, edit: Callable[[dict, str], str], guard: _Guard = _Guard(), actor: str = OPERATOR
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
        {"created": head[1], "text": region[head.end() : end].rstrip().removesuffix("---").strip()}
        for head, end in zip(heads, ends, strict=False)
    ]


def _recorded(text: str, comments: list[dict[str, str]]) -> bool:
    """Whether the task already records `text`: merge evidence anywhere, a hold only as its latest hold comment."""
    texts = [c["text"] for c in comments]
    if text.startswith(MERGE_EVIDENCE):
        return text.strip() in texts
    holds = [t for t in texts if t.startswith(HELD)]
    return text.startswith(HELD) and bool(holds) and holds[-1] == text.strip()


def _session(notes: str, comments: list[dict[str, str]]) -> str:
    """The link of the latest `**Session Link:**` line: the newest comment that has one, else the notes', else empty."""
    texts = [notes, *(comment["text"] for comment in comments)]
    links = [link for text in texts for link in _SESSION_LINK.findall(text)]
    return links[-1] if links else ""


def _reader(root: Path, evaluate: Callable[[str, str], list[dict[str, Any]]]) -> TaskReader:
    """A board reader: the record of the task's file, keyed by the fields the task view draws and edits.

    `start_criteria` is the description's Start Criteria, each with the result `evaluate` gives it."""

    def read(task: str, /) -> dict[str, Any] | None:
        if (path := _find(root, task)) is None:
            return None
        try:
            frontmatter, body = _split(path.read_text())
        except OSError:
            return None  # moved or removed while reading
        description = _description(body)
        notes, comments = _section(_NOTES, body), _comments(body)
        return {
            "title": str(frontmatter.get("title") or ""),
            "type": str(frontmatter.get("type") or ""),
            "status": str(frontmatter.get("status") or ""),
            "profile": _profile_of(frontmatter),
            "priority": str(frontmatter.get("priority") or ""),
            "impact": str(frontmatter.get("impact") or ""),
            "urgency": str(frontmatter.get("urgency") or ""),
            "labels": list(_strings(frontmatter.get("labels"))),
            "milestone": str(frontmatter.get("milestone") or ""),
            "dependencies": list(_strings(frontmatter.get("dependencies"))),
            "references": list(_strings(frontmatter.get("references"))),
            "documentation": list(_strings(frontmatter.get("documentation"))),
            "modifiedFiles": list(_strings(frontmatter.get("modified_files"))),
            "description": description,
            "start_criteria": evaluate(task, description),
            "plan": _section(_PLAN, body),
            "notes": notes,
            "finalSummary": _section(_FINAL_SUMMARY, body),
            "comments": comments,
            "session": _session(notes, comments),
            "acceptanceCriteria": _items(_CRITERIA, body),
            "definitionOfDone": _items(_DONE, body),
        }

    return read


#: The sections an edit rewrites as text: the field's name, the markers' name and the heading a new section gets.
_TEXT_SECTIONS = {
    "description": ("DESCRIPTION", "Description"),
    "plan": ("PLAN", "Implementation Plan"),
    "notes": ("NOTES", "Implementation Notes"),
    "finalSummary": ("FINAL_SUMMARY", "Final Summary"),
}
#: The checklists an edit rewrites: the field's name, the markers' name, the heading a new section gets and its pattern.
_CHECKLISTS = {
    "acceptanceCriteria": ("AC", "Acceptance Criteria", _CRITERIA),
    "definitionOfDone": ("DOD", "Definition of Done", _DONE),
}
_SCALARS = {
    "title": "title",
    "type": "type",
    "priority": "priority",
    "impact": "impact",
    "urgency": "urgency",
    "milestone": "milestone",
}
_LISTS = {
    "labels": "labels",
    "dependencies": "dependencies",
    "references": "references",
    "documentation": "documentation",
    "modifiedFiles": "modified_files",
}
#: The lists whose key a task file leaves out while it holds nothing.
_OPTIONAL_LISTS = {"references", "documentation", "modified_files"}
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


def _comment(body: str, text: str) -> str:
    """`body` with `text` appended to its comments, as the Backlog this workspace runs writes one."""
    entry = f"created: {datetime.now():%Y-%m-%d %H:%M}\n---\n{text.strip()}\n---\n\n"
    if _COMMENTS.search(body):
        return _COMMENTS.sub(lambda end: f"{entry}{end.group()}", body, count=1)
    return body.rstrip("\n") + f"\n\n## Comments\n\n<!-- COMMENTS:BEGIN -->\n{entry}<!-- COMMENTS:END -->\n"


def _append_notes(body: str, text: str) -> str:
    """`body` with `text` on a new line at the end of its notes, which a body without notes gets as its first."""
    if _NOTES_END.search(body):
        return _NOTES_END.sub(lambda end: f"\n{text}{end.group()}", body, count=1)
    return body.rstrip("\n") + "\n" + _NOTES_SECTION.format(text)


def _set_front(frontmatter: dict, field: str, value: Any, spelled: Mapping[str, str]) -> bool:
    """Set `field` in `frontmatter` and say so, or say it is no front matter field, leaving `frontmatter` as it was."""
    if field in _SCALARS:
        text = _text(field, value)
        if not text and field == "title":
            raise ValueError("title cannot be empty")
        frontmatter[field] = text
        if not text:
            del frontmatter[field]
    elif field == "profile":
        frontmatter.pop("assignee", None)
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


def _editor(root: Path, statuses: tuple[str, ...], guard: _Guard = _Guard(), link: _Linker = _unlinked) -> TaskEditor:
    """A board writer that applies every change to a task's file in one write, or refuses the whole edit.

    `changes` holds the new value of each field `read` names except `comments`, which `comment` appends to: one text, or a
    list appended in order, each blank one skipped; `appendNotes` is one more, text added to the end of the notes. An
    empty priority, milestone, profile or type and an empty references, documentation or modified-files list removes its
    key, a status is spelled as its lane is, a checklist item without a number is new, and `link` reads a doc id in the
    documentation list as its file.
    """
    spelled = {lane_id(status): status for status in statuses}

    def edit(task: str, changes: Mapping[str, Any], comment: str | Sequence[str], /, actor: str = OPERATOR) -> Written:
        def apply(frontmatter: dict, body: str) -> str:
            body = _apply(task, frontmatter, body, link(changes), spelled)
            for text in [comment] if isinstance(comment, str) else comment:
                recorded = _recorded(text, _comments(body))
                body = _comment(body, text) if text.strip() and not recorded else body
            return body

        try:
            written = _update(root, task, apply, guard, actor)
        except ValueError as refusal:  # raised before the file is written, so a refusal writes nothing
            return Written(False, f"{task}: {refusal}")
        status = str(changes.get("status") or "")
        return _moved(written, spelled.get(lane_id(status), status)) if status else written

    return edit


def _open_dependents(root: Path, task: str, done: str | None) -> list[str]:
    """Ids of the tasks under `tasks/` that are not Done and list `task` as a dependency, in file order."""
    found = []
    for path in sorted((root / "tasks").glob("*.md")):
        try:
            frontmatter, _ = _split(path.read_text())
        except OSError:
            continue  # moved or removed while looking
        if not isinstance(frontmatter, dict) or lane_id(str(frontmatter.get("status") or "")) == done:
            continue
        if task.casefold() in {dependency.casefold() for dependency in _strings(frontmatter.get("dependencies"))}:
            found.append(str(frontmatter.get("id") or path.stem).strip())
    return found


def _unlinker(task: str, reason: str, ready: str | None, waiting: str | None) -> Callable[[dict, str], str]:
    """An edit that drops `task` from a task's dependencies and says why; a Waiting task left with no dependency and
    no Start Criteria moves to `ready`, since the release pass reads only Waiting tasks that still have one."""
    note = f"Removed dependency on {task}: archived" + (f" ({reason.strip()})" if reason.strip() else "")

    def edit(frontmatter: dict, body: str) -> str:
        kept = [name for name in _strings(frontmatter.get("dependencies")) if name.casefold() != task.casefold()]
        frontmatter["dependencies"] = kept
        held = lane_id(str(frontmatter.get("status") or "")) == waiting
        if held and not kept and ready is not None and not criteria.authored(body):
            frontmatter["status"] = ready
            return _comment(body, f"{note}; no dependency is left, so it moved to {ready}.")
        return _comment(body, note)

    return edit


def _archiver(root: Path, statuses: tuple[str, ...], roles: StateRoles, guard: _Guard = _Guard()) -> TaskArchiver:
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
                    root, task, lambda _, body: _comment(body, f"Archived: {reason.strip()}"), guard, actor
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
        if self.engine is None:
            return []
        query = select(retired_tasks.c.task, retired_tasks.c.name, retired_tasks.c.text).order_by(retired_tasks.c.task)
        if task:
            query = query.where(func.lower(retired_tasks.c.task) == task.lower())
        if milestone:  # the text search narrows the rows; the front matter decides
            query = query.where(retired_tasks.c.text.contains(milestone))
        with self.engine.connect() as db:
            rows = [dict(row._mapping) for row in db.execute(query)]
        if not milestone:
            return rows
        return [row for row in rows if str(_split_record(row["text"])[0].get("milestone") or "").strip() == milestone]

    def texts(self) -> Iterator[str]:
        """Every retired task's text, by id, a page of rows at a time, so no more than a page is held at once."""
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
            yield from (row.text for row in page)
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
    def read(task: str, milestone: str, /) -> list[Mapping[str, str]]:
        return list(retired.rows(task, milestone))

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


def _restorer(root: Path, retired: _Retired) -> TaskRestorer:
    """A board writer that returns an archived or retired task's file, unchanged, to `tasks/` under its own name.

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
        target = root / "tasks" / path.name
        try:
            os.link(path, target)
            path.unlink()
        except FileExistsError:
            return Written(False, f"{task}: {target} already exists")
        except OSError as error:
            return Written(False, f"{path}: {error}")
        return Written(True, f"Restored task {task}")

    return restore


def _assign(body: str, session: str) -> str:
    """`body` with `**Assignee:** <session>` appended to its notes, which the board reads the assignee from.

    A session the notes already name as assignee is not named again: a claim's edit may have recorded it before the move.
    """
    return body if _assignee_of(body) == session else _append_notes(body, f"**Assignee:** {session}")


class _Claims:
    """Where the board records an agent's refused claim once `attach` binds the event log: one `board:claims` entry."""

    def __init__(self) -> None:
        self.log: EventLog | None = None

    def refused(self, task: str, actor: str, reason: str) -> None:
        """Append the refusal of `actor`'s claim of `task` with its `reason` and the time, fail-open."""
        if self.log is not None:
            from starpulse._internal.feed.claim_refusals import CLAIMS_STREAM  # noqa: PLC0415 - loading a board loads no feed

            self.log._append(CLAIMS_STREAM, {"task": task, "actor": actor, "reason": reason, "time": time.time()})


def _moved(written: Written, lane: str) -> Written:
    """`written` once it landed, with the `lane` it put the task in and the moment, for the server to record with the
    request's actor; a refused write moved nothing."""
    return written._replace(lane=lane, at=time.time()) if written.ok else written


def _writer(
    root: Path, statuses: tuple[str, ...], roles: StateRoles, guard: _Guard = _Guard(), claims: _Claims = _Claims()
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
            return _assign(body, session) if claim else body

        written = _update(root, task, edit, guard, actor)
        if claim and not written.ok:
            claims.refused(task, actor, written.output)
        return _moved(written, spelled.get(lane_id(status), status))

    return write


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


def _next_id(root: Path, prefix: str, retired: _Retired) -> str:
    """`<prefix>-N` with N one past the highest on the board, its completed, archived and retired tasks included."""
    number = re.compile(rf"{re.escape(prefix)}-(\d+)", re.I)
    highest = max((int(found[1]) for task in retired.ids() if (found := number.fullmatch(task))), default=0)
    for folder, _ in _FOLDERS:
        for path in (root / folder).glob("*.md"):
            try:
                frontmatter, _ = _split(path.read_text())
            except OSError:
                continue  # moved or removed while looking
            if isinstance(frontmatter, dict) and (found := number.fullmatch(str(frontmatter.get("id") or "").strip())):
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
    "description",
    "acceptanceCriteria",
    "created_by",
}


def _new_task(task: str, title: str, status: str, details: Mapping[str, Any]) -> str:
    """A new task file as Backlog.md writes one: its front matter, then its Description and Acceptance Criteria."""
    frontmatter: dict[str, Any] = {"id": task, "title": title, "status": status}
    if profile := details.get("profile", details.get("assignee")):
        frontmatter["profile"] = [profile]
    keys = ("labels", "milestone", "dependencies", "priority", "impact", "urgency", "created_by")
    frontmatter |= {key: details[key] for key in keys if key in details}
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
        boundary = head.rfind("-")
        words = (head[:boundary] if boundary > 0 else head).strip("-").split("-")
        while len(words) > 1 and words[-1] in _SLUG_STOPWORDS:
            words.pop()
        slug = "-".join(words)
    return f"{slug}{date}".strip("-") or "untitled"


def _file_name(task: str, title: str, form: str) -> str:
    """The name of the file a task created as `title` is written under, in the `form` of `_FILE_NAMES`."""
    if form == "slug":
        return f"{task.lower()}-{_slug(title)}.md"
    return f"{task} - {re.sub(r'[^\w-]+', '-', title).strip('-')[:60].strip('-') or 'Task'}.md"


def _creator(
    root: Path,
    config: BacklogConfig,
    retired: _Retired,
    guard: _Guard = _Guard(),
    file_name: str = "title",
    link: _Linker = _unlinked,
) -> TaskCreator:
    """A board writer that makes a task file with the next id, named in the `file_name` form, in one write.

    It starts in the first lane; any detail beyond the ones the page fills (a `status`, `type`, `references`,
    `documentation`, `definitionOfDone`, `plan`, `notes` or other field `edit` sets) is set as `edit` sets it, so a
    detail it cannot set refuses the create and nothing is written. A refused create leaves its id to the next one.
    """
    lock = threading.Lock()  # two creates must not both read the same highest id
    spelled = {lane_id(status): status for status in config.statuses}

    def create(title: str, details: Mapping[str, Any], /, actor: str = OPERATOR) -> Written:
        with lock:
            task = _next_id(root, config.prefix, retired)
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


def _holds(command: object, base: Path) -> Callable[[str], list[str]] | None:
    """The `holds` command, run in `base` with `{id}` replaced by the task's id, as the board's holds: it prints a JSON
    array of the reasons the task's `deps_done` is withheld. Output that is no such array raises, which holds the task."""
    if not command:
        return None
    parts = shlex.split(str(command))

    def holds(task: str) -> list[str]:
        argv = [part.replace("{id}", task) for part in parts]
        done = subprocess.run(argv, cwd=base, capture_output=True, text=True, timeout=criteria.TIMEOUT, check=False)
        try:
            printed = json.loads(done.stdout)
        except ValueError:
            printed = None
        if not isinstance(printed, list) or not all(isinstance(reason, str) for reason in printed):
            said = done.stderr.strip() or done.stdout.strip() or "printed nothing"
            raise ValueError(f"{shlex.join(argv)}: exit {done.returncode}: {said}")
        return printed

    return holds


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
    root = base / str(settings.get("path", DEFAULT_PATH))
    _create(root, base.resolve().name)
    link = _doc_linker(root, base)
    evaluate = criteria.evaluator(settings.get("criteria"), base)
    retired = _Retired()
    claims = _Claims()
    guard = _Guard(
        rules.load(settings.get("guards")), _hook(settings.get("validate")), _state_of(root, retired), _types(settings)
    )

    def assign(task: str, profile: str, /, actor: str = OPERATOR) -> Written:
        def edit(frontmatter: dict, body: str) -> str:
            frontmatter.pop("assignee", None)
            frontmatter["profile"] = [profile]
            return body

        return _update(root, task, edit, guard, actor)

    made = project_board(
        root,
        settings,
        base,
        lambda config, roles: {
            "writer": _writer(root, config.statuses, roles, guard, claims),
            "assign": assign,
            "create": _creator(root, config, retired, guard, file_name, link),
            "read": _reader(root, evaluate.latest if isinstance(evaluate, criteria.Evaluator) else evaluate),
            "evaluate": evaluate,
            "holds": _holds(settings.get("holds"), base),
            "edit": _editor(root, config.statuses, guard, link),
            "archive": _archiver(root, config.statuses, roles, guard),
            "restore": _restorer(root, retired),
            "complete": _completer(root, config.statuses, roles),
            "retire": _retirer(root, retired, roles),
            "retired": _retired_reader(retired),
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
        },
        retired.changes(),
        guard.standing,
    )

    history = TaskHistory()

    def attach(log: EventLog) -> None:
        retired.engine = log.engine  # the retired tasks live in the view's history store
        claims.log = log
        history.attach(log.engine)

    def start(feed: BoardFeed, group: str, log: EventLog) -> None:
        attach(log)
        made.start(feed, group, log)

    read = made.read
    recorded = {
        "writer": history.recorded(made.writer, read, actor_at=1),
        "assign": history.recorded(made.assign, read),
        "edit": history.recorded(made.edit, read),
        "archive": history.recorded(made.archive, read, reason_at=0),
        "restore": history.recorded(made.restore, read),
        "complete": history.recorded(made.complete, read),
        "retire": history.recorded(made.retire, read),
        "create": history.created(made.create, read),
    }
    return replace(made, start=start, attach=attach, **recorded)
