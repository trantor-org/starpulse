"""StarPulse's own board: one Markdown file per task under `.starpulse/board/`, written in Python.

The files use the front matter Backlog.md's tasks use, and `starpulse.board.adapters.native_scan` reads them: the lanes are the
`statuses` of `config.yml` and a task is a file under `tasks/`. This adapter adds the writer that edits the files, and
creates the board, empty, when its directory is absent. It is the default `[board]` adapter.
"""

import fcntl
import hashlib
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
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

import yaml
from sqlalchemy import and_, delete, func, insert, or_, select
from sqlalchemy.engine import Engine

from starpulse.board.adapters import item_uuid, native_doc_import, native_docs, native_milestones, qa_verdicts, ref_uuids
from starpulse.board.adapters.native_doc_index import DocIndex, index_of
from starpulse.board.adapters.holder_idle import GRACE_EXIT, UNREACHABLE_EXIT, HolderInGrace, HolderUnreachable
from starpulse.board.adapters.native_scan import (
    _CRITERIA,
    _HEADED_DESCRIPTION,
    _ITEM,
    _NOTES,
    DEFAULT_PREFIX,
    DEFAULT_STATUSES,
    BacklogConfig,
    _description,
    _split,
    _strings,
    canonical_key,
    lane_id,
    project_board,
)
from starpulse.board.adapters.native_scan import (
    _profile as _profile_of,
)
from starpulse.board.adapters.task_history import TaskHistory, appended, revises_plan
from starpulse.board.adapters.task_view import TaskView
from starpulse.board.model import criteria, entry, rules, write_steps
from starpulse.board.model.claims import assignee_of
from starpulse.board.model.guard import Guard, Validate
from starpulse.board.model.markdown import ARCHIVE_REQUEST
from starpulse.board.model.policy import Policy, guards_of, profile_matrix
from starpulse.board.model.rollup import checks_verdict
from starpulse.board.model.seam import (
    FLAGGED,
    HELD,
    MERGE_EVIDENCE,
    OPERATOR,
    TASK_ACTOR,
    Board,
    MoveWriter,
    RetiredReader,
    TaskArchiver,
    TaskCompleter,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskReopener,
    TaskRestorer,
    TaskRetirer,
    Written,
)
from starpulse.contracts.doc_links import doc_link
from starpulse.contracts.tiers import TIERS, implied_tier
from starpulse.event_log.lane_events import ARCHIVED, COMPLETED
from starpulse.event_log.readmodel.fold import Row
from starpulse.event_log.store import StaleVersion
from starpulse.event_log.tables import pull_requests, retired_tasks, task_links
from starpulse.github.adapters.outbound.rest import connect, get, pull_mergeable
from starpulse.machine_engine.model.state_roles import StateRoles
lazy from starpulse.machine_engine.adapters.machine_loader import read_document

if TYPE_CHECKING:
    from starpulse.board.model.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog

#: Where the board lives, relative to the config's directory (or the working directory without a config).
DEFAULT_PATH = ".starpulse/board"
#: The `[board]` settings this adapter reads: `path` is the board's directory, `machine` a machine file for the Board,
#: relative to the config, `criteria` a retired setting that is read and ignored,
#: `validate` the `module:function` that may refuse a task write before it lands, `python_path` the directories, relative
#: to the config, put at the front of `sys.path` before `validate` is imported, `types` the names a task's `type` may take (any when absent),
#: `policy` the `[board.policy]` table `starpulse policy revision` reads, `transcripts` the directory of the sessions' transcripts, `complete_done` (boolean) that a task
#: landing in Done, and each Done task the board holds when it starts, is archived (the board keeps it readable), `complete_keep_labels` (a regex) that a Done task with a label fully matching it stays on the board, `policy_rows` the stored policy
#: (its guards, profiles and watches) that `assemble` hands the board; no config sets it. `cohort_milestone` (boolean) that a
#: create of a batch of two or more tasks refuses a spec with no `milestone`. `entered` is the command run
#: (`{id}` the task's id) for each lane change `board:lanes` records, and `entered_labels` (a regex) limits it to a task
#: with a label fully matching it.
_SETTINGS = {
    "entered",
    "entered_labels",
    "type",
    "path",
    "interval",  # retired: a config that still sets it loads, the setting does nothing
    "machine",
    "criteria",  # retired: a config that still sets it loads, the setting does nothing
    "claim_ttl",  # retired: a config that still sets it loads, the setting does nothing
    "verifying",  # retired: a config that still sets it loads, the setting does nothing
    "task_file_name",  # retired: a config that still sets it loads, the setting does nothing
    "holds",
    "holds_labels",
    "unfinished",
    "unpublished",
    "parked",
    "released",
    "idle",
    "returned",
    "alive",
    "enqueued",
    "closed",
    "archived",
    "frozen",
    "halted",
    "faulted",
    "validate",
    "python_path",
    "types",
    "entry",
    "warn_actors",
    "policy",
    "transcripts",
    "complete_done",
    "complete_keep_labels",
    "policy_rows",
    "cohort_milestone",
}
#: How many retired rows a scan reads at a time, so no more than a page of their text is in memory at once.
_RETIRED_PAGE = 200
#: The stamps' format, read as UTC.
_STAMP = "%Y-%m-%d %H:%M"
_NOTES_END = re.compile(r"\s*<!-- SECTION:NOTES:END -->")
_PLAN = re.compile(r"<!-- SECTION:PLAN:BEGIN -->(.*?)<!-- SECTION:PLAN:END -->", re.S)
_DONE = re.compile(r"<!-- DOD:BEGIN -->(.*?)<!-- DOD:END -->", re.S)
_FINAL_SUMMARY = re.compile(r"<!-- SECTION:FINAL_SUMMARY:BEGIN -->(.*?)<!-- SECTION:FINAL_SUMMARY:END -->", re.S)
_NEEDS_ATTENTION = re.compile(r"<!-- SECTION:NEEDS_ATTENTION:BEGIN -->(.*?)<!-- SECTION:NEEDS_ATTENTION:END -->", re.S)
_COMMENTS_BEGIN = "<!-- COMMENTS:BEGIN -->"
_COMMENTS_END = "<!-- COMMENTS:END -->"
_COMMENTS_SECTION = re.compile(f"{_COMMENTS_BEGIN}(.*?){_COMMENTS_END}", re.S)
_COMMENT_HEAD = re.compile(r"created: (\S+ \S+)\n(?:author: (\S+)\n)?---\n")
_SESSION_LINK = re.compile(r"\*\*Session Link:\*\* (?:local \w+ session `([^`]+)`|(\S+))")
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


#: GitHub lists a pull request's files `_FILES_PAGE` to a page and stops at 3000.
_FILES_PAGE, _FILES_PAGES = 100, 30


def _github_mergeable(repo: str, number: int) -> str | None:
    return pull_mergeable(repo, number, HOOK_TIMEOUT)


