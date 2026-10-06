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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

from starpulse.contracts import TaskKeys
from starpulse.snapshot import Qualify

if TYPE_CHECKING:
    from starpulse.board_feed import BoardFeed
    from starpulse.event_log import EventLog
    from starpulse.history import History

__all__ = [
    "DEFAULT_TYPE",
    "AssigneeWriter",
    "Board",
    "MoveWriter",
    "TaskArchiver",
    "TaskCreator",
    "TaskEditor",
    "TaskReader",
    "Written",
    "load",
    "module_name",
]

DEFAULT_TYPE = "native"


class Written(NamedTuple):
    """What a board writer did with a status change: `output` is its response, or its refusal and the `skill` that satisfies it.

    `unavailable` marks a board with no writer at all, which is no refusal of this change but of every one."""

    ok: bool
    output: str
    skill: str = ""
    unavailable: bool = False
    advice: str = ""
    """What the writer tells the mover about the task now it is moved (a routing profile); empty when it has nothing to say."""


class MoveWriter(Protocol):
    """A board writer: set a task's status on behalf of `actor` (`operator` or `agent`), and say what it did.

    A move that names the mover's `session` calls the writer with it as a fourth argument; a move that names none calls it
    with three, so a writer that predates sessions keeps working. A writer records the session as the task's holder when
    the move is a claim."""

    def __call__(self, task: str, status: str, actor: str, session: str = "") -> Written: ...


class AssigneeWriter(Protocol):
    """A board writer: set a task's assignee, and say what it did."""

    def __call__(self, task: str, assignee: str, /) -> Written: ...


class TaskReader(Protocol):
    """A board reader: one task's full record, keyed by its editable fields, or None when the board has no such task."""

    def __call__(self, task: str, /) -> Mapping[str, Any] | None: ...


class TaskEditor(Protocol):
    """A board writer: apply every change to a task in one write, with the comment the write records, and say what it did."""

    def __call__(self, task: str, changes: Mapping[str, Any], comment: str, /) -> Written: ...


class TaskArchiver(Protocol):
    """A board writer: archive a task, recording the reason when there is one, and say what it did."""

    def __call__(self, task: str, reason: str, /) -> Written: ...


class TaskCreator(Protocol):
    """A board writer: create a task with this title in the board's first lane, and say what it did.

    A successful `Written.output` is the new task's id."""

    def __call__(self, title: str, /) -> Written: ...


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
    writer: MoveWriter | None = None
    """Sets a task's status when the page moves it; None refuses every move."""
    assign: AssigneeWriter | None = None
    """Sets the assignee the page picked when starting a task's session; None refuses a changed assignee."""
    history: Callable[[Mapping[str, dict]], History | None] = lambda machines: None
    """A history the adapter keeps itself, given the drawn machines; None uses StarPulse's own store."""
    source: str = "the board"
    """What the page says the Board is read from until the adapter is ready."""
    read: TaskReader | None = None
    """Reads a task's full record when the page opens it; None leaves the page with the snapshot's fields."""
    edit: TaskEditor | None = None
    """Saves the page's edits to a task in one write; None refuses every edit. Needs `read`, which it is checked against."""
    archive: TaskArchiver | None = None
    """Archives a task from any column; None refuses every archive."""
    create: TaskCreator | None = None
    """Creates a task in the first lane when the page asks for a new one; None refuses every create."""

    def __post_init__(self) -> None:
        if self.edit is not None and self.read is None:
            raise ValueError(
                "a board that edits tasks must also read them: an edit is checked against the current record"
            )


def module_name(kind: str) -> str:
    """The module a `[board]` or `[[runs]]` type names: a dotted path as it is, a bare name under `starpulse`."""
    return kind if "." in kind else f"starpulse.{kind}"


def load(kind: str, settings: Mapping[str, Any], base: Path) -> Board:
    """The board the adapter module `kind` builds from `settings`."""
    module = importlib.import_module(module_name(kind))
    if not callable(factory := getattr(module, "board", None)):
        raise ValueError(f"board type {kind}: {module.__name__} has no board(settings, base)")
    return factory(settings, base)
