"""StarPulse's own board: one Markdown file per task under `.starpulse/board/`, written in Python.

The files use the front matter Backlog.md's tasks use, so `starpulse._internal.board.upstream_backlog` reads them: the lanes are the
`statuses` of `config.yml` and a task is a file under `tasks/`. This adapter adds what that one lacks, a writer that
edits the files with no `backlog` CLI, and creates the board, empty, when its directory is absent. It is the default
`[board]` adapter.
"""

from __future__ import annotations

import importlib
import os
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from starpulse._internal.board import native_docs, native_milestones, rules
from starpulse._internal.board.seam import (
    Board,
    OPERATOR,
    MoveWriter,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskRestorer,
    Written,
)
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
from starpulse._internal.feed import criteria

#: Where the board lives, relative to the config's directory (or the working directory without a config).
DEFAULT_PATH = ".starpulse/board"
#: The `[board]` settings this adapter reads: `path` is the board's directory, `machine` a machine file for the Board,
#: relative to the config, `criteria` the command that evaluates a task's Start Criteria (`{id}` is the task's id),
#: `validate` the `module:function` that may refuse a task write before it lands, `rules` the record-level rules every
#: task write must satisfy (`starpulse._internal.board.rules`).
_SETTINGS = {"type", "path", "interval", "machine", "criteria", "validate", "rules"}
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
_NOTES_SECTION = "\n## Implementation Notes\n\n<!-- SECTION:NOTES:BEGIN -->\n{}\n<!-- SECTION:NOTES:END -->\n"


def _create(root: Path, project: str) -> None:
    """Make an empty board in `root` when it is absent: the project it belongs to, the default lanes and a `tasks/` directory, nothing else."""
    if not root.exists():
        (root / "tasks").mkdir(parents=True)
        (root / "config.yml").write_text(
            yaml.safe_dump(
                {"project_name": project, "statuses": list(DEFAULT_STATUSES), "task_prefix": DEFAULT_PREFIX},
                sort_keys=False,
            )
        )


def _find(root: Path, task: str, folders: tuple[str, ...] = ("tasks", "completed")) -> Path | None:
    """The file under `tasks/`, or `completed/` once it is completed, whose front matter holds `id: <task>`; `folders`
    names where else to look.

    A file named for the id is checked first; any other is parsed only when its raw front matter has an `id:` line
    spelling the id, so a lookup parses the file it returns rather than every file on the board.
    """
    paths = [path for folder in folders for path in sorted((root / folder).glob("*.md"))]
    named = [path for path in paths if _named_for(path, task)]
    others = [path for path in paths if not _named_for(path, task)]
    spelled = _id_line(task)
    for candidates, prefilter in ((named, False), (others, True)):
        for path in candidates:
            try:
                text = path.read_text()
            except OSError:
                continue  # moved or removed while looking
            if prefilter and not spelled.search(_front_matter(text)):
                continue
            frontmatter, _ = _split(text)
            if isinstance(frontmatter, dict) and str(frontmatter.get("id") or "").strip() == task:
                return path
    return None


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
    """A front matter line that spells `task` as the `id:`, quoted or not."""
    return re.compile(rf"^id:[ \t]*[\"']?{re.escape(task)}[\"']?[ \t]*$", re.M)


def _state_of(root: Path) -> Callable[[str], str | None]:
    """A lookup of the state (its lane id) a task's file is in, None for a task with no file."""

    def state(task: str) -> str | None:
        if (path := _find(root, task)) is None:
            return None
        try:
            frontmatter, _ = _split(path.read_text())
        except OSError:
            return None  # moved or removed while looking
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