def _github_files(repo: str, number: int) -> list[str] | None:
    """The paths pull request `number` changes, None when GitHub is unreadable or its listing is cut at its cap."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    transport = connect(token, HOOK_TIMEOUT, caller="native")
    paths: list[str] = []
    try:
        for page in range(1, _FILES_PAGES + 1):
            items = get(transport, f"/repos/{repo}/pulls/{number}/files?per_page={_FILES_PAGE}&page={page}").get(
                "items", []
            )
            paths += [item["filename"] for item in items]
            if len(items) < _FILES_PAGE:
                return paths
    except OSError:
        pass
    return None


def _pull_of(retired: _Retired) -> Callable[[str, int, str | None], dict[str, Any] | None]:
    """A lookup of the stored pull request `(repository, number)` as `{state, draft, checks, threads, mergeable, body, files}`,
    None when the store holds none; `files` is None for a record saved before the store kept them. A board that has not started has no store.
    With `settle="mergeable"`, an open pull request whose stored `mergeable` is not `MERGEABLE` reads GitHub's answer instead: GitHub sends no
    event when a push clears a conflict, so the stored flag can outlive it. With `settle="files"`, a pull request whose `files` is None
    reads GitHub's listing instead: the pulls consumer can lag the pull request's first delivery. An unreadable GitHub leaves the stored value."""

    def read(repo: str, number: int, settle: str | None) -> dict[str, Any] | None:
        if retired.engine is None:
            return None
        columns = (
            pull_requests.c.state,
            pull_requests.c.is_draft,
            pull_requests.c.checks,
            pull_requests.c.head,
            pull_requests.c.rollup,
            pull_requests.c.required,
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
        mergeable = row.mergeable
        if settle == "mergeable" and row.state == "OPEN" and mergeable != "MERGEABLE":
            mergeable = _github_mergeable(repo, number) or mergeable
        files = (row.detail or {}).get("files")
        if settle == "files" and files is None:
            files = _github_files(repo, number)
        return {
            "number": number,
            "state": row.state,
            "draft": row.is_draft,
            "checks": checks_verdict(row.state, row.checks, row.head, row.rollup, row.required),
            "threads": row.threads,
            "mergeable": mergeable,
            "body": row.body,
            "files": files,
        }

    return read


_CHANGE = re.compile(r"change:[^:]+:([^:]+/[^:]+):(\d+)")


def _linked(retired: _Retired) -> Callable[[str], list[tuple[str, str, int]]]:
    """A lookup of the pull requests the task of a UUID links, oldest first, as `(role, repository, number)`; a board that has not
    started has no store, so one it cannot read (repository `""`)."""

    def read(uuid: str) -> list[tuple[str, str, int]]:
        if not uuid:
            return []
        if (
            retired.engine is None
        ):  # no store to read: not that none is linked, so one unreadable pull request holds ready back
            return [("delivers", "", 0)]
        with retired.engine.connect() as db:
            rows = db.execute(
                select(task_links.c.role, task_links.c.ref)
                .where(task_links.c.task == uuid, task_links.c.role.in_(("delivers", "cites")))
                .order_by(task_links.c.at)
            ).all()
        return [(role, found[1], int(found[2])) for role, ref in rows if (found := _CHANGE.fullmatch(ref))]

    return read


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


def _warn_actors(settings: Mapping[str, Any]) -> frozenset[str]:
    """The actors the `warn_actors` setting declares, empty when it declares none."""
    declared = settings.get("warn_actors", ())
    if not isinstance(declared, (list, tuple)) or not all(isinstance(name, str) and name.strip() for name in declared):
        raise ValueError("board: warn_actors must be a list of actors (`operator`, `agent`, `<instance>/<workflow>`)")
    return frozenset(name.strip() for name in declared)


class _Shelf(NamedTuple):
    """Where a board holds its tasks: their Histories, as `view` replays them. A task's file text is drawn from its row when
    a write is judged and is written nowhere."""

    root: Path
    view: TaskView
    spelled: Mapping[str, str]
    done: str | None

    def row(self, task: str) -> Row | None:
        """The row of `task` a verb may write: a task on the board or archived Done; an archived task not Done is off it."""
        row = self.view.row(task)
        return None if row is None or (row["archived"] and lane_id(str(row["state"])) != self.done) else row

    def text(self, row: Row) -> str:
        front, body = _file_of(_record_from(row, self.spelled))
        return f"---\n{yaml.safe_dump(front, sort_keys=False, allow_unicode=True)}---{body}"

    def uuid_of(self, key: str) -> str:
        return "" if (row := self.view.row(key)) is None else _said(row["meta"], "uuid")

    def names(self, task: str) -> set[str]:
        """`task` and, when it is on the board, its `id` and `aliases`, casefolded: every spelling a dependency may use."""
        names = {task.casefold()}
        if (row := self.view.row(task)) is not None:
            names |= {name.casefold() for name in (str(row["id"]), *(row["meta"].get("aliases") or [])) if name}
        return names

    def dependents(self, wanted: set[str]) -> list[str]:
        """Ids of the open tasks (unarchived, not Done) that list any of `wanted` as a dependency, in id order."""
        return [
            item["id"]
            for item in self.view.open(self.done)
            if wanted & {dependency.casefold() for dependency in item["dependencies"] or []}
        ]

    def holders(self, field: str, value: str) -> list[str]:
        """The ids of the open tasks whose front matter `field` holds `value`."""
        found = []
        for item in self.view.open(self.done):
            if field in item:
                held = item[field]
            elif (row := self.view.row(item["id"])) is not None:
                held = _file_of(_record_from(row, self.spelled))[0].get(field)
            else:
                continue
            if value in _strings(held):
                found.append(item["id"])
        return found


def _stamped(shelf: _Shelf, frontmatter: dict, *, created: bool = False) -> dict:
    """`frontmatter` with `updated_date` (and `created_date` on a new task) set to now in UTC, after the profile or status,
    and the UUID of each item it names in `uuids`."""
    ref_uuids.stamp(shelf.root, frontmatter, shelf.uuid_of)
    now = f"{datetime.now(timezone.utc):{_STAMP}}"
    stamps = {key: now for key in ("created_date", "updated_date") if created or key == "updated_date"}
    anchor = next((key for key in ("profile", "assignee") if key in frontmatter), "status")
    stamped: dict[str, Any] = {}
    for key, value in frontmatter.items():
        stamped[key] = stamps.get(key, value)
        if key == anchor:
            stamped |= {stamp: now for stamp in stamps if stamp not in frontmatter}
    return stamped


def _aliases(frontmatter: Mapping[str, Any]) -> list[str]:
    """The ids a task answers to besides its own `id`, as its `aliases` front matter lists them."""
    aliases = frontmatter.get("aliases")
    return [str(alias).strip() for alias in aliases] if isinstance(aliases, list) else []


def _split_record(text: str) -> tuple[dict, str]:
    frontmatter, body = _split(text)
    return (frontmatter if isinstance(frontmatter, dict) else {}), body


#: Returned by `_land` when the task's History moved after the write was made over it.
_STALE = Written(False, "the task's History changed while it was being written")
#: How many times `_update` redoes an edit on a task that changed under it before it gives up.
_ATTEMPTS = 5
#: Returned by `_update` when the task is not the one a write was judged over (`over`): no refusal, so it is judged again.
_CHANGED = Written(False, "the task changed after it was judged", transient=True)


def _land(
    shelf: _Shelf,
    task: str,
    before: str | None,
    head: int,
    frontmatter: dict,
    body: str,
    guard: Guard,
    actor: str,
    *,
    audit: bool = False,
) -> Written:
    """Append `task`'s write to its History at `head`, the one `before` (None: a new task) was drawn at, unless `guard` refuses `actor`'s
    write or the History moved: the refusal (`_STALE` for a moved History), or once it landed an ok `Written` naming the lane rules it
    broke. The lane the write enters runs its entry effects first, whoever writes. An `audit` appends nothing: it is
    the verdict of the rules on the write."""
    members = frontmatter.pop("members", None)
    earlier = None if before is None else rules.Record(*_split_record(before))
    frontmatter = dict(guard.entered(frontmatter, None if earlier is None else earlier.front))
    text = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)}---{body}"
    judged = guard.verdict(
        shelf.root / "tasks" / f"{task}.md", before, earlier, frontmatter, body, text, actor, audit=audit
    )
    write_steps.step("guard")
    if audit or not judged.ok:
        return judged
    try:
        _commit(
            task,
            text,
            actor,
            before,
            members,
            head,
            lane_id(str(frontmatter.get("status") or "")) not in {shelf.done, COMPLETED},
        )
    except StaleVersion:
        return _STALE
    write_steps.step("land")
    return judged


def _commit(
    task: str, text: str, actor: str, before: str | None, members: dict | None, head: int, rehydrates: bool
) -> None:
    """Append to the History of the task `text` replaces `before` with, at `head`, the Events that write is: what it
    changed in the task, so a field the History holds beyond its rendering is never overwritten. A completed task
    written into a lane other than Done leaves the archive (`rehydrates`)."""
    record = _record_of(text)
    if members is not None:
        record["members"] = members
    appended(
        str(record["id"] or task),
        record,
        actor,
        created=before is None,
        before=None if before is None else _record_of(before),
        rehydrates=rehydrates,
        head=head,
    )


def _update(
    shelf: _Shelf,
    task: str,
    edit: Callable[[dict, str], str],
    guard: Guard = Guard(),
    actor: str = OPERATOR,
    *,
    audit: bool = False,
    over: str = "",
) -> Written:
    """Append to the History of `task` its front matter edited in place and its body as `edit` returns it, as `actor`;
    an `audit` only judges that write (`_land`) and names the task as it stood as `version`. With `over`, a task that is
    not the one an audit named is `_CHANGED`.

    A task whose History moved between the read and the append is read and edited again, so another writer's change is
    kept; after `_ATTEMPTS` such races the edit is refused."""
    for _ in range(_ATTEMPTS):
        if (row := shelf.row(task)) is None:
            return Written(False, f"{task} is not on the board")
        before = shelf.text(row)
        version = hashlib.sha256(before.encode()).hexdigest()
        if over and version != over:
            return _CHANGED
        frontmatter, body = _split(before)
        body = edit(frontmatter, body)
        landed = _land(
            shelf, str(row["id"]), before, row["version"], _stamped(shelf, frontmatter), body, guard, actor, audit=audit
        )
        if landed.ok:
            return Written(True, f"Updated task {task}", warnings=landed.warnings, version=version if audit else "")
        if landed is not _STALE:
            return landed
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


# `^` under `re.M` and a lazy `.*?` each cost tens of milliseconds over a megabyte of comments; a literal-prefixed pattern
# filtered to line starts is linear and fast.
def _line_starts(pattern: re.Pattern[str], text: str) -> Iterator[re.Match[str]]:
    return (m for m in pattern.finditer(text) if m.start() == 0 or text[m.start() - 1] == "\n")


def _comments(body: str) -> list[dict[str, str]]:
    """The task's comments as `{created, text}`, oldest first, as `_comment` and the Backlog this workspace runs write them."""
    begin = body.find(_COMMENTS_BEGIN)
    end = body.find(_COMMENTS_END, begin + len(_COMMENTS_BEGIN)) if begin >= 0 else -1
    region = body[begin + len(_COMMENTS_BEGIN) : end] if end >= 0 else ""
    heads = list(_line_starts(_COMMENT_HEAD, region))
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
    links = [m[1] or m[2] for text in texts for m in _line_starts(_SESSION_LINK, text)]
    return links[-1] if links else ""


