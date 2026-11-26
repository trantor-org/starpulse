"""The Board: what the server, the views and the task actor read and write of StarPulse's Markdown board.

`starpulse.board.adapters.native.board` builds the one a `[board]` table of type `native` names.
"""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

from starpulse.machine_engine.model.state_roles import StateRoles

if TYPE_CHECKING:
    from starpulse.board.model.board_feed import BoardFeed
    from starpulse.contracts.task_keys import TaskKeys
    from starpulse.event_log.event_log import EventLog
    from starpulse.machine_engine.model.snapshot import Qualify

__all__ = [
    "AGENT",
    "ANONYMOUS",
    "COMMENT_CAP",
    "FLAGGED",
    "HELD",
    "MERGE_EVIDENCE",
    "AssigneeWriter",
    "Board",
    "DocArchiver",
    "DocCreator",
    "DocEditor",
    "DocReader",
    "DocRestorer",
    "MilestoneArchiver",
    "MilestoneCreator",
    "MilestoneEditor",
    "MilestoneLister",
    "MilestoneReader",
    "MoveWriter",
    "OPERATOR",
    "RETRO_MARKER",
    "RetiredProjector",
    "RetiredReader",
    "TaskArchiver",
    "TaskCompleter",
    "TaskCreator",
    "TaskEditor",
    "TaskReader",
    "TaskReopener",
    "TaskRestorer",
    "TaskRetirer",
    "Written",
]

#: Who the page acts for, which it names on every write it makes.
OPERATOR = "operator"
#: The most characters one board comment holds: the agent CLI refuses a longer one, and the task actor clips its own.
COMMENT_CAP = 4000
#: What a close comment of merge evidence starts with; a board writes the same one once per task.
MERGE_EVIDENCE = "Closed on merge evidence:"
#: What a hold comment starts with; a board does not repeat the task's latest one, so a restart writes nothing new.
HELD = "Held from Ready:"
#: What a flag comment starts with: a Waiting task nothing can release; a board does not repeat the task's latest one.
FLAGGED = "Flagged in Waiting:"
#: Who a session's write is made by when it names no actor.
AGENT = "agent"
#: Who a write is made by when it names no actor and no session: never the operator.
ANONYMOUS = "anonymous"
#: The task actor, who writes the moves no agent or operator makes (`pulls.adapters.inbound.task_actor.ACTOR`).
TASK_ACTOR = "starpulse/task-actor"


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
    moves: tuple[tuple[str, str], ...] = ()
    """Each other task the write moved at `at`, with the lane it put it in: the server records them as the request's actor."""
    lint: bool = False
    transient: bool = False
    """The write raised a locked-database error that outlasted its retries: no refusal of the change, so the task stays put."""
    """Whether a declared guard or the board's validate hook refused the write: a defect in the task record an editor of the record repairs."""
    warnings: tuple[str, ...] = ()
    """The reasons of the lane rules the write broke and landed anyway, which only an operator's move may; empty for a clean write."""
    version: str = ""
    """What an audit judged the write over, to pass back as `over`; empty for a write that landed."""
    rule: str = ""
    """The `key` of the guard rule that refused the write, never its text; empty for a refusal no rule made."""


class MoveWriter(Protocol):
    """A board writer: set a task's status for `actor` and say what it did. The assignee is the task actor's alone."""

    def __call__(self, task: str, status: str, actor: str) -> Written: ...


class AssigneeWriter(Protocol):
    """Set a task's assignee to `profile` for `actor` (a keyword, omitted when the write names none), and say what it
    did. The same holds for `TaskEditor`, `TaskArchiver` and `TaskCreator`."""

    def __call__(self, task: str, profile: str, /, actor: str = ...) -> Written: ...


#: One task's full record keyed by its editable fields, or None when the board has no such task.
TaskReader = Callable[[str], Mapping[str, Any] | None]


class TaskEditor(Protocol):
    """Apply every change to a task in one write, with a comment or a list of them. With `over`, the `version` an audit
    judged, the write lands only on that record: a task changed since is no refusal (`transient`), judged again."""

    def __call__(
        self, task: str, changes: Mapping[str, Any], comment: str | Sequence[str], /, actor: str = ..., over: str = ...
    ) -> Written: ...


class TaskArchiver(Protocol):
    """Archive a task with the reason when there is one."""

    def __call__(self, task: str, reason: str, /, actor: str = ...) -> Written: ...


