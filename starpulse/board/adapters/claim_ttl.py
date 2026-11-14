"""A stale Assignee is released (D6): a claim no Event by its session renewed within the claim TTL ends.

StarPulse appends `Released` and a comment naming the last renewal. The Task keeps its State, so a Task still in
progress is never offered to another agent as Ready; it only has no Assignee, and any session may claim it.

A released claim whose session acts again before another session holds the Task is re-attached to it.

A claim whose session process is alive is kept past the TTL: a session that ended its turn on a background wait emits
nothing, and is no less the Task's holder.

A session whose harness wrote a terminal halt as its last turn, with nothing renewing the claim after it, has stopped
for good: its claim is released at once, before the TTL, and the comment names the halt."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

import psutil

from starpulse.board.adapters.running_workflows import DEFAULT_QUERY, running_tasks
from starpulse.board.adapters.session_activity import DEFAULT_SESSIONS, DEFAULT_TRANSCRIPTS
from starpulse.board.model.seam import Board
from starpulse.event_log.deadlines import Deadlines
from starpulse.event_log.store import EventStore, NewEvent, StoredEvent
from starpulse.event_log.wake import StopEvent
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:
    from starpulse.board.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog

__all__ = ["DEFAULT_TTL", "ACTOR", "last_renewal", "live_session", "start", "sweep", "transcript_halt"]

DEFAULT_TTL = 30 * 60
"""Seconds a claim lives without an Event by its session: `[board] claim_ttl`."""
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
        start = max(0, path.stat().st_size - tail)
        transcript.seek(start)
        lines = transcript.read().decode(errors="replace").splitlines()
    lines = lines[1:] if start else lines  # a read from mid-file opens on a partial line
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") in TURNS:
            return _halt(entry)
    return None


def live_session(root: Path, session: str) -> bool:
    """Whether the process registered under `root` for `session` (its session id, bridge id or Remote Control URL) is still running."""
    for entry in root.glob("*.json") if session else ():
        try:
            data = json.loads(entry.read_text())
        except OSError, ValueError:
            continue
        if not isinstance(data, dict):
            continue
        bridge = data.get("bridgeSessionId")
        named = session in (data.get("sessionId"), bridge) or bool(bridge and session.endswith(f"/{bridge}"))
        if named and _running(data):
            return True
    return False


def _running(entry: dict) -> bool:
    """Whether the registered pid runs with the registered start time, so a reused pid is not the session."""
    try:
        started = psutil.Process(int(entry["pid"])).create_time() - psutil.boot_time()
        return round(started * os.sysconf("SC_CLK_TCK")) == int(entry["procStart"])  # `procStart` is in clock ticks
    except psutil.Error, KeyError, ValueError:
        return False


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


def _reattach(
    board: Board, store: EventStore, row: Mapping[str, Any], activity: Callable[[str, str], float | None]
) -> bool:
    """Gives an unheld working Task back to the session this sweep released it from, once that session acts again."""
    released = _released_unheld(store, row)
    if released is None:
        return False
    release, session, later = released
    acted = (last_renewal(later, session), activity(session, row["id"]))
    renewed = max((at for at in acted if at is not None), default=0.0)
    return renewed > release.at and board.writer(row["id"], row["state"], ACTOR, session).ok


def _lapsed(
    store: EventStore,
    row: Mapping[str, Any],
    now: float,
    ttl: float,
    activity: Callable[[str, str], float | None],
    alive: Callable[[str], bool],
) -> bool:
    """Whether an unheld working Task's release went a full TTL with its session neither acting nor running."""
    released = _released_unheld(store, row)
    if released is None:
        return False
    release, session, later = released
    acted = (last_renewal(later, session), activity(session, row["id"]))
    return now - release.at >= ttl and not alive(session) and all(at is None or at <= release.at for at in acted)


def _released_unheld(store: EventStore, row: Mapping[str, Any]) -> tuple[StoredEvent, str, list[StoredEvent]] | None:
    """The sweep's last release of an unheld Task, its session and the later Events by others; None when none stands.

    A later claim or move retires the release: it belonged to a visit to the working lane that has ended."""
    events = store.read("task", row["id"])
    swept = [i for i, event in enumerate(events) if event.type == "Released" and "ttl" in event.payload]
    if not swept or any(event.type in ("Claimed", "Transitioned") for event in events[swept[-1] :]):
        return None
    release = events[swept[-1]]
    later = [event for event in events[swept[-1] :] if event.at > release.at and event.actor != ACTOR]
    return release, release.payload["session"], later


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
    alive: Callable[[str], bool] = lambda _session: False,
) -> list[str]:
    """Releases each working Task in `rows` whose Assignee renewed nothing for `ttl`; the ids released.

    `activity` is when a session last acted outside the Task's stream, such as a harness event of its run or its Task:
    a session working in its worktree renews its claim that way without a Task Event. `expiries`, when given, is filled with each
    held working Task's claim expiry, its renewal plus `ttl`; a Task this pass releases has none. `halted` is the moment
    and text of the terminal halt a session's harness wrote as its last turn, None when it wrote none; a claim with no
    renewal after its session's halt is released before `ttl`. `seen_running` is when a workflow was last seen running for each Task, by lowercased id: it renews that Task's claim,
    since the workflow emits nothing while it waits. `alive` is whether a session's process runs: its claim is kept past
    `ttl`, expiring `ttl` after this pass, since the session emits nothing while it waits on a background task.
    """
    now = time.time() if now is None else now
    expiries = {} if expiries is None else expiries
    working = board.roles.working
    if board.release is None or not working:
        return []
    released = []
    for row in rows:
        session = row.get("assignee") or ""
        if lane_id(row.get("state") or "") != working:
            continue
        if not session:
            waiting = board.roles.ready or board.roles.initial
            if (
                not _reattach(board, store, row, activity)
                and waiting
                and _lapsed(store, row, now, ttl, activity, alive)
            ):
                board.writer(row["id"], waiting, ACTOR, "")
            continue
        workflow = (seen_running or {}).get(row["id"].lower())
        renewals = (last_renewal(store.read("task", row["id"]), session), activity(session, row["id"]), workflow)
        renewed = max((at for at in renewals if at is not None), default=None)
        if renewed is None:
            continue
        live = alive(session)
        expiries[row["id"]] = (now if live else renewed) + ttl
        stale = not live and now - renewed >= ttl
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