def _live_criteria(record: dict[str, Any], lane: str, done: str | None, waiting: str | None) -> list[dict[str, Any]]:
    """The record's Start Criteria still in force in `lane`: none once Done, and no event wait outside Waiting."""
    if lane == done:
        return []
    if waiting is None or lane == waiting:
        return record["start_criteria"]
    return [each for each in record["start_criteria"] if each["kind"] != criteria.EVENT]


def _record_of(text: str) -> dict[str, Any]:
    """The record of the task file `text`, keyed by the fields the task view draws and edits."""
    frontmatter, body = _split(text)
    description = _description(body)
    notes, comments = _section(_NOTES, body), _comments(body)
    return {
        "id": str(frontmatter.get("id") or ""),
        "uuid": str(frontmatter.get("uuid") or ""),
        "uuids": dict(frontmatter.get("uuids") or {}),
        "title": str(frontmatter.get("title") or ""),
        "type": str(frontmatter.get("type") or ""),
        "status": str(frontmatter.get("status") or ""),
        "profile": _profile_of(frontmatter),
        "priority": str(frontmatter.get("priority") or ""),
        "impact": str(frontmatter.get("impact") or ""),
        "urgency": str(frontmatter.get("urgency") or ""),
        "tier": str(frontmatter.get("tier") or ""),
        "labels": list(_strings(frontmatter.get("labels"))),
        "milestone": str(frontmatter.get("milestone") or ""),
        "source": str(frontmatter.get("source") or ""),
        "follows": str(frontmatter.get("follows") or ""),
        "adrNeeded": str(frontmatter.get("adr_needed") or ""),
        "duplicateSearch": str(frontmatter.get("duplicate_search") or ""),
        "duplicateResolution": str(frontmatter.get("duplicate_resolution") or ""),
        "dependencies": list(_strings(frontmatter.get("dependencies"))),
        "dependencyNeeds": list(_strings(frontmatter.get("dependency_needs"))),
        "actorMemory": dict(frontmatter.get("actor_memory") or {}),
        "frozen": dict(frontmatter.get("frozen") or {}),
        "references": list(_strings(frontmatter.get("references"))),
        "documentation": list(_strings(frontmatter.get("documentation"))),
        "modifiedFiles": list(_strings(frontmatter.get("modified_files"))),
        "description": description,
        "start_criteria": criteria.authored(description),
        "plan": _section(_PLAN, body),
        "notes": notes,
        "finalSummary": _section(_FINAL_SUMMARY, body),
        "needsAttention": _section(_NEEDS_ATTENTION, body),
        "comments": comments,
        "assignee": assignee_of(frontmatter),
        "session": assignee_of(frontmatter) or _session(notes, comments),
        "createdBy": str(frontmatter.get("created_by") or ""),
        "aliases": _aliases(frontmatter),
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
}
#: The lists whose key a task file leaves out while it holds nothing.
_OPTIONAL_LISTS = {"references", "documentation", "modified_files", "dependency_needs"}
_COMMENTS = re.compile(r"[ \t]*<!-- COMMENTS:END -->")


