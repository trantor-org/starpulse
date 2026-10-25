"""The Board as one process places it and every other reads it: a replica in the event log.

The Board child (`starpulse worker board`) is the only process that runs the board adapter's watchers. It hands the
adapter a `Publisher` in place of its feed: each task the adapter reports that differs from what was last published is
appended to the `board:replica` stream, and the Board is checkpointed under `key` (`BoardFeed.save`). `serve` and the
other workers do not run the adapter: `follow` restores that checkpoint and tails the stream, so a task reaches their
feed within `POLL_S` of the child placing it. A restart of the child resumes its checkpoint and the entries after it, so
the reader's view is never emptied and the unchanged tasks of its first scan publish nothing.

A stream entry is `{id, digest, task}`: the task as the adapter reported it (stamped with when the child first saw it,
so every process dates a lane change alike), or an empty `task` for a retraction. `{ready: 1}` marks the child's first
scan done: a reader is not ready before it, as the Board is not read before then.

The stream is a changelog keyed by task, so the child compacts it (`compact`) hourly: an entry a later one of the same
task supersedes, and every ready marker but the newest, is deleted. What is left is the latest entry of each task the
retention still holds, so a reader that replays the stream, with or without a checkpoint, ends on the same Board.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, select

from starpulse.board.board_feed import BoardFeed, retained
from starpulse.contracts import BoardTask
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import events

if TYPE_CHECKING:
    from starpulse.board.model.seam import Board
    from starpulse._internal.config.config import Config

logger = logging.getLogger(__name__)

REPLICA_STREAM = "board:replica"
#: The longest a reader waits for an entry the child appended; an append in this database wakes it sooner.
POLL_S = 0.5
#: How often the child compacts the stream: each changed task appends an entry, so without it the stream holds every
#: lane move of the retention, and a reader with no checkpoint replays them all before it is ready.
COMPACT_S = 3600.0
_COMPACT_BATCH = 5000


def _read(raw: str) -> BoardTask | None:
    """A retained task entry as the task it recorded; None, with one warning, when no current key set reads it."""
    try:
        return BoardTask.model_validate(json.loads(raw))
    except ValueError as exc:  # ValidationError and JSONDecodeError both subclass it
        logger.warning("StarPulse: skipping an unreadable retained task in %s: %s", REPLICA_STREAM, exc)
        return None


def key(board: Board, config: Config) -> str:
    """Where the Board's checkpoint is kept: it changes with what the adapter's `state_key` names and the board type,
    so a checkpoint of another project is never resumed. The `[board]` table is not in it: an edit to a command or a
    rule there leaves the saved Board in place instead of replaying every task."""
    settings = json.dumps([board.state_key and board.state_key(), config.board_type], sort_keys=True)
    return f"{REPLICA_STREAM}@{hashlib.sha256(settings.encode()).hexdigest()[:12]}"


def compact(log: EventLog, *, batch: int = _COMPACT_BATCH) -> int:
    """Delete the stream's superseded entries and return how many; raises when the database does.

    An entry is superseded when a later entry names the same task (a put or a retraction), and a ready marker when a
    later one is kept. The newest entry of each task stays, so a reader that replays from any cursor ends on the same
    Board; a retraction stays too, as a reader's checkpoint may still hold the task. The log's oldest row is never
    deleted, whatever its stream: the retention alone moves it, so no reader's cursor reads as pruned (`retained`) and
    no gap is recorded. Each batch is its own transaction, so an append waits on one batch at most."""
    latest = (
        select(func.max(events.c.id))
        .where(events.c.stream == REPLICA_STREAM)
        .group_by(func.json_extract(events.c.fields, "$.id"))  # ready markers name no task: one group, NULL
    )
    oldest = select(func.min(events.c.id)).scalar_subquery()
    deleted = 0
    while True:
        with log.engine.begin() as db:
            ids = (
                db.execute(
                    select(events.c.id)
                    .where(events.c.stream == REPLICA_STREAM, events.c.id.not_in(latest), events.c.id != oldest)
                    .order_by(events.c.id)
                    .limit(batch)
                )
                .scalars()
                .all()
            )
            if not ids:
                return deleted
            db.execute(delete(events).where(events.c.id.in_(ids)))
        deleted += len(ids)


def _digest(task: BoardTask) -> str:
    return hashlib.sha256(task.model_dump_json().encode()).hexdigest()[:16]


class Publisher:
    """The feed of the Board child, as the board adapter sees it: it places each task in the child's `BoardFeed` and
    publishes the ones that changed to the replica stream. Everything else is the feed's.

    What was published is kept as a digest per task in the checkpoint (beside the adapter's own source), so a restarted
    child publishes only what changed while it was down. A publish the log refused is made by the next put of the task
    and a retraction by the next call that reaches the log.
    """

    def __init__(self, feed: BoardFeed, log: EventLog, key: str, *, clock=time.time) -> None:
        self._feed = feed
        self._log = log
        self._key = key
        self._clock = clock
        self._lock = threading.RLock()
        self._digests: dict[str, str] = {}
        self._adapter: dict[str, Any] = {}
        self._pending: set[str] = set()
        self._marked = False
        self._dirty = False
        self._cursor: int | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._feed, name)

    def begin(self) -> None:
        """Restore the checkpoint and the entries published after it, before the adapter starts."""
        feed = self._feed
        feed.await_stream()
        self._cursor = feed.resume(self._log.checkpoints, self._key, lambda _cursor: True)
        kept = feed.source()
        self._digests = dict(kept.get("published", {}))
        self._adapter = {name: value for name, value in kept.items() if name != "published"}
        if self._cursor is None or not retained(self._log, REPLICA_STREAM)(self._cursor):
            return  # nothing published is known: the first scan publishes every task
        tail = self._log.tail(REPLICA_STREAM, after=self._cursor)
        while entries := tail.poll():
            for entry in entries:
                self._catch_up(entry.id, entry.fields)

    def _catch_up(self, entry_id: int, fields: dict) -> None:
        if task := fields.get("task"):
            self._feed.put(BoardTask.model_validate_json(task))
            self._digests[fields["id"]] = fields["digest"]
        elif "id" in fields:
            self._feed.retract(fields["id"])
            self._digests.pop(fields["id"], None)
        self._feed.seen(str(entry_id))

    def resume(self, *_: Any) -> int | None:
        """The cursor `begin` restored: the adapter's own start resumes nothing more."""
        return self._cursor

    def source(self) -> dict:
        return self._adapter

    def keep_source(self, source: dict) -> None:
        with self._lock:
            self._adapter, self._dirty = source, True
            self._flush()

    def put(self, task: BoardTask) -> None:
        stamped = task if task.observed_at is not None else task.model_copy(update={"observed_at": self._clock()})
        digest = _digest(task)
        with self._lock:
            self._pending.discard(task.id)  # a task retracted and back before the log took it is still published
            self._feed.put(stamped)
            if self._digests.get(task.id) != digest:
                fields = {
                    "id": task.id,
                    "digest": digest,
                    "task": stamped.model_dump_json(),
                }
                if (entry := self._log._append(REPLICA_STREAM, fields)) is not None:
                    self._digests[task.id], self._dirty = digest, True
                    self._feed.seen(str(entry))
            self._flush()

    def retract(self, task_id: str) -> None:
        with self._lock:
            self._feed.retract(task_id)
            if task_id in self._digests:
                self._pending.add(task_id)
            self._flush()

    def expect(self, last_id: str) -> None:
        self._feed.expect(last_id)
        with self._lock:
            self._flush()

    def _flush(self) -> None:
        """Append the retractions and the ready marker the log has not taken yet; the caller holds the lock."""
        for task_id in sorted(self._pending):
            entry = self._log._append(REPLICA_STREAM, {"id": task_id, "digest": "", "task": ""})
            if entry is not None:
                self._pending.discard(task_id)
                self._digests.pop(task_id, None)
                self._dirty = True
                self._feed.seen(str(entry))
        if not self._marked and self._feed.ready.is_set():
            entry = self._log._append(REPLICA_STREAM, {"ready": "1"})
            if entry is not None:
                self._marked = True
                self._feed.seen(str(entry))

    def save(self) -> None:
        """Save the Board once the child has read its source: a checkpoint is a Board a restart may resume."""
        if not self._feed.ready.is_set():
            return
        with self._lock:
            if self._dirty:
                self._feed.keep_source({**self._adapter, "published": dict(self._digests)})
                self._dirty = False
        self._feed.save()

    def keep_saved(
        self, stop: threading.Event, interval: float | None = None, *, compact_every: float = COMPACT_S
    ) -> None:
        """Save the Board every `interval` until `stop`, and compact the stream after the first save and then every
        `compact_every`. A compaction that fails is logged and the next one retries."""
        interval = 60.0 if interval is None else interval
        due = 0.0
        while not stop.wait(interval):
            self.save()
            if (now := time.monotonic()) >= due:
                due = now + compact_every
                try:
                    if deleted := compact(self._log):
                        logger.info("StarPulse: compacted %d superseded entries of %s", deleted, REPLICA_STREAM)
                except Exception as exc:  # the database is unreachable or locked; the next compaction retries
                    logger.warning("StarPulse: cannot compact %s, retrying later: %s", REPLICA_STREAM, exc)
        self.save()


def follow(
    feed: BoardFeed,
    log: EventLog,
    key: str,
    stop: threading.Event,
    *,
    interval: float = POLL_S,
) -> threading.Thread:
    """Read the Board the child publishes into `feed` on a daemon thread and return it, until `stop`.

    The feed restores the child's last checkpoint (and never writes it) and reads the stream from the cursor it
    reflects, or all it retains where that is gone. It turns ready once it has read what the stream held when it
    started, and not before the child has read its Board: a checkpoint says it had, else the ready marker does.
    While the database cannot be reached the start retries every `interval`.
    """
    feed.await_stream()

    def run() -> None:
        while not stop.is_set():
            try:
                cursor = feed.resume(log.checkpoints, key, lambda _cursor: True, keep=False)
                last = log.last(REPLICA_STREAM)
                break
            except Exception as exc:  # the database is unreachable; the next attempt retries
                logger.warning(
                    "StarPulse: cannot reach the event log for %s, retrying: %s",
                    REPLICA_STREAM,
                    exc,
                )
                stop.wait(interval)
        else:
            return
        if cursor:
            feed.expect(str(last or cursor))
        after = cursor if cursor and retained(log, REPLICA_STREAM)(cursor) else None

        def apply(entry) -> None:
            try:
                if "ready" in entry.fields:
                    feed.expect(str(log.last(REPLICA_STREAM) or entry.id))
                elif task := entry.fields.get("task"):
                    if placed := _read(task):
                        feed.put(placed)
                else:
                    feed.retract(entry.fields["id"])
            finally:
                feed.seen(str(entry.id))

        log.tail(REPLICA_STREAM, after=after, interval=interval).run(apply, stop)

    thread = threading.Thread(target=run, name="board-replica", daemon=True)
    thread.start()
    return thread


def publish(board: Board, feed: BoardFeed, group: str, log: EventLog, config: Config) -> Publisher:
    """Start the board adapter for the Board child: on a `Publisher` that has restored its checkpoint, with the
    checkpoint saved every minute on a daemon thread."""
    publisher = Publisher(feed, log, key(board, config))
    publisher.begin()
    board.start(publisher, group, log)
    feed.spawn(publisher.keep_saved, "board-state")
    return publisher


def read(
    board: Board,
    feed: BoardFeed,
    group: str,
    log: EventLog,
    config: Config,
    stop: threading.Event,
) -> None:
    """Give a context its Board: the replica the Board child publishes."""
    if board.attach is not None:
        board.attach(log)
    follow(feed, log, key(board, config), stop)