def _stamped(frontmatter: dict, *, created: bool = False) -> dict:
    """`frontmatter` with `updated_date` (and `created_date` on a new task) set to now in UTC, after the assignee or status."""
    now = f"{datetime.now(timezone.utc):{_STAMP}}"
    stamps = {key: now for key in ("created_date", "updated_date") if created or key == "updated_date"}
    anchor = "assignee" if "assignee" in frontmatter else "status"
    stamped: dict[str, Any] = {}
    for key, value in frontmatter.items():
        stamped[key] = stamps.get(key, value)
        if key == anchor:
            stamped |= {stamp: now for stamp in stamps if stamp not in frontmatter}
    return stamped


@dataclass(frozen=True)
class _Guard:
    """What a task write must pass before it lands: the board's rules, then its `validate` hook."""

    rules: tuple[rules.Rule, ...] = ()
    validate: Validate | None = None
    #: The state of another task (a dependency a rule reads), or None when the board has none.
    state_of: Callable[[str], str | None] = lambda _: None

    def refusal(
        self, path: Path, before: str | None, frontmatter: dict, body: str, text: str, actor: str
    ) -> Written | None:
        """Why the write of `text` over `before` (None for a create) by `actor` is refused, or None to let it land."""
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


def _land(path: Path, before: str | None, frontmatter: dict, body: str, guard: _Guard, actor: str) -> Written | None:
    """Write the task file at `path` in one rename, unless `guard` refuses `actor`'s write: the refusal, or None once
    it landed."""
    text = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---{body}"
    if refused := guard.refusal(path, before, frontmatter, body, text, actor):
        return refused
    scratch = path.with_name(f"{path.name}.tmp")  # not a `.md` file, so a scan never reads it half written
    scratch.write_text(text)
    os.replace(scratch, path)
    return None


def _update(
    root: Path, task: str, edit: Callable[[dict, str], str], guard: _Guard = _Guard(), actor: str = OPERATOR
) -> Written:
    """Rewrite the file of `task` with its front matter edited in place, its body as `edit` returns it and a new
    `updated_date`, as `actor`."""
    if (path := _find(root, task)) is None:
        return Written(False, f"{task} has no task file in {root / 'tasks'}")
    try:
        before = path.read_text()
        frontmatter, body = _split(before)
        body = edit(frontmatter, body)
        if refused := _land(path, before, _stamped(frontmatter), body, guard, actor):
            return refused
    except OSError as error:
        return Written(False, f"{path}: {error}")
    return Written(True, f"Updated task {task}")


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
        return {
            "title": str(frontmatter.get("title") or ""),
            "type": str(frontmatter.get("type") or ""),
            "status": str(frontmatter.get("status") or ""),
            "profile": next(iter(_strings(frontmatter.get("assignee"))), ""),
            "priority": str(frontmatter.get("priority") or ""),
            "labels": list(_strings(frontmatter.get("labels"))),
            "milestone": str(frontmatter.get("milestone") or ""),
            "dependencies": list(_strings(frontmatter.get("dependencies"))),
            "references": list(_strings(frontmatter.get("references"))),
            "documentation": list(_strings(frontmatter.get("documentation"))),
            "modifiedFiles": list(_strings(frontmatter.get("modified_files"))),
            "description": description,
            "start_criteria": evaluate(task, description),
            "plan": _section(_PLAN, body),
            "notes": _section(_NOTES, body),
            "finalSummary": _section(_FINAL_SUMMARY, body),
            "comments": _comments(body),
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
_SCALARS = {"title": "title", "type": "type", "priority": "priority", "milestone": "milestone"}
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
    """`body` with the checklist `field` set to `value`: an item with a number keeps it and one without takes the next."""
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
    following = max(known, default=0)
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
        frontmatter["assignee"] = [_text(field, value)]
        if not frontmatter["assignee"][0]:
            del frontmatter["assignee"]
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


def _editor(root: Path, statuses: tuple[str, ...], guard: _Guard = _Guard()) -> TaskEditor:
    """A board writer that applies every change to a task's file in one write, or refuses the whole edit.

    `changes` holds the new value of each field `read` names except `comments`, which `comment` appends to: one text, or a
    list appended in order, each blank one skipped; `appendNotes` is one more, text added to the end of the notes. An
    empty priority, milestone, assignee or type and an empty references, documentation or modified-files list removes its
    key, a status is spelled as its lane is, and a checklist item without a number is new.
    """
    spelled = {lane_id(status): status for status in statuses}

    def edit(task: str, changes: Mapping[str, Any], comment: str | Sequence[str], /, actor: str = OPERATOR) -> Written:
        def apply(frontmatter: dict, body: str) -> str:
            body = _apply(task, frontmatter, body, changes, spelled)
            for text in [comment] if isinstance(comment, str) else comment:
                body = _comment(body, text) if text.strip() else body
            return body

        try:
            return _update(root, task, apply, guard, actor)
        except ValueError as refusal:  # raised before the file is written, so a refusal writes nothing
            return Written(False, f"{task}: {refusal}")

    return edit


def _archiver(root: Path, guard: _Guard = _Guard()) -> TaskArchiver:
    """A board writer that moves a task's file to `archive/tasks/`, from any lane, after recording a non-blank reason as a comment."""

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
        target = root / "archive" / "tasks" / path.name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, target)
        except OSError as error:
            return Written(False, f"{path}: {error}")
        return Written(True, f"Archived task {task}")

    return archive