def _text(field: str, value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    return value.strip()


def _texts(field: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of text")
    return value


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
    return _appended_comments(body, [(text, actor)])


def _appended_comments(body: str, written: Sequence[tuple[str, str]]) -> str:
    """`body` with each `(text, actor)` appended to its comments in order, the body searched once for all of them."""
    stamp = f"{datetime.now():%Y-%m-%d %H:%M}"
    entry = "".join(f"created: {stamp}\nauthor: {actor}\n---\n{text.strip()}\n---\n\n" for text, actor in written)
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
        frontmatter["status"] = spelled[lane_id(_text(field, value))]
    elif field == "actorMemory":
        if not isinstance(value, dict):
            raise ValueError(f"{field} must be a mapping")
        frontmatter["actor_memory"] = value
        if not value:
            del frontmatter["actor_memory"]
    elif field == "members":
        if not isinstance(value, dict):
            raise ValueError(f"{field} must be a mapping")
        frontmatter["members"] = value  # `_land` lifts it out of the file: only the History keeps it
    elif field == "frozen":
        if not isinstance(value, dict):
            raise ValueError(f"{field} must be a mapping")
        frozen = {key: str(value.get(key) or "") for key in ("by", "at", "reason")} if value else {}
        frontmatter["frozen"] = frozen
        if not frozen:
            del frontmatter["frozen"]
    elif field in _LISTS:
        _texts(field, value)
        key = _LISTS[field]
        items = [item.strip() for item in value if item.strip()]
        frontmatter[key] = list(dict.fromkeys(items)) if key == "references" else items  # a task cites a reference once
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


def _said(meta: Mapping[str, Any], key: str) -> str:
    return str(meta.get(key) or "")


def _record_from(row: Mapping[str, Any], spelled: Mapping[str, str]) -> dict[str, Any]:
    """The record `_record_of` draws from a task's file, drawn from its History's replayed `row`: a status is spelled as the
    board spells it, and a comment as the Backlog this workspace runs stamps it."""
    meta = row["meta"]
    comments = [
        {
            "created": item.get("created")
            or (f"{datetime.fromtimestamp(item['at']):%Y-%m-%d %H:%M}" if item["at"] else ""),
            "text": item["text"],
            **({"author": item["actor"]} if item.get("actor") else {}),
        }
        for item in row["comments"]
    ]
    items = {
        kind: [{key: item[key] for key in ("n", "text", "checked")} for item in row["criteria"] if item["kind"] == kind]
        for kind in ("ac", "dod")
    }
    description = row["description"]
    return {
        "id": row["id"],
        "title": row["title"],
        "type": row["type"],
        "status": spelled.get(lane_id(row["state"]), row["state"]),
        "profile": _said(meta, "profile"),
        "priority": row["priority"],
        "impact": _said(meta, "impact"),
        "urgency": _said(meta, "urgency"),
        "tier": _said(meta, "tier"),
        "labels": list(row["labels"]),
        "milestone": row["milestone"],
        "source": _said(meta, "source"),
        "follows": _said(meta, "follows"),
        "adrNeeded": _said(meta, "adrNeeded"),
        "duplicateSearch": _said(meta, "duplicateSearch"),
        "duplicateResolution": _said(meta, "duplicateResolution"),
        "dependencies": list(row["dependencies"]),
        "dependencyNeeds": list(meta.get("dependencyNeeds") or []),
        "actorMemory": dict(meta.get("actorMemory") or {}),
        "members": dict(meta.get("members") or {}),
        "frozen": dict(meta.get("frozen") or {}),
        "references": list(row["references"]),
        "documentation": list(row["documentation"]),
        "modifiedFiles": list(row["modified_files"]),
        "description": description,
        "start_criteria": criteria.authored(description),
        "plan": row["plan"],
        "notes": row["notes"],
        "finalSummary": row["final_summary"],
        "needsAttention": _said(meta, "needsAttention"),
        "comments": comments,
        "assignee": row["assignee"],
        "session": row["assignee"] or _session(row["notes"], comments),
        "createdBy": _said(meta, "createdBy"),
        "aliases": list(meta.get("aliases") or []),
        "uuid": _said(meta, "uuid"),
        "uuids": dict(meta.get("uuids") or {}),
        "acceptanceCriteria": items["ac"],
        "definitionOfDone": items["dod"],
    }


def _file_of(record: Mapping[str, Any]) -> tuple[dict, str]:
    """The front matter and body a task file would hold for `record`, as the board rules read a file."""
    frontmatter: dict[str, Any] = {"id": record["id"]}
    if record.get("uuid"):
        frontmatter["uuid"] = record["uuid"]
    if record.get("uuids"):
        frontmatter["uuids"] = record["uuids"]
    spelled = {lane_id(record["status"]): record["status"]}
    for field in (*_SCALARS, "profile", "status", "actorMemory", "frozen", *_LISTS):
        if record.get(field):
            _set_front(frontmatter, field, record[field], spelled)
    frontmatter |= {
        key: record[field] for key, field in (("created_by", "createdBy"), ("aliases", "aliases")) if record.get(field)
    }
    body = ""
    for field in _TEXT_SECTIONS:
        if record.get(field):
            body = _set_text(body, field, record[field])
    for field, (marker, heading, _) in _CHECKLISTS.items():
        if record.get(field):
            lines = "".join(
                f"- [{'x' if item['checked'] else ' '}] #{item['n']} {item['text']}\n" for item in record[field]
            )
            body = _marked(body, marker, heading, "\n" + lines)
    if record["comments"]:
        body = _appended_comments(body, [(item["text"], item.get("author") or OPERATOR) for item in record["comments"]])
    return frontmatter, body


_DOC_ID = re.compile(r"doc-\d+")
_Linker = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _unlinked(changes: Mapping[str, Any]) -> Mapping[str, Any]:
    return changes


def _doc_linker(index: DocIndex, base: Path) -> _Linker:
    """`changes` with each doc id in its `documentation` list read as that open doc's file, keeping one link per file; an
    id no open doc has, or an entry that is a JSON object or array (a command's reply), raises ValueError.

    The file is named from the repository the board sits in (the nearest folder above it holding `.git`), as a task's
    other links are, else from `base`.
    """
    read = native_docs.reader(index.root, index)
    root = index.root

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
            if _DOC_ID.fullmatch(doc := doc_link(item)):
                if (record := read(doc)) is None:
                    raise ValueError(f"{doc} is not an open doc")
                item = (prefix() / "docs" / record["path"]).as_posix()
            paths.append(item)
        return {**changes, "documentation": list(dict.fromkeys(paths))}

    return link


def _unstarted(roles: StateRoles) -> frozenset[str]:
    """The lanes where work has not begun: where a task starts, is ready or waits on dependencies."""
    return frozenset(lane for lane in (roles.initial, roles.ready, roles.waiting) if lane)


def _editor(
    shelf: _Shelf,
    guard: Guard = Guard(),
    link: _Linker = _unlinked,
    attention: str | None = None,
    unstarted: frozenset[str] = frozenset(),
    audit: bool = False,
) -> TaskEditor:
    """A board writer that applies every change to a task in one History append, or refuses the whole edit. With `audit` it
    writes nothing and answers, for the task actor, what the board's rules say of the edit (`Board.judge`).

    `changes` holds the new value of each field `read` names except `comments`, which `comment` appends to: one text, or a
    list appended in order, each blank one skipped; `appendNotes` is one more, text added to the end of the notes. An
    empty priority, milestone, profile or type and an empty references, documentation or modified-files list removes its
    key, a status is spelled as its lane is, a checklist item without a number is new, and `link` reads a doc id in the
    documentation list as its file. A move to the `attention` lane with comment text also writes that text as the task's
    `## Needs attention` section, the reason the lane's guard reads. `planReason` is no field: a plan rewritten on a task
    outside the `unstarted` lanes needs one, and the History records it. A completed task edited into a lane other than `done`
    leaves the archive.
    """
    spelled = shelf.spelled

    def edit(
        task: str, changes: Mapping[str, Any], comment: str | Sequence[str], /, actor: str = OPERATOR, over: str = ""
    ) -> Written:
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
            gated = {item["id"] for item in criteria.authored(_description(body))}
            held = lane_id(str(frontmatter.get("status") or "")) == guard.waiting and lane_id(status) in {
                "",
                guard.waiting,
            }
            body = _apply(task, frontmatter, body, link(changes), spelled)
            # An edit may re-gate a Waiting task onto other subjects or onto tasks, never leave it with no gate.
            ungated = not criteria.authored(_description(body)) and not _strings(frontmatter.get("dependencies"))
            if held and "description" in changes and gated and ungated:
                raise ValueError(f"a Waiting task keeps its Start Criteria; the edit drops {', '.join(sorted(gated))}")
            for text in texts:
                recorded = _recorded(text, _comments(body))
                body = _comment(body, text, actor) if text.strip() and not recorded else body
            return body

        # A comment changes no field a rule or the validate hook judges, and the comment that names a refusal must land;
        # an archive request is judged, as the archive it asks for is.
        asked = any(text.strip().startswith(ARCHIVE_REQUEST) for text in texts)
        judged = guard if changes or asked else replace(guard, rules=(), validate=None)
        if audit:
            judged, actor = replace(judged, validate=None, types=()), TASK_ACTOR
        try:
            written = _update(shelf, task, apply, judged, actor, audit=audit, over=over)
        except ValueError as refusal:  # raised before the History is appended to, so a refusal writes nothing
            return Written(False, f"{task}: {refusal}")
        if audit:
            return written
        return _moved(written, spelled.get(lane_id(status), status)) if status else written

    return edit


def _unlinker(
    task: str, names: set[str], reason: str, ready: str | None, waiting: str | None, actor: str
) -> Callable[[dict, str], str]:
    """An edit that drops `task` from a task's dependencies and says why; a Waiting task left with no dependency and
    no Start Criteria moves to `ready`, since the release pass reads only Waiting tasks that still have one."""
    note = f"Removed dependency on {task}: archived" + (f" ({reason.strip()})" if reason.strip() else "")

    def edit(frontmatter: dict, body: str) -> str:
        kept = [name for name in _strings(frontmatter.get("dependencies")) if name.casefold() not in names]
        frontmatter["dependencies"] = kept
        if needs := [
            need
            for need in _strings(frontmatter.get("dependency_needs"))
            if need.partition("#")[0].casefold() not in names
        ]:
            frontmatter["dependency_needs"] = needs
        else:
            frontmatter.pop("dependency_needs", None)
        held = lane_id(str(frontmatter.get("status") or "")) == waiting
        if held and not kept and ready is not None and not frontmatter.get("frozen") and not criteria.authored(body):
            frontmatter["status"] = ready
            return _comment(body, f"{note}; no dependency is left, so it moved to {ready}.", actor)
        return _comment(body, note, actor)

    return edit


def _archiver(shelf: _Shelf, roles: StateRoles, guard: Guard = Guard()) -> TaskArchiver:
    """A board writer that archives a task's History, from any lane, after recording a non-blank reason as a comment.

    An archived task never reaches Done, so each open task that depends on it has that dependency removed first, with
    a comment saying why; a Waiting one left with no dependency is released to Ready."""
    ready = shelf.spelled.get(roles.ready or "")

    def archive(task: str, reason: str, /, actor: str = OPERATOR) -> Written:
        if (row := shelf.row(task)) is None:
            return Written(False, f"{task} is not on the board")
        if row["archived"]:
            return Written(False, f"{task} is already archived")
        front = _split(shelf.text(row))[0]
        if refusal := guard.frozen_refusal(rules.Record(front, ""), front | {"status": ARCHIVED}, actor):
            return Written(False, refusal)
        if (
            reason.strip()
            and not (
                noted := _update(
                    shelf, task, lambda _, body: _comment(body, f"Archived: {reason.strip()}", actor), guard, actor
                )
            ).ok
        ):
            return noted
        names = shelf.names(task)
        dependents = shelf.dependents(names)
        moves = []
        for dependent in dependents:
            unlink = _unlinker(task, names, reason, ready, roles.waiting, actor)
            released = False

            def edit(frontmatter: dict, body: str) -> str:
                nonlocal released
                before = frontmatter.get("status")
                body = unlink(frontmatter, body)
                released = frontmatter.get("status") != before
                return body

            if not (unlinked := _update(shelf, dependent, edit, guard, actor)).ok:
                return unlinked
            if released and ready is not None:
                moves.append((dependent, ready))
        held = shelf.view.row(task)
        appended(str(row["id"]), None, actor, head=None if held is None else held["version"])
        unlinked = f"; removed it from the dependencies of {', '.join(dependents)}" if dependents else ""
        return _moved(Written(True, f"Archived task {task}{unlinked}"), ARCHIVED)._replace(moves=tuple(moves))

    return archive


class _Retired:
    """The board's retired tasks, rows of the history store's `starpulse_retired_tasks`, once `start` binds the store.

    A board that has not started has no store: it reads no retired task and refuses to keep one. A task is matched by
    its id in any case, as `_find` matches a file."""

    def __init__(self) -> None:
        self.engine: Engine | None = None
        self._highest: dict[str, tuple[tuple[int, float | None], int]] = {}

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
                query = query.where(retired_tasks.c.task.in_({task, task.upper(), task.lower()}))
            if milestone:
                query = query.where(retired_tasks.c.milestone == milestone)
            with self.engine.connect() as db:
                page = [dict(row._mapping) for row in db.execute(query)]
            yield from page
            if len(page) < _RETIRED_PAGE:
                return
            after = page[-1]["task"]

    def page(self, limit: int, before: str) -> tuple[list[dict[str, str]], str | None]:
        """The `limit` retired tasks after the cursor `before` ("" for the first page), newest retired first, as
        `[{task, name, text}]`, and the cursor of the page that follows, None on the last. A cursor is the last row's
        `retired_at` and id, `<retired_at>|<task>`; one that is not raises `ValueError`."""
        if self.engine is None:
            return [], None
        columns = (retired_tasks.c.task, retired_tasks.c.name, retired_tasks.c.text, retired_tasks.c.retired_at)
        query = (
            select(*columns).order_by(retired_tasks.c.retired_at.desc(), retired_tasks.c.task.desc()).limit(limit + 1)
        )
        if before:
            at, _, task = before.partition("|")
            older = float(at)
            query = query.where(
                or_(
                    retired_tasks.c.retired_at < older,
                    and_(retired_tasks.c.retired_at == older, retired_tasks.c.task < task),
                )
            )
        with self.engine.connect() as db:
            found = db.execute(query).all()
        last = found[limit - 1] if len(found) > limit else None
        rows = [{"task": row.task, "name": row.name, "text": row.text} for row in found[:limit]]
        return rows, f"{last.retired_at!r}|{last.task}" if last else None

    def text(self, task: str) -> str | None:
        """The retired `task`'s file text, None when it is not retired. The id is looked up as spelled, upper-cased and
        lower-cased, each a primary-key read, so asking for a task that is not retired reads no other row."""
        if self.engine is None:
            return None
        spellings = {task, task.upper(), task.lower()}
        query = select(retired_tasks.c.text).where(retired_tasks.c.task.in_(spellings)).limit(1)
        with self.engine.connect() as db:
            return db.execute(query).scalar()

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

    def version(self) -> tuple[int, float | None]:
        """The rows' count and newest `retired_at`, which a retire, an import or a restore moves."""
        if self.engine is None:
            return (0, None)
        with self.engine.connect() as db:
            return tuple(db.execute(select(func.count(), func.max(retired_tasks.c.retired_at))).one())

    def highest(self, number: re.Pattern[str]) -> int:
        """The highest number `number` matches among the retired ids and their aliases, 0 for none. It is read again only
        once the rows' count or newest `retired_at` moved, as a retire or a restore moves them; reading the aliases
        searches every retired text."""
        if self.engine is None:
            return 0
        now = self.version()
        held = self._highest.get(number.pattern)
        if held is not None and held[0] == now:
            return held[1]
        newer = self._newer(held[0][1]) if held is not None and held[0][1] is not None else None
        if held is not None and newer is not None and now[0] - held[0][0] == len(newer):
            names = [name for task, text in newer for name in (task, *_aliases(_split_record(text)[0]))]
            highest = held[1]  # the same rows plus these, so no retired id the last read saw is gone from the store
        else:
            names, highest = [*self.ids(), *self.aliases()], 0
        matched = (number.fullmatch(task) for task in names)
        highest = max([highest, *(int(found[1]) for found in matched if found)])
        self._highest[number.pattern] = (now, highest)
        return highest

    def _newer(self, after: float) -> list[tuple[str, str]]:
        """The `(task, text)` of each row retired after `after`, an indexed range read."""
        if self.engine is None:
            return []
        query = select(retired_tasks.c.task, retired_tasks.c.text).where(retired_tasks.c.retired_at > after)
        with self.engine.connect() as db:
            return [(row.task, row.text) for row in db.execute(query)]

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
                select(retired_tasks.c.text).where(retired_tasks.c.task.in_({task, task.upper(), task.lower()}))
            ).scalar()
            if held is None:
                milestone = str(_split_record(text)[0].get("milestone") or "").strip() or None
                db.execute(
                    insert(retired_tasks).values(
                        task=task, name=name, text=text, retired_at=time.time(), milestone=milestone
                    )
                )
        return None if held in (None, text) else f"{task} is already retired with other text"

    def take(self, task: str) -> Written | None:
        """Return the retired `task` to the board, its History rehydrated, and drop its row; None when it is not retired."""
        if not (kept := self.rows(task)):
            return None
        appended(kept[0]["task"], _record_of(kept[0]["text"]), OPERATOR, rehydrates=True)
        assert self.engine is not None  # rows found one
        with self.engine.begin() as db:
            db.execute(delete(retired_tasks).where(retired_tasks.c.task == kept[0]["task"]))
        return Written(True, f"Restored task {task}")


def _retirer(shelf: _Shelf, retired: _Retired, roles: StateRoles, prefix: str) -> TaskRetirer:
    """A board writer that takes a Done or archived task off the board into `retired`, with the text its History renders.

    The task is archived first, so a write meeting the retire finds it off the board; a retire the store refuses leaves it archived."""

    def retire(task: str, /) -> Written:
        if (row := shelf.view.row(task)) is None:
            return Written(False, f"{task} is not on the board")
        status = str(row["state"] or "")
        if not row["archived"] and lane_id(status) != roles.done:
            return Written(False, f"{task} is {status or 'without a status'}, neither Done nor archived")
        key = canonical_key(prefix, str(row["id"]).strip())
        if not row["archived"]:
            appended(key, None, OPERATOR, head=row["version"])
        if refused := retired.keep(key, f"{key}.md", shelf.text(row)):
            return Written(False, refused)
        return Written(True, f"Retired task {task}")

    return retire


def _retired_reader(retired: _Retired) -> RetiredReader:
    def read(task: str, milestone: str, /) -> Iterable[Mapping[str, str]]:
        rows = retired.each(task, milestone)
        return list(rows) if task else rows

    return read


def _restorer(shelf: _Shelf, retired: _Retired, migrations: Mapping[str, str], guard: Guard) -> TaskRestorer:
    """A board writer that returns an archived or retired task to the board, in the State it was archived in.

    When the active definition lacks that State, the task lands in the State its `migrations` entry names, and a State
    with no entry refuses the restore. A task on the board, or archived Done, which the board keeps readable, is refused."""

    def restore(task: str, /) -> Written:
        if retired.rows(task):
            return retired.take(task) or Written(False, f"{task} is not retired")
        if (row := shelf.view.row(task)) is None:
            return Written(False, f"{task} has no History and is not retired")
        held = str(row["state"] or "")
        if not row["archived"] or lane_id(held) == shelf.done:
            return Written(False, f"{task} is already on the board")
        landing = held if lane_id(held) in shelf.spelled else shelf.spelled.get(migrations.get(lane_id(held), ""))
        if landing is None:
            return Written(
                False, f"{task} was archived in {held}, which the active definition lacks and no migrations entry names"
            )
        appended(str(row["id"]), _record_of(shelf.text(row)), OPERATOR, rehydrates=True, head=row["version"])
        if landing == held:
            return Written(True, f"Restored task {task}")

        def land(frontmatter: dict, body: str) -> str:
            frontmatter["status"] = landing
            return body

        return _update(shelf, task, land, guard)

    return restore


def _moved(written: Written, lane: str) -> Written:
    """`written` once it landed, with the `lane` it put the task in and the moment, for the server to record with the
    request's actor; a refused write moved nothing."""
    return written._replace(lane=lane, at=time.time()) if written.ok else written


def _writer(shelf: _Shelf, roles: StateRoles, guard: Guard = Guard()) -> MoveWriter:
    """A board writer that sets a task's status. A lane's status is the board's own spelling of it.
    A move to `archived` is an archive, so `restore` finds it; a move out of Done returns a completed task to the board.
    """
    spelled = shelf.spelled
    archive = _archiver(shelf, roles, guard)

    def write(task: str, status: str, actor: str) -> Written:
        if lane_id(status) == ARCHIVED:
            return archive(task, "", actor)

        def edit(frontmatter: dict, body: str) -> str:
            frontmatter["status"] = spelled.get(lane_id(status), status)
            return body

        return _moved(_update(shelf, task, edit, guard, actor), spelled.get(lane_id(status), status))

    return write


class _Unheld(Exception):
    """The task file no longer holds the State a write judged."""


def _reopener(shelf: _Shelf, roles: StateRoles, guard: Guard = Guard()) -> TaskReopener:
    """A board writer that returns a Done task to the working State, or to Ready when `ready`, in one write, `reason`
    as the comment the Board machine's REOPEN requires, and a completed task off the archive; a task that is not
    Done is refused untouched."""
    working = shelf.spelled.get(roles.working or "", "")
    ready_lane = shelf.spelled.get(roles.ready or "", "")

    def reopen(task: str, reason: str, /, actor: str = TASK_ACTOR, ready: bool = False) -> Written:
        landing = ready_lane if ready else working

        def edit(frontmatter: dict, body: str) -> str:
            held = str(frontmatter.get("status") or "")
            if lane_id(held) != roles.done:
                raise _Unheld(f"{task} is {held or 'without a status'}, not Done")
            frontmatter["status"] = landing
            return _comment(body, f"Reopened from Done: {reason.strip()}", actor)

        try:
            written = _update(shelf, task, edit, guard, actor)
        except _Unheld as unheld:
            return Written(False, str(unheld))
        return _moved(written, landing)

    return reopen


def _keeps(kept: re.Pattern[str], frontmatter: dict) -> bool:
    return any(kept.fullmatch(label) for label in _strings(frontmatter.get("labels")))


def _completer(shelf: _Shelf, roles: StateRoles, keep: object = None, guard: Guard = Guard()) -> TaskCompleter:
    """A board writer that archives a Done task's History, where the reader and the projection still find it.

    The move enters the `completed` lane where the board has one; a board without it keeps the task in Done. A task
    with a label that fully matches the regex `keep` stays on the board, Done and writable."""
    kept = re.compile(str(keep)) if keep else None
    swept = COMPLETED if COMPLETED in shelf.spelled else None

    def complete(task: str, /) -> Written:
        if (row := shelf.view.row(task)) is None:
            return Written(False, f"{task} is not on the board")
        if row["archived"]:
            return Written(False, f"{task} is already completed")
        frontmatter = _split(shelf.text(row))[0]
        status = str(frontmatter.get("status") or "")
        if lane_id(status) != roles.done:
            return Written(False, f"{task} is {status or 'without a status'}, not Done")
        if swept and (
            refusal := guard.frozen_refusal(rules.Record(frontmatter, ""), frontmatter | {"status": swept}, OPERATOR)
        ):
            return Written(False, refusal)
        if kept is not None and _keeps(kept, frontmatter):
            return Written(False, f"{task} carries a label that keeps it on the board")
        appended(str(row["id"]), None, OPERATOR, head=row["version"])
        written = Written(True, f"Completed task {task}")
        return written if swept is None else _moved(written, swept)

    return complete


def _next_id(view: TaskView, prefix: str, retired: _Retired) -> str:
    """`<prefix>-N` with N one past the highest on the board, its completed, archived and retired tasks included."""
    number = re.compile(rf"{re.escape(prefix)}-(\d+)", re.I)
    highest = retired.highest(number)
    for taken in view.taken():
        if found := number.fullmatch(taken):
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


#: The details `_new_task` writes as lists of text; each other detail it writes is text.
_NEW_TASK_LISTS = {"labels", "dependencies", "acceptanceCriteria"}


def _check_new_task(details: Mapping[str, Any]) -> None:
    for field in _NEW_TASK_DETAILS & details.keys():
        if (value := details[field]) is None:
            continue
        (_text if field not in _NEW_TASK_LISTS else _texts)(field, value)


def _new_task(task: str, title: str, status: str, details: Mapping[str, Any]) -> str:
    """A new task file as Backlog.md writes one: its front matter, then its Description and Acceptance Criteria."""
    frontmatter: dict[str, Any] = {"id": task, "uuid": item_uuid.mint(), "title": title, "status": status}
    if profile := details.get("profile", details.get("assignee")):
        frontmatter["profile"] = [profile]
    keys = ("labels", "milestone", "dependencies", "priority", "impact", "urgency", "created_by")
    frontmatter |= {key: details[key] for key in keys if key in details}
    frontmatter["tier"] = _tier(str(details.get("tier") or "")) or implied_tier(
        str(details.get("type") or ""), details.get("labels") or ()
    )
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
    shelf: _Shelf,
    config: BacklogConfig,
    retired: _Retired,
    guard: Guard = Guard(),
    link: _Linker = _unlinked,
    cohort_milestone: bool = False,
) -> TaskCreator:
    """A board writer that makes a task, its History, with the next id, in one write.

    It starts in the first lane; any detail beyond the ones the page fills (a `status`, `type`, `references`,
    `documentation`, `definitionOfDone`, `plan`, `notes` or other field `edit` sets) is set as `edit` sets it, so a
    detail it cannot set refuses the create and nothing is written. A refused create leaves its id to the next one.
    With `cohort_milestone`, a task created as one of a batch of two or more (`cohort`) must name a `milestone`.
    """
    lock = threading.Lock()  # two creates, in this process or another, must not both read the same highest id
    spelled = shelf.spelled

    def create(title: str, details: Mapping[str, Any], /, actor: str = OPERATOR, cohort: bool = False) -> Written:
        if cohort and cohort_milestone and not str(details.get("milestone") or "").strip():
            return Written(
                False, f"{title}: a batch of two or more tasks is a cohort and needs a `milestone` on each spec"
            )
        with lock, _allocating(shelf.root):
            write_steps.step("lock")
            task = _next_id(shelf.view, config.prefix, retired)
            write_steps.step("allocate")
            rest = {field: value for field, value in details.items() if field not in _NEW_TASK_DETAILS}
            try:
                _check_new_task(details)
                frontmatter, body = _split(_new_task(task, title, config.statuses[0], details))
                body = _apply(task, frontmatter, body, link(rest), spelled)
                write_steps.step("apply")
                landed = _land(shelf, task, None, 0, _stamped(shelf, frontmatter, created=True), body, guard, actor)
                if not landed.ok:
                    return landed
            except ValueError as refusal:
                return Written(False, f"{title}: {refusal}")
            except OSError as error:
                return Written(False, f"{shelf.root}: {error}")
        return _moved(
            Written(True, task, warnings=landed.warnings), str(frontmatter.get("status") or config.statuses[0])
        )

    return create


