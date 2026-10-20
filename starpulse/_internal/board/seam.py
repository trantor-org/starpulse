"""The board adapter seam: where the Board's tasks and the machines the page draws come from.

The config's `[board]` table names the adapter by `type`: a module under `starpulse` (the default is
`native`, StarPulse's own Markdown board; `upstream_backlog` reads a Backlog.md project's task files) or a dotted
module path an installed package provides.
The module's `board(settings, base)` returns a `Board`; `settings` is the rest of the `[board]` table and
`base` the directory relative paths in it are read from.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from starpulse._internal.config.adapter_types import module_name
from starpulse._internal.config.config import DEFAULT_TYPE

if TYPE_CHECKING:
    from starpulse._internal.feed.board_feed import BoardFeed
    from starpulse._internal.eventlog.event_log import EventLog
    from starpulse._internal.machines.snapshot import Qualify
    from starpulse.contracts.task_keys import TaskKeys

__all__ = [
    "AGENT",
    "ANONYMOUS",
    "DEFAULT_TYPE",
    "HELD",
    "MERGE_EVIDENCE",
    "AssigneeWriter",
    "Board",
    "DocArchiver",
    "DocCreator",
    "DocEditor",
    "DocLister",
    "DocReader",
    "DocRestorer",
    "MilestoneArchiver",
    "MilestoneCreator",
    "MilestoneEditor",
    "MilestoneLister",
    "MilestoneReader",
    "MoveWriter",
    "OPERATOR",
    "RetiredImporter",
    "RetiredReader",
    "TaskArchiver",
    "TaskCompleter",
    "TaskCreator",
    "TaskEditor",
    "TaskReader",
    "TaskRestorer",
    "TaskRetirer",
    "Written",
    "load",
    "module_name",
]

#: Who the page acts for, which it names on every write it makes.
OPERATOR = "operator"
#: What a close comment of merge evidence starts with; a board writes the same one once per task.
MERGE_EVIDENCE = "Closed on merge evidence:"
#: What a hold comment starts with; a board does not repeat the task's latest one, so a restart writes nothing new.
HELD = "Held from Ready:"
#: Who a session's write is made by when it names no actor.
AGENT = "agent"
#: Who a write is made by when it names no actor and no session: never the operator.
ANONYMOUS = "anonymous"


class Written(NamedTuple):
    """What a board writer did with a status change: `output` is its response, or its refusal and the `skill` that satisfies it.

    `unavailable` marks a board with no writer at all, which is no refusal of this change but of every one."""

    ok: bool
    output: str = ""
    skill: str = ""
    unavailable: bool = False
    advice: str = ""
    """What the writer tells the mover about the task now it is moved (a routing profile); empty when it has nothing to say."""
    lane: str | None = None
    """The lane the write put the task in, in the board's spelling; unset when it moved none (a note, a refusal, or a
    board that does not say), and the server then records nothing for it: the board's watch records the placement."""
    at: float | None = None
    """When the write put the task there, in epoch seconds; set with `lane`."""


