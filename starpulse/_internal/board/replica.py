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
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from starpulse._internal.eventlog.event_log import EventLog, Tail
from starpulse._internal.feed.board_feed import BoardFeed, retained, stream_id
from starpulse.contracts import BoardTask

if TYPE_CHECKING:
    from starpulse._internal.board.seam import Board
    from starpulse._internal.config.config import Config

logger = logging.getLogger(__name__)

REPLICA_STREAM = "board:replica"
#: The longest a reader waits for an entry the child appended; an append in this database wakes it sooner.
POLL_S = 0.5


def _read(raw: str) -> BoardTask | None:
    """A retained task entry as the task it recorded; None, with one warning, when no current key set reads it.

    Before the rename an entry held the session as `holder` and the agent profile as `assignee`."""
    try:
        fields = json.loads(raw)
        if "holder" in fields:
            fields["profile"], fields["assignee"] = fields.pop("assignee", ""), fields.pop("holder")
        return BoardTask.model_validate(fields)
    except ValueError as exc:  # ValidationError and JSONDecodeError both subclass it
        logger.warning("StarPulse: skipping an unreadable retained task in %s: %s", REPLICA_STREAM, exc)
        return None


def key(board: Board, config: Config) -> str:
    """Where the Board's checkpoint is kept: it changes with what the adapter's `state_key` names and the `[board]`
    table, so a checkpoint of another project or setting is never resumed."""
    settings = json.dumps(
        [board.state_key and board.state_key(), config.board_type, config.board], sort_keys=True, default=str
    )
    return f"{REPLICA_STREAM}@{hashlib.sha256(settings.encode()).hexdigest()[:12]}"


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
        self._cursor: str | None = None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._feed, name)

    def begin(self) -> None:
        """Restore the checkpoint and the entries published after it, before the adapter starts."""
        feed = self._feed
        feed.await_stream()
        self._cursor = feed.resume(self._log, self._key, lambda _cursor: True)
        kept = feed.source()
        self._digests = dict(kept.get("published", {}))
        self._adapter = {name: value for name, value in kept.items() if name != "published"}
        if self._cursor is None or not retained(self._log, REPLICA_STREAM)(self._cursor):
            return  # nothing published is known: the first scan publishes every task
        tail = Tail(self._log, REPLICA_STREAM, after=stream_id(self._cursor)[0])
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
        self._feed.seen(f"{entry_id}-0")

    def resume(self, *_: Any) -> str | None:
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
                if (entry := self._log.append(REPLICA_STREAM, fields)) is not None:
                    self._digests[task.id], self._dirty = digest, True
                    self._feed.seen(f"{entry}-0")
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
            entry = self._log.append(REPLICA_STREAM, {"id": task_id, "digest": "", "task": ""})
            if entry is not None:
                self._pending.discard(task_id)
                self._digests.pop(task_id, None)
                self._dirty = True
                self._feed.seen(f"{entry}-0")
        if not self._marked and self._feed.ready.is_set():
            entry = self._log.append(REPLICA_STREAM, {"ready": "1"})
            if entry is not None:
                self._marked = True
                self._feed.seen(f"{entry}-0")

    def save(self) -> None:
        """Save the Board once the child has read its source: a checkpoint is a Board a restart may resume."""
        if not self._feed.ready.is_set():
            return
        with self._lock:
            if self._dirty:
                self._feed.keep_source({**self._adapter, "published": dict(self._digests)})
                self._dirty = False
        self._feed.save()

    def keep_saved(self, stop: threading.Event, interval: float | None = None) -> None:
        interval = 60.0 if interval is None else interval
        while not stop.wait(interval):
            self.save()
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
                cursor = feed.resume(log, key, lambda _cursor: True, keep=False)
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
            feed.expect(str(last) if last else cursor)
        after = stream_id(cursor)[0] if cursor and retained(log, REPLICA_STREAM)(cursor) else None

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
                feed.seen(f"{entry.id}-0")

        Tail(log, REPLICA_STREAM, after=after, interval=interval).run(apply, stop)

    thread = threading.Thread(target=run, name="board-replica", daemon=True)
    thread.start()
    return thread


def publish(board: Board, feed: BoardFeed, group: str, log: EventLog, config: Config) -> Publisher:
    """Start the board adapter for the Board child: on a `Publisher` that has restored its checkpoint, with the
    checkpoint saved every minute on a daemon thread."""
    publisher = Publisher(feed, log, key(board, config))
    publisher.begin()
    board.start(publisher, group, log)
    threading.Thread(
        target=publisher.keep_saved,
        args=(threading.Event(),),
        name="board-state",
        daemon=True,
    ).start()
    return publisher


def read(
    board: Board,
    feed: BoardFeed,
    group: str,
    log: EventLog,
    config: Config,
    stop: threading.Event,
    *,
    local: bool,
) -> None:
    """Give a context its Board: the replica the Board child publishes, or with `local` (a worker a hub manages,
    which has no Board child) the adapter started in this process."""
    if local:
        board.start(feed, group, log)
        return
    if board.attach is not None:
        board.attach(log)
    follow(feed, log, key(board, config), stop)