#: Seconds a `holds`, `unfinished` or notice hook may run. Each starts a Python process and reads the board over HTTP, which takes
#: 20 s under load; a timeout holds the task until the next pass.
HOOK_TIMEOUT = 60.0


def _unlabelled(shelf: _Shelf, task: str, applies: re.Pattern[str]) -> bool:
    """Whether the task has a History and no label fully matching `applies`."""
    if (row := shelf.view.row(task)) is None:
        return False
    return not any(applies.fullmatch(label) for label in row["labels"])


def _entered(command: object, base: Path, shelf: _Shelf, labels: object) -> Callable[..., None]:
    """The `entered` command, as `_notice` runs it, for a task not found or with a label fully matching `labels`."""
    notice = _notice(command, base)
    if not command or not labels:
        return notice
    applies = re.compile(str(labels))

    def entered(task: str) -> None:
        if not _unlabelled(shelf, task, applies):
            notice(task)

    return entered


def _holds(
    command: object, base: Path, shelf: _Shelf | None = None, labels: object = None
) -> Callable[[str], list[str]]:
    """The `holds` or `unfinished` command, run in `base` with `{id}` replaced by the task's id: it prints a JSON array
    of the reasons the task's `deps_done` is withheld, or of the work a merged task has left. Output that is no such array
    raises, which holds the task. With `labels` (a regex) and the board's `shelf`, a task found with no label that fully
    matches it holds nothing and the command, a process spawn per call, does not run. With no command nothing is held."""
    if not command:
        return lambda _task: []
    parts = shlex.split(str(command))
    applies = re.compile(str(labels)) if labels and shelf is not None else None

    def holds(task: str) -> list[str]:
        if applies is not None and shelf is not None and _unlabelled(shelf, task, applies):
            return []
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