#: A board writer: set a task's status for `actor` and say what it did. A move that names the mover's `session` passes it
#: as a fourth argument; one that names none passes three, so a writer that predates sessions keeps working. A claim
#: records the session as the task's assignee.
MoveWriter = Callable[..., Written]
#: Set a task's assignee for `actor` (a keyword, omitted when the write names none), and say what it did. The same holds
#: for `TaskEditor`, `TaskArchiver` and `TaskCreator`.
AssigneeWriter = Callable[..., Written]
#: One task's full record keyed by its editable fields, or None when the board has no such task.
TaskReader = Callable[[str], Mapping[str, Any] | None]
#: Apply every change to a task in one write, `(task, changes, comment | [comment, ...], /, actor=)`.
TaskEditor = Callable[..., Written]
#: Archive a task with the reason when there is one, `(task, reason, /, actor=)`.
TaskArchiver = Callable[..., Written]
#: Return an archived task's file to the board's tasks, unchanged. A task with no archived file, or whose number is
#: already open or completed, is refused.
TaskRestorer = Callable[[str], Written]
#: Take a finished task's file off the board into its retired tasks, kept whole. A Done task, or an archived one in any
#: state, is retired; an open or unknown task, or one whose number is already retired with other text, is refused.
TaskRetirer = Callable[[str], Written]
#: The retired task `task` as `[{task, name, text}]` (id, file name and file text), empty when it is not retired; a blank
#: `task` reads every retired task, by id.
RetiredReader = Callable[[str], list[Mapping[str, str]]]
#: Keep the file `name` with `text`, retired elsewhere, among the retired tasks; a successful `Written.output` is the
#: task's id. Text that names no task id, a name that is no plain file name, a task on the board, or a task retired with
#: other text is refused; the same task with the same text is accepted again.
RetiredImporter = Callable[[str, str], Written]
#: Move a Done task out of the lanes into the board's completed tasks; one that is not Done, is already completed or has
#: no file is refused. A completed task is still read and edited.
TaskCompleter = Callable[[str], Written]
#: Create a task with this title and details in the starting lane, `(title, details, /, actor=)`. `details` holds only
#: the fields the page filled (`description`, `priority`, `labels`, `milestone`, `assignee`, `dependencies`,
#: `acceptanceCriteria`); a caller in the same process may pass any other field `TaskEditor` sets. A successful
#: `Written.output` is the new task's id.
TaskCreator = Callable[..., Written]
#: Every open milestone as `{id, title, outcome, specs, adrs, retro, description}`, oldest id first.
MilestoneLister = Callable[[], list[Mapping[str, Any]]]
#: One milestone's record, or None when the board has no open milestone with that id.
MilestoneReader = Callable[[str], Mapping[str, Any] | None]
#: Open a milestone with this title and details (`outcome`, `retro` as text, `specs`, `adrs` as lists, each optional); a
#: successful `Written.output` is the new milestone's id.
MilestoneCreator = Callable[[str, Mapping[str, Any]], Written]
#: Replace the `title`, `outcome`, `specs`, `adrs` or `retro` a milestone is given, keeping the rest.
MilestoneEditor = Callable[[str, Mapping[str, Any]], Written]
#: Archive a milestone.
MilestoneArchiver = Callable[[str], Written]
#: Every open doc as `{id, title, type, created_date, updated_date, path}` without its body, oldest id first.
DocLister = Callable[[], list[Mapping[str, Any]]]
#: One doc's record with its `body`, or None when the board has no open doc with that id.
DocReader = Callable[[str], Mapping[str, Any] | None]
#: File a doc with this title and details (`type`: `specification`, `guide`, `readme` or `other`, the default; `folder`
#: under the board's `docs/`; `body`, each optional); a successful `Written.output` is the new doc's id.
DocCreator = Callable[[str, Mapping[str, Any]], Written]
#: Replace the `title`, `type` or `body` a doc is given, keeping the rest.
DocEditor = Callable[[str, Mapping[str, Any]], Written]
#: Archive a doc.
DocArchiver = Callable[[str], Written]
#: Return an archived doc's file, unchanged, to the board's docs under `folder` (a path of plain names under `docs/`,
#: `docs/` itself when blank), `(doc, folder="", /)`. An archive keeps no folder, so the caller names where the doc goes;
#: a doc with no archived file, one whose id is already open, or whose destination file exists is refused.
DocRestorer = Callable[..., Written]


def _no_cues(qualify: Qualify) -> list[dict]:
    return []