#: Return an archived task's file to the board's tasks, unchanged. A task with no archived file, or whose number is
#: already open or completed, is refused.
TaskRestorer = Callable[[str], Written]
#: Return a Done task, completed or not, to the working State with `reason` as its comment, as `actor`: `(task, reason, /,
#: actor)`. A task that is not Done is refused.
TaskReopener = Callable[..., Written]
#: Take a finished task's file off the board into its retired tasks, kept whole. A Done task, or an archived one in any
#: state, is retired; an open or unknown task, or one whose number is already retired with other text, is refused.
TaskRetirer = Callable[[str], Written]
#: The retired task `task` as `[{task, name, text}]` (id, file name and file text), empty when it is not retired; a blank
#: `task` reads every retired task, by id, as an iterator that reads a page of rows at a time, so a caller encoding the
#: rows one by one never holds them all.
RetiredReader = Callable[[str, str], Iterable[Mapping[str, str]]]
#: `(project, task, milestone)` as `[(id, project(text))]` over the same retired tasks `RetiredReader` reads, the texts
#: read a page at a time and dropped once projected, so a caller wanting only what `project` keeps holds no text.
RetiredProjector = Callable[[Callable[[str], Any], str, str], list[tuple[str, Any]]]
#: One page of the retired tasks, newest retired first: `(limit, before)` as the rows (`{task, name, text}`) after the
#: cursor `before` ("" for the first page) at most `limit` long, and the cursor of the page that follows, None on the
#: last. A `before` that is no cursor raises `ValueError`.
RetiredPager = Callable[[int, str], tuple[list[Mapping[str, str]], str | None]]
#: Move a Done task out of the lanes into the board's completed tasks; one that is not Done, is already completed or has
#: no file is refused. A completed task is still read and edited.
TaskCompleter = Callable[[str], Written]


class TaskCreator(Protocol):
    """Create a task with this title and details in the starting lane. `details` holds only the fields the page filled
    (`description`, `priority`, `impact`, `urgency`, `tier`, `labels`, `milestone`, `assignee`, `dependencies`,
    `acceptanceCriteria`); a caller in the same process may pass any other field `TaskEditor` sets. `cohort` says the
    task is one of a batch of two or more. A successful `Written.output` is the new task's id."""

    def __call__(self, title: str, details: Mapping[str, Any], /, actor: str = ..., cohort: bool = ...) -> Written: ...


#: Every open milestone as `{id, title, outcome, specs, adrs, retro, description}`, oldest id first.
MilestoneLister = Callable[[], list[Mapping[str, Any]]]
#: One milestone's record, or None when the board has no open milestone with that id.
MilestoneReader = Callable[[str], Mapping[str, Any] | None]
#: The `Retro` line a milestone opened without one gets: its first task opens the retro, and the retro waits on every
#: open task in the milestone. A `retro` of `""` opens a milestone that asks for none.
RETRO_MARKER = "Opens when the first task is filed into this milestone, and waits on every open task in it."
#: Open a milestone with this title and details (`outcome`, `retro` as text, `specs`, `adrs` as lists, each optional); a
#: successful `Written.output` is the new milestone's id.
MilestoneCreator = Callable[[str, Mapping[str, Any]], Written]
#: Replace the `title`, `outcome`, `specs`, `adrs` or `retro` a milestone is given, keeping the rest.
MilestoneEditor = Callable[[str, Mapping[str, Any]], Written]
#: Archive a milestone.
MilestoneArchiver = Callable[[str], Written]
#: One doc's record with its `body`, or None when the board has no open doc with that id.
DocReader = Callable[[str], Mapping[str, Any] | None]
#: File a doc with this title and details (`type`: `specification`, `guide`, `readme`, `postmortem` or `other`, the default; `folder`
#: under the board's `docs/`; `body`, each optional); a successful `Written.output` is the new doc's id.
DocCreator = Callable[[str, Mapping[str, Any]], Written]
#: Replace the `title`, `type` or `body` a doc is given, keeping the rest.
DocEditor = Callable[[str, Mapping[str, Any]], Written]
#: Archive a doc.
DocArchiver = Callable[[str], Written]


class DocRestorer(Protocol):
    """Return an archived doc's file, unchanged, to the board's docs under `folder` (a path of plain names under
    `docs/`, `docs/` itself when blank). An archive keeps no folder, so the caller names where the doc goes; a doc with
    no archived file, one whose id is already open, or whose destination file exists is refused."""

    def __call__(self, doc: str, folder: str = "", /) -> Written: ...