def _reason(holds: Callable[[str], list[str]]) -> Callable[[str], str | None]:
    """The `unpublished` command, run with `{id}` replaced by an event subject: it prints a JSON array holding the one
    reason no component publishes the subject, or none."""
    return lambda subject: next(iter(holds(subject)), None)


def _notice(command: object, base: Path, unreachable: bool = False) -> Callable[..., None]:
    """The `parked`, `released`, `idle`, `returned`, `enqueued`, `closed`, `archived`, `frozen`, `halted` or `entered` command
    (the last on any lane entry the board records, by whoever moves the task), run in `base` with `{id}` replaced by the
    task's id, after the task actor moves a task from the working lane to Waiting, from Waiting to Ready, sees its holder
    go idle (with `{verdict}` replaced by the idle step) or writes or clears its `frozen` fact (`freeze` or `thaw`), sends it from Review
    back to the working lane, reads its pull request ready in Review, moves it to Done, or archives it. A nonzero exit raises with what
    the command said. With no command it tells no one."""
    if not command:
        return lambda _task, _verdict="": None
    parts = shlex.split(str(command))

    def notice(task: str, verdict: str = "") -> None:
        argv = [part.replace("{id}", task).replace("{verdict}", verdict) for part in parts]
        done = subprocess.run(argv, cwd=base, capture_output=True, text=True, timeout=HOOK_TIMEOUT, check=False)
        if done.returncode:
            said = done.stderr.strip() or done.stdout.strip() or "printed nothing"
            error = ValueError
            if unreachable and done.returncode == UNREACHABLE_EXIT:
                error = HolderUnreachable
            elif unreachable and done.returncode == GRACE_EXIT:
                error = HolderInGrace
            raise error(f"{shlex.join(argv)}: exit {done.returncode}: {said}")

    return notice