def _restorer(root: Path) -> TaskRestorer:
    """A board writer that returns an archived task's file, unchanged, to `tasks/` under its own name.

    The task is refused while its number is open or completed, and when the name is taken: the file is linked into
    place, so a file another writer put there first is never replaced."""

    def restore(task: str, /) -> Written:
        if _find(root, task) is not None:
            return Written(False, f"{task} is already on the board")
        if (path := _find(root, task, ("archive/tasks",))) is None:
            return Written(False, f"{task} has no archived task file in {root / 'archive' / 'tasks'}")
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


def _holder(body: str, session: str) -> str:
    """`body` with `**Holder:** <session>` appended to its notes, which the board reads the holder from."""
    return _append_notes(body, f"**Holder:** {session}")


def _writer(root: Path, statuses: tuple[str, ...], guard: _Guard = _Guard()) -> MoveWriter:
    """A board writer that sets a status in the task's file. A lane's status is the board's own spelling of it.

    An agent's claim (a move to `In Progress` that names its session) also records the session as the task's holder.
    """
    spelled = {lane_id(status): status for status in statuses}

    def write(task: str, status: str, actor: str, session: str = "") -> Written:
        claim = actor != OPERATOR and session and lane_id(status) == "in_progress"

        def edit(frontmatter: dict, body: str) -> str:
            frontmatter["status"] = spelled.get(lane_id(status), status)
            return _holder(body, session) if claim else body

        return _update(root, task, edit, guard, actor)

    return write


def _completer(root: Path) -> TaskCompleter:
    """A board writer that moves a Done task's file to `completed/`, where the reader and the projection still find it."""

    def complete(task: str, /) -> Written:
        if (path := _find(root, task)) is None:
            return Written(False, f"{task} has no task file in {root / 'tasks'}")
        if path.parent.name == "completed":
            return Written(False, f"{task} is already completed")
        status = str(_split(path.read_text())[0].get("status") or "")
        if lane_id(status) != "done":
            return Written(False, f"{task} is {status or 'without a status'}, not Done")
        target = root / "completed" / path.name
        try:
            target.parent.mkdir(exist_ok=True)
            os.replace(path, target)
        except OSError as error:
            return Written(False, f"{path}: {error}")
        return Written(True, f"Completed task {task}")

    return complete


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


#: The details `_new_task` writes itself; any other detail is set as `edit` sets that field.
_NEW_TASK_DETAILS = {"assignee", "labels", "milestone", "dependencies", "priority", "description", "acceptanceCriteria"}