#: How long a claim whose workflow server cannot be read, or whose release failed, waits for its next judgement, in seconds.
RETRY_S = 60.0


def start(
    board: Board,
    feed: BoardFeed,
    log: EventLog,
    settings: Mapping[str, Any],
    persist: Callable[[dict[str, float]], None] = lambda _expiries: None,
) -> None:
    """Judges each held claim at its own expiry on a daemon thread, for `[board] claim_ttl` seconds, until the feed
    stops. A change to a task judges it at once and moves or cancels its deadline; the claim's renewal plus the TTL is
    when it is judged next, so a held claim costs no poll. The feed holds the board's tasks whether or not a read model
    folds them. `persist` keeps the held claims' expiries where the serving process reads them. `[board] workflows` is
    a Temporal server's URL: a Task that `[board] workflows_query` matches a running workflow for keeps its claim, and
    a judgement that cannot read the server releases no claim."""
    from starpulse.event_log.opening import last_run_event  # noqa: PLC0415 — keeps the board's import light

    ttl = float(settings.get("claim_ttl", DEFAULT_TTL))
    if ttl <= 0:
        return  # a rehearsal runs on the live board's files and must release none of its claims
    store = EventStore(log.engine)
    activity = partial(last_run_event, log.engine)
    halted = partial(transcript_halt, Path(settings.get("transcripts", DEFAULT_TRANSCRIPTS)).expanduser())
    alive = partial(live_session, Path(settings.get("sessions", DEFAULT_SESSIONS)).expanduser())
    workflows = str(settings.get("workflows", ""))
    query = str(settings.get("workflows_query", DEFAULT_QUERY))
    seen: dict[str, float] = {}
    held: dict[str, float] = {}
    judging = threading.Lock()
    read = [
        not workflows
    ]  # whether the workflow server's last answer is held: a judgement without one releases nothing

    def judge(tasks: Iterable[str], *, reread: bool) -> tuple[int, list[str]]:
        """Judge `tasks` and arm each one's next deadline; `reread` asks the workflow server which tasks it runs. The
        working tasks judged and the ids released."""
        with judging:
            ids = set(tasks)
            rows = feed.open_tasks() if len(ids) > 1 else [row for task in ids if (row := feed.task(task, lean=True))]
            working = [row for row in rows if row["id"] in ids and lane_id(row["state"]) == board.roles.working]
            if working and (reread or not read[0]):
                try:
                    seen.update(dict.fromkeys(running_tasks(workflows, query) if workflows else (), time.time()))
                    read[0] = True
                except OSError, ValueError, KeyError:
                    read[0] = False
                    for row in working:  # Temporal unread: a claim its workflow may be holding is not judged now
                        deadlines.arm(row["id"], time.time() + RETRY_S)
                    return len(working), []
            expiries: dict[str, float] = {}
            released = sweep(
                board,
                store,
                working,
                ttl=ttl,
                activity=activity,
                expiries=expiries,
                halted=halted,
                seen_running=seen,
                alive=alive,
            )
            for task in ids:
                held.pop(task, None)
                deadlines.cancel(task)
            held.update(expiries)
            now = time.time()
            for task, at in expiries.items():
                deadlines.arm(
                    task, at if at > now else now + RETRY_S
                )  # an expiry a failed release left is retried later
            for task in released:
                deadlines.arm(task, now + ttl)  # the released task returns to waiting once its session stays gone a TTL
            for row in working:  # a later judgement of that released task keeps the deadline its release armed
                standing = None if row.get("assignee") else _released_unheld(store, row)
                if standing:
                    lapses = standing[0].at + ttl
                    deadlines.arm(row["id"], lapses if lapses > now else now + ttl)
            persist(dict(held))
            feed.serve_expiries(dict(held))
            return len(working), released

    deadlines = Deadlines(lambda task: judge([task], reread=True))

    def reconcile() -> tuple[int, int]:
        """The sweeper's `claims` pass: judge every open task again; a claim it releases outlived its deadline unseen."""
        sampled, released = judge([row["id"] for row in feed.open_tasks()], reread=True)
        return sampled, len(released)

    feed.reconcilers["claims"] = reconcile

    def run(stop: StopEvent) -> None:
        feed.wait_replayed()
        changes = feed.follow_changes()
        deadlines.start(stop, thread_name="claim-ttl-deadlines")
        judge([row["id"] for row in feed.open_tasks()], reread=True)

        def stopped() -> None:
            changes.put(("stop", {}))

        stop.listen(stopped)
        try:
            while not stop.is_set():
                kind, data = changes.get()
                if kind in ("task", "move") and data.get("id"):
                    judge([data["id"]], reread=False)
        finally:
            stop.unlisten(stopped)

    feed.spawn(run, "claim-ttl")