def _probe(command: object, base: Path) -> Callable[[str], bool]:
    """The `alive` command, run in `base` with `{id}` replaced by the task's id: exit 0 says yes, any other exit no; with no command every holder reads as gone."""
    if not command:
        return lambda _task: False
    parts = shlex.split(str(command))

    def probe(task: str) -> bool:
        argv = [part.replace("{id}", task) for part in parts]
        return subprocess.run(argv, cwd=base, capture_output=True, timeout=HOOK_TIMEOUT, check=False).returncode == 0

    return probe


def _owner(command: object, base: Path) -> Callable[[str, str], str] | None:
    """The `faulted` command, run in `base` with `{id}` replaced by the task's id and `{verdict}` by the fault the task
    actor met working it: it prints the id of the open task that owns the fault, filing it when none does. A nonzero
    exit, or output that is no task id, raises. With no command there is no hook."""
    if not command:
        return None
    parts = shlex.split(str(command))

    def owner(task: str, fault: str) -> str:
        argv = [part.replace("{id}", task).replace("{verdict}", fault) for part in parts]
        done = subprocess.run(argv, cwd=base, capture_output=True, text=True, timeout=HOOK_TIMEOUT, check=False)
        printed = done.stdout.strip().upper()
        if done.returncode or not re.fullmatch(r"[A-Z][A-Z0-9]*-\d+", printed):
            said = done.stderr.strip() or done.stdout.strip() or "printed nothing"
            raise ValueError(f"{shlex.join(argv)}: exit {done.returncode}: {said}")
        return printed

    return owner


