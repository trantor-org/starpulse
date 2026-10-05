"""The board adapter seam: where the Board's tasks and the machines the page draws come from.

The config's `[board]` table names the adapter by `type`: a module under `starpulse` (the default is
`upstream_backlog`, a Backlog.md project's task files) or a dotted module path an installed package provides.
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
    from starpulse.history import History

__all__ = ["DEFAULT_TYPE", "AssigneeWriter", "Board", "MoveWriter", "Written", "load", "module_name"]

DEFAULT_TYPE = "upstream_backlog"


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


def _no_cues(qualify: Qualify) -> list[dict]:
    return []


@dataclass(frozen=True)
class Board:
    """What a board adapter hands the server."""

    machines: Callable[[Qualify, Collection[str]], dict[str, dict]]
    """Every machine the page draws, the Board's as `board`, naming workflows as `qualify` does; the collection is
    the `<instance>/<workflow>` names the config lists, for an adapter that refuses a writer naming another."""
    start: Callable[[BoardFeed, str], None]
    """Begin placing the Board's tasks on the feed, on threads of the adapter's own; the text is a name unique to this
    running view, for a stream consumer group."""
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
    redis_prefixes: tuple[str, ...] = ()
    """The `<PREFIX>_REDIS_*` names of the streams the adapter reads, pointed at the view's Redis."""
    source: str = "the board"
    """What the page says the Board is read from until the adapter is ready."""


def module_name(kind: str) -> str:
    """The module a `[board]` or `[[runs]]` type names: a dotted path as it is, a bare name under `starpulse`."""
    return kind if "." in kind else f"starpulse.{kind}"


def load(kind: str, settings: Mapping[str, Any], base: Path) -> Board:
    """The board the adapter module `kind` builds from `settings`."""
    module = importlib.import_module(module_name(kind))
    if not callable(factory := getattr(module, "board", None)):
        raise ValueError(f"board type {kind}: {module.__name__} has no board(settings, base)")
    return factory(settings, base)
