"""A stale Assignee is released (D6): a claim no Event by its session renewed within the claim TTL ends.

StarPulse appends `Released` and a comment naming the last renewal. The Task keeps its State, so a Task still in
progress is never offered to another agent as Ready; it only has no Assignee, and any session may claim it.

A session whose harness wrote a terminal halt as its last turn, with nothing renewing the claim after it, has stopped
for good: its claim is released at once, before the TTL, and the comment names the halt."""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from starpulse.board.adapters.running_workflows import DEFAULT_QUERY, running_tasks
from starpulse.board.model.seam import Board
from starpulse.event_log.store import EventStore, NewEvent, StoredEvent
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:
    from starpulse.board.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog

__all__ = ["DEFAULT_TTL", "ACTOR", "last_renewal", "start", "sweep", "transcript_halt"]

DEFAULT_TTL = 30 * 60
"""Seconds a claim lives without an Event by its session: `[board] claim_ttl`."""
DEFAULT_TRANSCRIPTS = "~/.claude/projects"
"""Where Claude Code writes each session's transcript, read for a terminal halt: `[board] transcripts`."""
logger = logging.getLogger(__name__)
ACTOR = "starpulse"
WRITER = "claim-ttl"


def last_renewal(events: Iterable[StoredEvent], session: str) -> float | None:
    """The moment of the latest Event by `session` or naming it, as a claim's does; None when there is none."""
    carried = (event.at for event in events if session == event.actor or session in json.dumps(event.payload))
    return max(carried, default=None)


TERMINAL_HALTS = ("Autocompact is thrashing",)
"""How the halts that end a session for good open: Claude Code writes each as a synthetic error reply."""
TURNS = frozenset({"user", "assistant"})


def transcript_halt(root: Path, session: str, tail: int = 64 * 1024) -> tuple[float, str] | None:
    """The moment and text of the terminal halt `session`'s transcript under `root` ends its turns with; None when its
    last turn is any other, or no turn lies in the transcript's last `tail` bytes (a transcript reaches 100 MB)."""
    path = next(root.glob(f"*/{session}.jsonl"), None)
    if path is None:
        return None
    with path.open("rb") as transcript:
        transcript.seek(max(0, path.stat().st_size - tail))
        lines = transcript.read().decode(errors="replace").splitlines()[1:]
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") in TURNS:
            return _halt(entry)
    return None


def _halt(turn: dict) -> tuple[float, str] | None:
    message = turn.get("message") or {}
    texts = [part.get("text", "") for part in message.get("content") or [] if isinstance(part, dict)]
    text = "".join(texts)
    synthetic = turn.get("isApiErrorMessage") and message.get("model") == "<synthetic>"
    if not synthetic or not text.startswith(TERMINAL_HALTS):
        return None
    return datetime.fromisoformat(turn["timestamp"]).timestamp(), text


