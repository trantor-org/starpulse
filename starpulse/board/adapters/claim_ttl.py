"""A stale Assignee is released (D6): a claim no Event by its session renewed within the claim TTL ends.

StarPulse appends `Released` and a comment naming the last renewal. The Task keeps its State, so a Task still in
progress is never offered to another agent as Ready; it only has no Assignee, and any session may claim it."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from functools import partial
from typing import TYPE_CHECKING, Any

from starpulse.board.model.seam import Board
from starpulse.event_log.store import EventStore, NewEvent, StoredEvent
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:
    from starpulse.board.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog

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
    expiries: dict[str, float] | None = None,
) -> list[str]:
    """Releases each working Task in `rows` whose Assignee renewed nothing for `ttl`; the ids released.

    `activity` is when a session last acted outside the Task's stream, such as a harness event of its run: a session
    working in its worktree renews its claim that way without a Task Event. `expiries`, when given, is filled with each
    held working Task's claim expiry, its renewal plus `ttl`; a Task this pass releases has none.
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
        renewals = (last_renewal(store.read("task", row["id"]), session), activity(session))
        renewed = max((at for at in renewals if at is not None), default=None)
        if renewed is None:
            continue
        expiries[row["id"]] = renewed + ttl
        if now - renewed < ttl:
            continue
        if board.release(row["id"], row["state"], session=session, actor=ACTOR).ok:
            events = [
                NewEvent("Released", {"session": session, "last_renewal": renewed, "ttl": ttl}, ACTOR, WRITER),
                NewEvent("CommentAdded", {"text": _note(session, renewed, ttl)}, ACTOR, WRITER),
            ]
            store.append("task", row["id"], store.head("task", row["id"]), events, at=now)
            released.append(row["id"])
            del expiries[row["id"]]
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
    `persist` keeps each pass's expiries where the serving process reads them."""
    from starpulse.event_log.opening import last_run_event  # noqa: PLC0415 — keeps the board's import light

    ttl = float(settings.get("claim_ttl", DEFAULT_TTL))
    store = EventStore(log.engine)
    activity = partial(last_run_event, log.engine)

    def run(stop: threading.Event) -> None:
        while not stop.wait(min(60.0, ttl / 6)):
            expiries: dict[str, float] = {}
            sweep(board, store, feed.open_tasks(), ttl=ttl, activity=activity, expiries=expiries)
            persist(expiries)
            feed.serve_expiries(expiries)

    feed.spawn(run, "claim-ttl")