def _new_task(task: str, title: str, status: str, details: Mapping[str, Any]) -> str:
    """A new task file as Backlog.md writes one: its front matter, then its Description and Acceptance Criteria."""
    frontmatter: dict[str, Any] = {"id": task, "title": title, "status": status}
    if "assignee" in details:
        frontmatter["assignee"] = [details["assignee"]]
    frontmatter |= {key: details[key] for key in ("labels", "milestone", "dependencies", "priority") if key in details}
    text = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---\n"
    if description := details.get("description"):
        text += (
            f"\n## Description\n\n<!-- SECTION:DESCRIPTION:BEGIN -->\n{description}\n<!-- SECTION:DESCRIPTION:END -->\n"
        )
    if criteria := details.get("acceptanceCriteria"):
        items = "".join(f"- [ ] #{n} {item}\n" for n, item in enumerate(criteria, 1))
        text += f"\n## Acceptance Criteria\n<!-- AC:BEGIN -->\n{items}<!-- AC:END -->\n"
    return text


def _creator(root: Path, config: BacklogConfig, guard: _Guard = _Guard()) -> TaskCreator:
    """A board writer that makes a task file with the next id, `<id> - <title as a slug>.md`, in one write.

    It starts in the first lane; any detail beyond the ones the page fills (a `status`, `type`, `references`,
    `documentation`, `definitionOfDone`, `plan`, `notes` or other field `edit` sets) is set as `edit` sets it, so a
    detail it cannot set refuses the create and nothing is written. A refused create leaves its id to the next one.
    """
    lock = threading.Lock()  # two creates must not both read the same highest id
    spelled = {lane_id(status): status for status in config.statuses}

    def create(title: str, details: Mapping[str, Any], /, actor: str = OPERATOR) -> Written:
        with lock:
            task = _next_id(root, config.prefix)
            slug = re.sub(r"[^\w-]+", "-", title).strip("-")[:60].strip("-") or "Task"
            path = root / "tasks" / f"{task} - {slug}.md"
            frontmatter, body = _split(_new_task(task, title, config.statuses[0], details))
            rest = {field: value for field, value in details.items() if field not in _NEW_TASK_DETAILS}
            try:
                body = _apply(task, frontmatter, body, rest, spelled)
                if refused := _land(path, None, _stamped(frontmatter, created=True), body, guard, actor):
                    return refused
            except ValueError as refusal:
                return Written(False, f"{title}: {refusal}")
            except OSError as error:
                return Written(False, f"{path}: {error}")
        return Written(True, task)

    return create


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The native board at `settings["path"]` (default `.starpulse/board`), created empty when absent, as the project named for `base`'s directory, polled every `interval` seconds.

    Moves, assignee changes, creates, edits and archives write the task files directly, and `read` returns a task's record from its file. Any lane reaches any other unless `machine` names a
    machine file, whose transitions and `writers` then decide which moves are offered, and to whom.
    """
    if unknown := sorted(settings.keys() - _SETTINGS):
        raise ValueError(f"board: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_SETTINGS))}")
    root = base / str(settings.get("path", DEFAULT_PATH))
    _create(root, base.resolve().name)
    evaluate = criteria.evaluator(settings.get("criteria"), base)
    guard = _Guard(rules.load(settings.get("rules")), _hook(settings.get("validate")), _state_of(root))

    def assign(task: str, assignee: str, /, actor: str = OPERATOR) -> Written:
        def edit(frontmatter: dict, body: str) -> str:
            frontmatter["assignee"] = [assignee]
            return body

        return _update(root, task, edit, guard, actor)

    return project_board(
        root,
        settings,
        base,
        lambda config: {
            "writer": _writer(root, config.statuses, guard),
            "assign": assign,
            "create": _creator(root, config, guard),
            "read": _reader(root, evaluate.latest if isinstance(evaluate, criteria.Evaluator) else evaluate),
            "evaluate": evaluate,
            "edit": _editor(root, config.statuses, guard),
            "archive": _archiver(root, guard),
            "restore": _restorer(root),
            "complete": _completer(root),
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
    )