def _note(session: str, renewed: float, ttl: float) -> str:
    stamp = datetime.fromtimestamp(renewed, UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"Released: no Event from session {session} within the {ttl / 60:g}-minute claim TTL; last renewal {stamp}."


def _halt_note(session: str, at: float, text: str) -> str:
    stamp = datetime.fromtimestamp(at, UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"Released: session {session}'s transcript ends in a terminal halt at {stamp}: {text}"


def _announce(board: Board, task: str) -> None:
    """Runs the board's `released` notice for a task the sweep released, so a session starts on it; a raise is logged."""
    if board.released is None:
        return
    try:
        board.released(task)
    except Exception:
        logger.exception("claim-ttl: the released notice for %s failed", task)


def sweep(
    board: Board,
    store: EventStore,
    rows: Iterable[Mapping[str, Any]],
    *,
    ttl: float = DEFAULT_TTL,
    now: float | None = None,
    activity: Callable[[str, str], float | None] = lambda _session, _task: None,
    expiries: dict[str, float] | None = None,
    halted: Callable[[str], tuple[float, str] | None] = lambda _session: None,
    seen_running: Mapping[str, float] | None = None,
) -> list[str]:
    """Releases each working Task in `rows` whose Assignee renewed nothing for `ttl`; the ids released.

    `activity` is when a session last acted outside the Task's stream, such as a harness event of its run or its Task:
    a session working in its worktree renews its claim that way without a Task Event. `expiries`, when given, is filled with each
    held working Task's claim expiry, its renewal plus `ttl`; a Task this pass releases has none. `halted` is the moment
    and text of the terminal halt a session's harness wrote as its last turn, None when it wrote none; a claim with no
    renewal after its session's halt is released before `ttl`. `seen_running` is when a workflow was last seen running for each Task, by lowercased id: it renews that Task's claim,
    since the workflow emits nothing while it waits.
    """
    now = time.time() if now is None else now
    expiries = {} if expiries is None else expiries
    working = board.roles.working
    if board.release is None or not working:
        return []
    released = []
    for row in rows:
        session = row.get("assignee") or ""
        if not session or lane_id(row.get("state") or "") != working:
            continue
        workflow = (seen_running or {}).get(row["id"].lower())
        renewals = (last_renewal(store.read("task", row["id"]), session), activity(session, row["id"]), workflow)
        renewed = max((at for at in renewals if at is not None), default=None)
        if renewed is None:
            continue
        expiries[row["id"]] = renewed + ttl
        stale = now - renewed >= ttl
        halt = None if stale else halted(session)
        if not stale and (halt is None or halt[0] < renewed):
            continue
        note = _note(session, renewed, ttl) if halt is None else _halt_note(session, *halt)
        if board.release(row["id"], row["state"], session=session, actor=ACTOR).ok:
            events = [
                NewEvent("Released", {"session": session, "last_renewal": renewed, "ttl": ttl}, ACTOR, WRITER),
                NewEvent("CommentAdded", {"text": note}, ACTOR, WRITER),
            ]
            store.append("task", row["id"], store.head("task", row["id"]), events, at=now)
            released.append(row["id"])
            del expiries[row["id"]]
            _announce(board, row["id"])
    return released


def start(
    board: Board,
    feed: BoardFeed,
    log: EventLog,
    settings: Mapping[str, Any],
    persist: Callable[[dict[str, float]], None] = lambda _expiries: None,
) -> None:
    """Sweeps the feed's open tasks on a daemon thread every sixth of the TTL, at most every minute, for `[board]
    claim_ttl` seconds, until the feed stops. The feed holds the board's tasks whether or not a read model folds them.
    `persist` keeps each pass's expiries where the serving process reads them. `[board] workflows` is a Temporal
    server's URL: a Task that `[board] workflows_query` matches a running workflow for keeps its claim, and a pass that
    cannot read the server judges no claim."""
    from starpulse.event_log.opening import last_run_event  # noqa: PLC0415 — keeps the board's import light

    ttl = float(settings.get("claim_ttl", DEFAULT_TTL))
    store = EventStore(log.engine)
    activity = partial(last_run_event, log.engine)
    halted = partial(transcript_halt, Path(settings.get("transcripts", DEFAULT_TRANSCRIPTS)).expanduser())
    workflows = str(settings.get("workflows", ""))
    query = str(settings.get("workflows_query", DEFAULT_QUERY))
    seen: dict[str, float] = {}

    def run(stop: threading.Event) -> None:
        while not stop.wait(min(60.0, ttl / 6)):
            expiries: dict[str, float] = {}
            try:
                seen.update(dict.fromkeys(running_tasks(workflows, query) if workflows else (), time.time()))
            except (OSError, ValueError, KeyError):
                continue  # Temporal unread: a claim its workflow may be holding is not judged this pass
            sweep(
                board, store, feed.open_tasks(), ttl=ttl, activity=activity, expiries=expiries, halted=halted, seen_running=seen
            )
            persist(expiries)
            feed.serve_expiries(expiries)

    feed.spawn(run, "claim-ttl")