def board(settings: Mapping[str, Any], base: Path) -> Board:
    """The native board at `settings["path"]` (default `.starpulse/board`), created empty when absent, as the project named for `base`'s directory, kept current by a directory watch.

    Moves, profile changes, creates, edits and archives write the task files and append to the task's History, and once a log is attached `read` returns a task's record from that History, never from its file. Any lane reaches any other unless `machine` names a
    machine file, whose transitions and `writers` then decide which moves are offered, and to whom.
    """
    if unknown := sorted(settings.keys() - _SETTINGS):
        raise ValueError(f"board: unknown key(s) {', '.join(unknown)}; known: {', '.join(sorted(_SETTINGS))}")
    rows = settings.get("policy_rows")
    if rows is not None and not isinstance(rows, Policy):
        raise ValueError(
            "board: `policy_rows` is the stored policy StarPulse hands the board; a config does not set it"
        )
    _python_path(settings.get("python_path"), base)
    root = base / str(settings.get("path", DEFAULT_PATH))
    _create(root, base.resolve().name)
    docs_index = index_of(root)
    link = _doc_linker(docs_index, base)
    migrations: Mapping[str, str] = {}
    labelled: Mapping[str, str] = {}
    if "machine" in settings:
        document = read_document(base / str(settings["machine"]))
        migrations = document.get("migrations", {})
        labelled = {name: spec["label"] for name, spec in document.get("states", {}).items() if spec.get("label")}
    retired = _Retired()
    view = TaskView()
    # A board with no stored policy runs no policy code: no guard, profile cell or lane label.
    guards, matrix, lanes = (guards_of(rows), profile_matrix(rows), rows.lanes) if rows is not None else ([], {}, ())
    guard = Guard(
        rules.load(guards),
        _hook(settings.get("validate")),
        _state_from(view),
        pull_of=_pull_of(retired),
        linked=_linked(retired),
        types=_types(settings),
        effects=entry.load(settings.get("entry"), matrix),
        warn_actors=_warn_actors(settings),
        dependencies_of=view.dependencies_of,
        matrix=matrix,
        qa_lenses=qa_verdicts.lenses_of(lambda: retired.engine, base),
    )

    def surfaces(config: BacklogConfig, roles: StateRoles) -> dict[str, Any]:
        ready = next((status for status in config.statuses if lane_id(status) == roles.ready), "")
        spelled = {lane_id(status): status for status in config.statuses}
        shelf = _Shelf(root, view, spelled, roles.done)
        gate = replace(guard, waiting=roles.waiting, ready=ready, holders=shelf.holders)

        def assign(task: str, profile: str, /, actor: str = OPERATOR) -> Written:
            def edit(frontmatter: dict, body: str) -> str:
                frontmatter["profile"] = [profile]
                return body

            return _update(shelf, task, edit, gate, actor)

        return {
            "writer": _writer(shelf, roles, gate),
            "assign": assign,
            "create": _creator(shelf, config, retired, gate, link, bool(settings.get("cohort_milestone"))),
            "read": _served(view, spelled, roles.done, archived=False, waiting=roles.waiting),
            "read_archived": _served(view, spelled, roles.done, archived=True),
            "holds": _holds(settings.get("holds"), base, shelf, settings.get("holds_labels")),
            "unfinished": _holds(settings.get("unfinished"), base),
            "unpublished": _reason(_holds(settings.get("unpublished"), base)),
            "parked": _notice(settings.get("parked"), base),
            "released": _notice(settings.get("released"), base),
            "idle": _notice(idle, base, unreachable=True) if (idle := settings.get("idle")) else None,
            "returned": _notice(settings.get("returned"), base),
            "alive": _probe(settings.get("alive"), base),
            "enqueued": _notice(settings.get("enqueued"), base),
            "closed": _notice(settings.get("closed"), base),
            "archived": _notice(settings.get("archived"), base),
            "frozen": _notice(settings.get("frozen"), base),
            "halted": _notice(settings.get("halted"), base),
            "faulted": _owner(settings.get("faulted"), base),
            "entered": _entered(settings.get("entered"), base, shelf, settings.get("entered_labels")),
            "edit": _editor(shelf, gate, link, roles.attention, _unstarted(roles)),
            "judge": _editor(shelf, gate, link, roles.attention, _unstarted(roles), True),
            "archive": _archiver(shelf, roles, gate),
            "restore": _restorer(shelf, retired, migrations, gate),
            "complete": _completer(shelf, roles, settings.get("complete_keep_labels"), gate),
            "reopen": _reopener(shelf, roles, gate),
            "retire": _retirer(shelf, retired, roles, config.prefix),
            "retired": _retired_reader(retired),
            "retired_projected": retired.projected,
            "retired_page": retired.page,
            "read_doc": native_docs.reader(root, docs_index),
            "create_doc": native_docs.creator(root, docs_index),
            "edit_doc": native_docs.editor(root, docs_index),
            "archive_doc": native_docs.archiver(root, docs_index),
            "restore_doc": native_docs.restorer(root, docs_index),
            "move_doc": native_docs.mover(root, docs_index),
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
        tuple(lane.label or labelled.get(lane.name, lane.name) for lane in lanes if lane.role),
    )

    history = TaskHistory()

    def attach(log: EventLog) -> None:
        retired.engine = log.engine  # the retired tasks live in the view's history store
        docs_index.engine = log.engine
        native_doc_import.import_files(root, docs_index)  # a doc file added on disk since the last start gets its row
        history.attach(log.engine)
        view.attach(log.engine)
        if settings.get("complete_done"):
            for done_task in view.finished(made.roles.done):
                complete(done_task)  # a Done task left on the board before a move completed it on landing

    def start(feed: BoardFeed, group: str, log: EventLog) -> None:
        attach(log)
        for task, aliases in view.listed():
            for alias in aliases:
                feed.alias(alias, task)

    complete = history.recorded(made.complete)

    def completing(write: MoveWriter) -> MoveWriter:
        def land(task: str, status: str, actor: str) -> Written:
            written = write(task, status, actor)
            if written.ok and settings.get("complete_done") and lane_id(status) == made.roles.done:
                complete(task)
            return written

        return land

    def completing_edit(edit: TaskEditor) -> TaskEditor:
        def land(task: str, changes: Mapping[str, Any], *rest: Any, **named: Any) -> Written:
            written = edit(task, changes, *rest, **named)
            if (
                written.ok
                and settings.get("complete_done")
                and lane_id(str(changes.get("status") or "")) == made.roles.done
            ):
                complete(task)
            return written

        return land

    recorded = {
        "writer": completing(history.recorded(made.writer, moves=True)),
        "assign": history.recorded(made.assign),
        "edit": completing_edit(history.recorded(made.edit, unstarted=_unstarted(made.roles))),
        "archive": history.recorded(made.archive),
        "restore": history.recorded(made.restore),
        "reopen": history.recorded(made.reopen),
        "complete": complete,
        "retire": history.recorded(made.retire),
        "create": history.recorded(made.create),
    }
    final = Board(
        **{
            **vars(made),
            "start": start,
            "attach": attach,
            "standing": _standing(guard, view),
            "readable": guard.readable,
            **recorded,
        }
    )
    return final


#: How many tasks' standing verdicts `_standing` keeps, the oldest placed dropped first.
_STANDING_KEPT = 512

#: The columns a row's every event moves, which no rendered file holds: a verdict stays while the rest of the row does.
_MOVING = ("version", "updated_at")


def _standing(guard: Guard, view: TaskView) -> Callable[[str, str], dict[str, Any] | None]:
    """The board rules' verdict on moving the task `task` to `lane` as its History stands now, or None for a task with no
    History or no refusing rule.

    A task is read once and each lane judged once while it stands (its History row), the verdicts shared by every reader
    thread: judging the rules costs tens of milliseconds, the read and parse under one."""

    versions: dict[str, tuple[str, dict, str, dict[str, dict[str, Any] | None]]] = {}
    judging = threading.Lock()

    def standing(task: str, lane: str) -> dict[str, Any] | None:
        if (row := view.row(task)) is None:
            return None
        with judging:
            held = versions.get(row["id"])
            content = json.dumps({key: value for key, value in row.items() if key not in _MOVING}, default=str)
            if held is None or held[0] != content:
                front, body = _file_of(_record_from(row, {}))
                held = versions[row["id"]] = (content, front, body, {})
                if len(versions) > _STANDING_KEPT:
                    del versions[next(iter(versions))]
            if lane not in held[3]:
                held[3][lane] = guard.standing(held[1], held[2], lane)
            return held[3][lane]

    return standing


def _state_from(view: TaskView) -> Callable[[str], str | None]:
    """A lookup of the state (its lane id) of a task's History, None for a task with none."""

    def state(task: str) -> str | None:
        return None if (row := view.row(task)) is None else lane_id(str(row["state"]).strip())

    return state


def _served(
    view: TaskView,
    spelled: Mapping[str, str],
    done: str | None,
    *,
    archived: bool,
    waiting: str | None = None,
) -> TaskReader:
    """A board reader of a task's History record; the archived reader answers any task, the live one an unarchived task or
    an archived Done one, which the board keeps readable.
    A Done or archived task has nothing left to start, and a task outside Waiting no event wait."""

    def read(task: str, /) -> dict[str, Any] | None:
        if (row := view.row(task)) is None:
            return None
        lane = lane_id(str(row["state"]))
        if not archived and row["archived"] and lane != done:
            return None
        record = _record_from(row, spelled)
        return {**record, "start_criteria": [] if archived else _live_criteria(record, lane, done, waiting)}

    return read
