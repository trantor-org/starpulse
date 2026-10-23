"""A stale Assignee is released (D6): a claim no Event by its session renewed within the claim TTL ends.

StarPulse appends `Released`, the Task moves to the State that waits on a person (Needs attention; the board's ready or
initial State when its machine declares none), and a comment names the last renewal. A released Task is never offered
to another agent as Ready, and the operator sees why a session that is alive but silent lost its claim."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from starpulse._internal.board.seam import Board
from starpulse._internal.machines.transitions import lane_id
from starpulse._internal.store import EventStore, NewEvent, StoredEvent

if TYPE_CHECKING:
    from starpulse._internal.eventlog.event_log import EventLog

__all__ = ["DEFAULT_TTL", "ACTOR", "last_renewal", "start", "sweep"]

DEFAULT_TTL = 30 * 60
"""Seconds a claim lives without an Event by its session: `[board] claim_ttl`."""
ACTOR = "starpulse"
WRITER = "claim-ttl"


def last_renewal(events: Iterable[StoredEvent], session: str) -> float | None:
    """The moment of the latest Event by `session` or naming it, as a claim's does; None when there is none."""
    carried = (event.at for event in events if session == event.actor or session in json.dumps(event.payload))
    return max(carried, default=None)


def _note(session: str, renewed: float, ttl: float) -> str:
    stamp = datetime.fromtimestamp(renewed, UTC).strftime("%Y-%m-%d %H:%M UTC")
    return f"Released: no Event from session {session} within the {ttl / 60:g}-minute claim TTL; last renewal {stamp}."


def sweep(
    board: Board,
    store: EventStore,
    rows: Iterable[Mapping[str, Any]],
    *,
    ttl: float = DEFAULT_TTL,
    now: float | None = None,
    activity: Callable[[str], float | None] = lambda _session: None,
) -> list[str]:
    """Releases each working Task in `rows` whose Assignee renewed nothing for `ttl`; the ids released.

    `activity` is when a session last acted outside the Task's stream, such as a harness event of its run: a session
    working in its worktree renews its claim that way without a Task Event.
    """
    now = time.time() if now is None else now
    working = board.roles.working
    resting = board.roles.attention or board.roles.ready or board.roles.initial
    if board.release is None or not (working and resting):
        return []
    released = []
    for row in rows:
        session = row.get("assignee") or ""
        if not session or lane_id(row.get("state") or "") != working:
            continue
        renewals = (last_renewal(store.read("task", row["id"]), session), activity(session))
        renewed = max((at for at in renewals if at is not None), default=None)
        if renewed is None or now - renewed < ttl:
            continue
        if board.release(row["id"], resting, actor=ACTOR).ok:
            events = [
                NewEvent("Released", {"session": session, "last_renewal": renewed, "ttl": ttl}, ACTOR, WRITER),
                NewEvent("CommentAdded", {"text": _note(session, renewed, ttl)}, ACTOR, WRITER),
            ]
            store.append("task", row["id"], store.head("task", row["id"]), events, at=now)
            released.append(row["id"])
    return released


def start(board: Board, log: EventLog, settings: Mapping[str, Any]) -> None:
    """Sweeps on a daemon thread every sixth of the TTL, at most every minute, for `[board] claim_ttl` seconds."""
    from starpulse._internal.eventlog.history import last_run_event  # noqa: PLC0415 — keeps the board's import light
    from starpulse._internal.readmodel.read_model import ReadModel  # noqa: PLC0415 — keeps the board's import light

    ttl = float(settings.get("claim_ttl", DEFAULT_TTL))
    store, model = EventStore(log.engine), ReadModel(log.engine)
    activity = partial(last_run_event, log.engine)

    def run() -> None:
        while True:
            time.sleep(min(60.0, ttl / 6))
            sweep(board, store, model.snapshot(), ttl=ttl, activity=activity)

    threading.Thread(target=run, name="claim-ttl", daemon=True).start()