@dataclass(frozen=True)
class Board:
    """What a board adapter hands the server."""

    machines: Callable[[Qualify, Collection[str]], dict[str, dict]]
    """Every machine the page draws, the Board's as `board`, naming workflows as `qualify` does; the collection is
    the `<instance>/<workflow>` names the config lists, for an adapter that refuses a writer naming another."""
    start: Callable[[BoardFeed, str, EventLog], None]
    """Begin placing the Board's tasks on the feed, on threads of the adapter's own; the text is a name unique to this
    running view, and the log is the event log of the view's database, which an adapter that reads another system's
    events appends them to (`board_feed.follow` reads a stream of it into the feed)."""
    keys: TaskKeys | None = None
    """The tracker's task key scheme; None places any key."""
    cues: Callable[[Qualify], Sequence[dict]] = _no_cues
    """The workflow cues the page draws, each `{dag, ...}` with its workflow named as `qualify` does."""
    waits: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    """The facts the Board machine's states wait on, `{lane: {fact kind: event}}`; empty when the machine declares none."""
    writer: MoveWriter | None = None
    """Sets a task's status when the page moves it; None refuses every move."""
    assign: AssigneeWriter | None = None
    """Sets the assignee the page picked when starting a task's session; None refuses a changed assignee."""
    source: str = "the board"
    """What the page says the Board is read from until the adapter is ready."""
    read: TaskReader | None = None
    """Reads a task's full record when the page opens it; None leaves the page with the snapshot's fields."""
    edit: TaskEditor | None = None
    """Saves the page's edits to a task in one write; None refuses every edit. Needs `read`, which it is checked against."""
    archive: TaskArchiver | None = None
    """Archives a task from any column; None refuses every archive."""
    restore: TaskRestorer | None = None
    """Returns an archived task to the board's tasks; None refuses every restore."""
    complete: TaskCompleter | None = None
    """Completes a Done task; None refuses every complete."""
    retire: TaskRetirer | None = None
    """Takes a finished task off the board into its retired tasks; None refuses every retire."""
    retired: RetiredReader | None = None
    """Reads the retired tasks; None when the board keeps none."""
    import_retired: RetiredImporter | None = None
    """Keeps a task retired elsewhere among the retired tasks; None refuses every import."""
    create: TaskCreator | None = None
    """Creates a task in the first lane when the page asks for a new one; None refuses every create."""
    milestones: MilestoneLister | None = None
    """Lists the open milestones; None leaves the board with no milestone records."""
    read_milestone: MilestoneReader | None = None
    """Reads one milestone's record; None when the board keeps none."""
    create_milestone: MilestoneCreator | None = None
    """Opens a milestone; None refuses every one."""
    edit_milestone: MilestoneEditor | None = None
    """Saves a milestone's changes in one write; None refuses every one."""
    archive_milestone: MilestoneArchiver | None = None
    """Archives a milestone; None refuses every one."""
    docs: DocLister | None = None
    """Lists the open docs; None leaves the board with no doc records."""
    read_doc: DocReader | None = None
    """Reads one doc's record; None when the board keeps none."""
    create_doc: DocCreator | None = None
    """Files a doc; None refuses every one."""
    edit_doc: DocEditor | None = None
    """Saves a doc's changes in one write; None refuses every one."""
    archive_doc: DocArchiver | None = None
    """Archives a doc; None refuses every one."""
    restore_doc: DocRestorer | None = None
    """Returns an archived doc to the board's docs; None refuses every one."""
    evaluate: Callable[[str, str], list[dict[str, Any]]] | None = None
    """Evaluates a task's Start Criteria, given its id and description; None leaves each `not evaluated`, so a Waiting task
    that declares any is never workable."""
    holds: Callable[[str], Sequence[str]] | None = None
    """Why the board withholds a task's `deps_done` from the task actor, given its id; empty when nothing does, and an
    exception holds the task. None holds no task."""
    state_key: Callable[[], str] | None = None
    """Names what a rebuild of the whole Board depends on (the project's config and machine, not the projection code,
    whose change the adapter diffs task by task), so a Board checkpointed for another is never resumed; None when the adapter keeps none. Called when the replica's checkpoint
    is keyed on it (`starpulse._internal.board.replica`), not when the Board is loaded."""
    attach: Callable[[EventLog], None] | None = None
    """What a context that reads the Board from the replica, and so never calls `start`, needs of the event log the
    adapter would have been handed there; None needs nothing."""

    def __post_init__(self) -> None:
        if self.edit is not None and self.read is None:
            raise ValueError(
                "a board that edits tasks must also read them: an edit is checked against the current record"
            )


def load(kind: str, settings: Mapping[str, Any], base: Path) -> Board:
    """The board the adapter module `kind` builds from `settings`."""
    module = importlib.import_module(module_name(kind))
    if not callable(factory := getattr(module, "board", None)):
        raise ValueError(f"board type {kind}: {module.__name__} has no board(settings, base)")
    return factory(settings, base)