@dataclass(frozen=True)
class Board:
    """What the server reads and writes of a board."""

    machines: Callable[[Qualify, Collection[str]], dict[str, dict]]
    """Every machine the page draws, the Board's as `board`, naming workflows as `qualify` does; the collection is
    the `<instance>/<workflow>` names the config lists, so a writer naming another is refused."""
    start: Callable[[BoardFeed, str, EventLog], None]
    """Begin placing the Board's tasks on the feed, on threads of its own; the text is a name unique to this
    running view, and the log is the event log of the view's database."""
    keys: TaskKeys | None
    """The board's task key scheme; None places any key."""
    cues: Callable[[Qualify], Sequence[dict]]
    """The workflow cues the page draws, each `{dag, ...}` with its workflow named as `qualify` does."""
    waits: Mapping[str, Mapping[str, str]]
    """The facts the Board machine's states wait on, `{lane: {fact kind: event}}`; empty when the machine declares none."""
    roles: StateRoles
    """The Board machine's states by the role each plays; a board with no machine file has the roles its statuses imply."""
    writer: MoveWriter
    """Sets a task's status when the page moves it."""
    assign: AssigneeWriter
    """Sets the assignee the page picked when starting a task's session."""
    source: str
    """What the page says the Board is read from until the board is ready."""
    read: TaskReader
    """Reads a task's full record when the page opens it."""
    read_archived: TaskReader
    """Reads an archived task's full record, which `read` never finds."""
    edit: TaskEditor
    """Saves the page's edits to a task in one write."""
    judge: TaskEditor
    """What the board's rules say of an edit by the task actor, which they never refuse: the refusal, or ok, and nothing
    is written. The actor reads it as a fact before it writes a move."""
    archive: TaskArchiver
    """Archives a task from any column."""
    restore: TaskRestorer
    """Returns an archived task to the board's tasks."""
    standing: Callable[[str, str], Mapping[str, Any] | None]
    """The update to the move of a task to a lane that the board's rules make for the task as it stands: a refusal, and
    the verdict of each actor a rule exempts (`Move.actors`)."""
    readable: Callable[[Mapping[str, Any], str], str]
    """What the board's `readable` rules find broken in the description of a task, or "" when it reads well."""
    complete: TaskCompleter
    """Completes a Done task."""
    reopen: TaskReopener
    """Returns a Done task to the working State, its file back in the board's tasks."""
    retire: TaskRetirer
    """Takes a finished task off the board into its retired tasks."""
    retired: RetiredReader
    """Reads the retired tasks."""
    retired_projected: RetiredProjector
    """Reads the retired tasks through a projection of each text."""
    retired_page: RetiredPager
    """Reads the retired tasks a page at a time, newest first."""
    create: TaskCreator
    """Creates a task in the first lane when the page asks for a new one."""
    milestones: MilestoneLister
    """Lists the open milestones."""
    read_milestone: MilestoneReader
    """Reads one milestone's record."""
    create_milestone: MilestoneCreator
    """Opens a milestone."""
    edit_milestone: MilestoneEditor
    """Saves a milestone's changes in one write."""
    archive_milestone: MilestoneArchiver
    """Archives a milestone."""
    read_doc: DocReader
    """Reads one doc's record."""
    create_doc: DocCreator
    """Files a doc."""
    edit_doc: DocEditor
    """Saves a doc's changes in one write."""
    archive_doc: DocArchiver
    """Archives a doc."""
    restore_doc: DocRestorer
    """Returns an archived doc to the board's docs."""
    holds: Callable[[str], Sequence[str]]
    """Why the board withholds a task's `deps_done` from the task actor, given its id; empty when nothing does, and an
    exception holds the task."""
    unfinished: Callable[[str], Sequence[str]]
    """The work a task whose pull requests merged still has, given its id; empty when none, and an exception reports
    the error as the work left."""
    unpublished: Callable[[str], str | None]
    """Why no component publishes an event subject, so a wait on it never ends, given the subject; None when one does
    or the board cannot judge. An exception counts as None."""
    parked: Callable[[str], None]
    """Tells whoever works a task that the task actor moved it from the working lane to Waiting, given its id; a raise is
    logged and the move stands."""
    released: Callable[[str], None]
    """Tells whoever held a task that the task actor moved it from Waiting to Ready, given its id, so a task that was
    parked mid-work is resumed whatever admits Ready tasks; a raise is logged and the move stands."""
    idle: Callable[[str, str], None] | None
    """Tells the session holding a task In Progress that it went idle, given the task's id and `checkpoint` (the first
    idle: resume the holder to checkpoint) or `confirm` (the second); a raise says the holder is busy or was not reached,
    and that idle is not counted. None when the config sets no idle command, so the task actor tracks no idle."""
    returned: Callable[[str], None]
    """Tells whoever held a task that the task actor moved it from Review back to the working lane, given its id, so the
    session that delivered it fixes the pull request that turned draft or conflicting; a raise is logged and the move
    stands."""
    alive: Callable[[str], bool]
    """Whether the session holding a task is running, given its id, so a Review task whose pull request is not green goes
    back to that session when it is and to the queue when it is not."""
    enqueued: Callable[[str], None]
    """Puts a Review task's ready pull request in the merge queue, given the task's id, when the task actor reads
    `pr_ready` in Review; the task stays in Review and a raise is logged."""
    closed: Callable[[str], None]
    """Tells the board that the task actor moved a task to Done, given its id, so it can file what follows the close; a
    raise is logged and the close stands."""
    entered: Callable[[str], None]
    """Tells the board that a task entered a lane, given its id, for every lane change `board:lanes` records whoever
    wrote it; a raise is logged and the move stands."""
    attach: Callable[[EventLog], None]
    """What a context that reads the Board from the read model, and so never calls `start`, needs of the event log `start` would have been handed there."""
    archived: Callable[[str], None]
    """Tells the board that the task actor archived a task, given its id, so it can close the pull requests the task
    leaves open; a raise is logged and the archive stands."""
    frozen: Callable[[str], None]
    """Tells the board that the task actor froze or unfroze a task, given its id, so it can post the freeze on the pull
    requests the task references; a raise is logged and the write stands."""
    halted: Callable[[str, str], None]
    """Tells the board that the task actor wrote or cleared a task's `frozen` fact, given its id and `freeze` or `thaw`, so
    the holder session is halted in place or resumed; a raise is logged and the fact stands."""
