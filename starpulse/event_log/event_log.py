"""StarPulse's event log: an append-only table in the history store that producers write and readers tail.

Every producer on the host appends one row (`EventLog.publish`), which never raises, so reporting an event never
fails the work that caused it. Every reader keeps its own cursor, the `id` of the last row it passed, and
reads `id > cursor` (`Tail`); there are no consumer groups. A tail without a cursor replays the retained log, one
given a cursor resumes after it, and `EventLog.prune` drops rows older than a retention, which the sweeper runs each pass
(`runtime.assembly.prune_steps`) after writing each row to its UTC day's gzip JSONL archive file. A cursor below the oldest retained row means rows were pruned unread, and the reader resumes at the oldest retained row.

The database is the history store's: SQLite by default (in WAL mode, so processes on the host append while the
server reads) or the file a `database_url` names. Delivery is at-least-once within retention, so a handler
treats `event_id` as its idempotency key. A reader holds no connection, hence no read transaction, between reads: a held
SQLite read transaction would stop WAL checkpoints and grow the `-wal` file without bound.

A tail sleeps until something wakes it, never on a timer. An append in this process wakes every waiting tail at once,
and on SQLite so does a commit by another process: one watcher thread per log blocks on a file watch of the store
(`event_log.watch`: inotify or kqueue) and rereads `PRAGMA data_version` when the watch fires. A `StopEvent` ends the
wait too (`EventLog.wait_for_append`). A platform with no file watch falls back to waking every `FALLBACK_WAKE_S`, the
sweeper's interval, and logs once that it has none.

`data_version` moves on every commit, a follower's own checkpoint write included, so `run_on_wake` takes a `signal`: a
statement for what its step reads, which the watcher reads after each commit and shares among the followers of one
statement. The follower wakes only when that value moves. A follower of a table no event announces names that table, so
a missing wake stalls the follower, never the commit. `EventLog.wakes` counts each follower's wakes and how many moved
the events head; `keep_wakes` keeps them for the Page API's `/metrics`.
"""

import gzip
import json
import logging
import os
import selectors
import sqlite3
import threading
import time
import uuid
import weakref
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, Engine, String, bindparam, create_engine, delete, event, func, literal, select, type_coerce, update
from sqlalchemy.dialects import sqlite
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.follower_wakes import STATE as WAKES_STATE, samples as wake_samples
from starpulse.event_log.migrate import require_migrated
from starpulse.event_log.signals import Signals, read_value
from starpulse.event_log.tables import events, settings, worker_state
from starpulse.event_log.wake import FALLBACK_WAKE_S, RETRY_DELAY, StopEvent
from starpulse.event_log.watch import open_watch

__all__ = ["Entry", "EventLog", "Tail", "WAL_SIZE_LIMIT", "bound_wal", "store_engine"]

logger = logging.getLogger(__name__)

#: Set once the process has logged that it has no file watch, so the line appears once however many logs it opens.
_NO_WATCH_LOGGED = threading.Event()

#: How long SQLite waits on another process's write lock before an append gives up and fails open, in seconds. It
#: outlasts the multi-second disk stalls of the host's weekly snapshot backup, which held writes past a 5 s wait.
_SQLITE_BUSY_TIMEOUT = 30.0

#: The most the -wal file keeps after a checkpoint resets it. SQLite keeps the file at its high-water mark otherwise,
#: so one burst left a 462 MB file holding a few hundred frames. Only the connection whose commit restarts the log
#: truncates it, so every connection to the database sets this, not the history store's alone: an unbounded writer
#: restarting the log left a 4.4 GB file holding 1.5 GB of frames (21.6 GB at its worst, 2026-11-18).
WAL_SIZE_LIMIT = 64 * 1024 * 1024

#: How long a checkpoint that truncates an oversized -wal file waits on readers and the write lock, in milliseconds. It
#: holds every writer off while it waits, so it gives up long before an append's own `_SQLITE_BUSY_TIMEOUT`.
_WAL_TRUNCATE_WAIT_MS = 1000

#: How long, in seconds, a truncate that found a reader still on the log leaves the next one.
_WAL_TRUNCATE_RETRY_S = 5.0

#: How many times the log tries to switch its SQLite database to WAL, which fails at once, without waiting on the busy
#: timeout, while another connection opens or closes the database.
_PRAGMA_ATTEMPTS = 20

#: How many idle connections a file database's pool keeps. Every append wakes every tail and `follow_state` thread
#: (~66 in the contexts worker), each checking out a connection at once; a pool smaller than that burst closes the
#: extra connections as they come back and opens them again on the next append, which cost 8-10 % of the worker's CPU
#: in the 2026-11-09 profile. An idle connection holds about 250 KB.
_POOL_SIZE = 64
#: How many connections a burst past `_POOL_SIZE` may open beyond it; those are closed again as they come back.
_POOL_OVERFLOW = 16

#: How many rows a prune archives and deletes at a time, so a long backlog is never held in memory at once.
_PRUNE_BATCH = 1000

#: The streams the prune keeps whatever their age: `machine:events` is refolded into every machine's task placement on a
#: read-model rebuild.
RETAINED_STREAMS = ("machine:events",)
# Built once: a statement made per poll recompiles its lazy attributes every time, which dominated the server's CPU
# at ~45 live sessions (every commit wakes every tail).
# SQLite answers a lone min or max from the primary key.
_HEAD = select(func.max(events.c.id))
_WORKER_VERSION = select(worker_state.c.version).where(worker_state.c.name == bindparam("name"))


class Entry(NamedTuple):
    """One row of the log: `id` is the cursor to resume after."""

    id: int
    stream: str
    event_id: str
    fields: dict[str, Any]
    at: float


def _watch_commits(
    log: weakref.ref[EventLog], database: str, fallback: float, baseline: threading.Event, ended: int
) -> None:
    """Wake waiters whenever another connection commits to `database`, setting `baseline` after the first read.
    The thread blocks on a file watch of the store (and on `ended`, the read end of the pipe the log's finalizer
    closes), then rereads `PRAGMA data_version`, which changes only for commits made through other connections. The
    connection holds no transaction, so it never stalls a checkpoint. Without a file watch, or after a failed read, it
    waits `fallback` seconds instead and says once that it has no watch.

    The thread holds the log only through `log`: a log its owner drops closes the pipe and ends this thread at once;
    a bound method as the target would keep the log alive for the life of the process."""
    watch = open_watch(database)
    selector = selectors.DefaultSelector()
    selector.register(ended, selectors.EVENT_READ)
    if watch is None:
        if not _NO_WATCH_LOGGED.is_set():
            _NO_WATCH_LOGGED.set()
            logger.warning(
                "EventLog: no file watch on this platform; waking on commits by other processes every %ss", fallback
            )
    else:
        selector.register(watch.fileno(), selectors.EVENT_READ)
    version = None
    connection = None
    healthy = True
    woken = False
    while (owner := log()) is not None:
        try:
            if connection is None:
                connection = sqlite3.connect(database, timeout=_SQLITE_BUSY_TIMEOUT, isolation_level=None)
            if woken or not healthy:
                # The watch fires on the write to the `-wal` file, before the writer publishes the commit in the shared
                # index (a memory-mapped write the watch cannot see): taking the write lock waits for that commit to end.
                # A baseline read after a failed check waits too, or it predates a commit the watch already announced.
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("ROLLBACK")
            current = connection.execute("PRAGMA data_version").fetchone()[0]
            # after a failed check a commit may have landed before this baseline read: wake the readers once
            if not healthy or version is None or current != version:
                _read_head(connection, owner)
                if (signals := owner._signals) is not None:
                    signals.probe(connection)
            if not healthy or (version is not None and current != version):
                owner._wake()
            version, healthy = current, True
        except sqlite3.Error as exc:  # the file is locked or gone: wake the readers to look, and look again later
            logger.debug("EventLog: data_version check failed: %s", exc)
            if healthy:
                owner._forget_head()
                if (signals := owner._signals) is not None:
                    signals.reset()
                owner._wake()
            connection, version, healthy = None, None, False
        del owner
        baseline.set()
        blocked = selector.select(None if watch is not None and healthy else fallback)
        if any(key.fd == ended for key, _ in blocked):
            break
        woken = watch is not None
        if watch is not None:
            watch.drain()
    if connection is not None:
        connection.close()
    selector.close()
    os.close(ended)
    if watch is not None:
        watch.close()


def _read_head(connection: sqlite3.Connection, log: EventLog) -> None:
    """Keep the events head on `log`, one read for every follower; a store without the table yet leaves it unknown."""
    try:
        log._observe_head(connection.execute(f"SELECT max(id) FROM {events.name}").fetchone()[0] or 0)
    except sqlite3.OperationalError:
        log._forget_head()


def _sqlite_wal(dbapi_connection: Any) -> None:
    """Switch the database to WAL. The mode is kept in the database file, so the log does it once, not per connection."""
    cursor = dbapi_connection.cursor()
    for attempt in range(_PRAGMA_ATTEMPTS):
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            break
        except sqlite3.OperationalError:
            if attempt == _PRAGMA_ATTEMPTS - 1:
                raise
            # adr-exempt: handshake
            time.sleep(0.05)
    cursor.close()


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    """The pragmas each connection keeps for itself: the database file keeps none of `synchronous`, the WAL limit and `foreign_keys`."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute(f"PRAGMA journal_size_limit={WAL_SIZE_LIMIT}")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def bound_wal(engine: Engine, stop: threading.Event) -> None:
    """Start the thread that truncates the engine's database's -wal file whenever it is past `WAL_SIZE_LIMIT`, until
    `stop` is set. One process runs it (the api worker's); a connection checkin runs no checkpoint.

    `journal_size_limit` shrinks the file only when a commit restarts the log, and SQLite restarts it only at a moment
    no reader is on any of its frames. Readers that always overlap (the contexts worker's) leave no such
    moment, so the file grows without bound while every checkpoint backfills it. A `TRUNCATE` checkpoint holds writers off
    until the readers on old frames end, and readers that begin meanwhile read the backfilled database file, so it
    ends the overlap; it gives up after `_WAL_TRUNCATE_WAIT_MS` and is not tried again for `_WAL_TRUNCATE_RETRY_S`.
    """
    database = engine.url.database
    if database in (None, "", ":memory:"):
        return
    wal = Path(f"{database}-wal")
    unpooled = unpooled_engine(engine)

    def truncate() -> None:
        while not stop.wait(_WAL_TRUNCATE_RETRY_S):
            try:
                if wal.stat().st_size > WAL_SIZE_LIMIT:
                    with unpooled.connect() as db:
                        raw = db.connection.dbapi_connection
                        raw.execute(f"PRAGMA busy_timeout={_WAL_TRUNCATE_WAIT_MS}")
                        raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except (OSError, SQLAlchemyError, sqlite3.OperationalError):  # no -wal file yet, or the database is busy: next round
                pass

    threading.Thread(target=truncate, name="wal-truncate", daemon=True).start()


#: `keep_wakes` keeps the counts again each time the wakes of this process reach another multiple, never on a timer.
PUBLISH_EVERY = 256


class Wakes:
    """The wakes of each follower thread, by whether the events head had moved since its last wake. Every log builds
    one, so it lives with the log: in `follower_wakes` it would tie that metric module to every test that opens a log."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counts: dict[tuple[str, bool], int] = {}
        self._total = 0

    def count(self, follower: str, head_moved: bool) -> bool:
        """Count one wake; whether the total has reached another `PUBLISH_EVERY`."""
        with self._lock:
            self._counts[follower, head_moved] = self._counts.get((follower, head_moved), 0) + 1
            self._total += 1
            return self._total % PUBLISH_EVERY == 0

    def counts(self) -> dict[tuple[str, bool], int]:
        with self._lock:
            return dict(self._counts)


class EventLog:
    """The log in one database. Opening it is lazy and retried, so a producer that starts before its database is
    reachable appends once it is."""

    def __init__(self, url: str, *, engine: Engine | None = None, fallback_interval: float = FALLBACK_WAKE_S) -> None:
        self.url = url
        self._fallback_interval = fallback_interval
        self._engine = engine
        self._unpooled: Engine | None = None
        self._ready = False
        self._lock = threading.Lock()
        self._appended = threading.Condition()
        self._appends = 0
        self._head: int | None = None  # the newest event id seen (0 for none), None while unknown
        self._head_moved = threading.Condition()
        self._signals: Signals | None = None  # built by the first follower of a signal (`_signal_watch`)
        #: How often each follower woke, and whether the events head had moved.
        self.wakes = Wakes()
        self._wakes_child: str | None = None
        self._watching = False
        self._unwatch: Callable[[], object] | None = None

    def close(self) -> None:
        """Release the database connections the log holds and end its commit watch; the log reopens, and watches
        again, on its next use."""
        with self._lock:
            if self._engine is not None:
                self._engine.dispose()
            if self._unwatch is not None:
                self._unwatch()
                self._unwatch, self._watching = None, False

    @property
    def engine(self) -> Engine:
        """The engine with the log's tables created; raises while the database cannot be opened."""
        with self._lock:
            if not self._ready:
                if self._engine is None:
                    self._engine = store_engine(self.url)
                with self._engine.connect() as db:
                    _sqlite_wal(db.connection.dbapi_connection)
                require_migrated(self._engine)
                self._ready = True
            assert self._engine is not None
            return self._engine

    @property
    def checkpoints(self) -> Checkpoints:
        """The table of how far each reader of this database got."""
        return Checkpoints(self.engine)

    def setting(self, key: str) -> Any | None:
        """The value kept under `key`, or None when no row holds one. Raises on a database error, so a caller that
        must fail closed decides what an unreadable setting means."""
        with self.engine.connect() as db:
            return db.execute(select(settings.c.value).where(settings.c.key == key)).scalar()

    def set_setting(self, key: str, value: Any, *, updated_at: float | None = None) -> None:
        """Keep `value` under `key`, replacing what was there, stamped now or at `updated_at`. Raises on a database
        error."""
        engine = self.engine
        with self._lock:
            if self._unpooled is None:
                self._unpooled = unpooled_engine(engine)  # a checkpoint is megabytes, so no pooled connection keeps one
            writer = self._unpooled
        now = time.time() if updated_at is None else updated_at
        upsert = sqlite.insert(settings).values(key=key, value=value, updated_at=now)
        with writer.begin() as db:
            db.execute(
                upsert.on_conflict_do_update(index_elements=[settings.c.key], set_={"value": value, "updated_at": now})
            )

    def setting_updated_at(self, key: str) -> float | None:
        """The epoch second `key` was last written, or None when no row holds it. Raises on a database error."""
        with self.engine.connect() as db:
            return db.execute(select(settings.c.updated_at).where(settings.c.key == key)).scalar()

    def delete_setting(self, key: str) -> None:
        """Drop `key`'s row, so the setting reads as its default again. Raises on a database error."""
        with self.engine.begin() as db:
            db.execute(delete(settings).where(settings.c.key == key))

    def state(self, name: str) -> tuple[int, Any | None]:
        """The `(version, state)` a worker kept under `name`, version 0 and no state before it kept any. Raises on a
        database error."""
        with self.engine.connect() as db:
            row = db.execute(select(worker_state.c.version, worker_state.c.state).where(worker_state.c.name == name))
            found = row.first()
        return (0, None) if found is None else (found.version, found.state)

    def put_state(self, name: str, state: Any) -> None:
        """Keep `state` under `name`, replacing what was there, and raise its version. Raises on a database error."""
        self._upsert_state(name, state, state)

    def put_state_entry(self, name: str, entry: str, value: Any) -> None:
        """Keep `value` under `entry` of the object kept under `name`, leaving its other entries as they are, in one
        statement so workers in separate processes never drop each other's entries. Raises on a database error."""
        merged = func.json_set(worker_state.c.state, f'$."{entry}"', func.json(json.dumps(value)))
        self._upsert_state(name, {entry: value}, merged)

    def drop_state_entries(self, name: str, keep: Collection[str]) -> list[str]:
        """Drop the entries of the object kept under `name` that `keep` does not name, and return the ones dropped. Raises
        on a database error."""
        _, body = self.state(name)
        gone = [entry for entry in body if entry not in keep] if isinstance(body, dict) else []
        if gone:
            removed = func.json_remove(worker_state.c.state, *(f'$."{entry}"' for entry in gone))
            with self.engine.begin() as db:
                db.execute(
                    update(worker_state)
                    .where(worker_state.c.name == name)
                    .values(state=removed, version=worker_state.c.version + 1, updated_at=time.time())
                )
            self._wake()
        return gone

    def _upsert_state(self, name: str, first: Any, replacement: Any) -> None:
        now = time.time()
        upsert = sqlite.insert(worker_state).values(name=name, state=first, version=1, updated_at=now)
        new = replacement if isinstance(replacement, ColumnElement) else literal(replacement, worker_state.c.state.type)
        with self.engine.begin() as db:
            written = db.execute(
                upsert.on_conflict_do_update(
                    index_elements=[worker_state.c.name],
                    set_={"state": replacement, "version": worker_state.c.version + 1, "updated_at": now},
                    where=func.json(worker_state.c.state).is_not(func.json(new)),
                )
            ).rowcount
        if written:  # a write that changes nothing raises no version and wakes no follower
            self._wake()

    def delete_state(self, name: str) -> None:
        """Drop `name`'s row, so it reads as unkept again. Raises on a database error."""
        with self.engine.begin() as db:
            db.execute(delete(worker_state).where(worker_state.c.name == name))
        self._wake()

    def follow_state(
        self, name: str, apply: Callable[[], None], stop: StopEvent, *, thread_name: str, catch_up: bool = False
    ) -> threading.Thread:
        """Call `apply` each time the state under `name` is written after this call, on a thread until `stop`; with
        `catch_up`, once at the start as well. An `apply` that raises is logged and called again after `RETRY_DELAY`,
        so one failure never ends the thread. The thread rereads the version when the log is appended to, here or by
        another process, and sleeps otherwise."""
        seen = -1 if catch_up else self.version_or(name, 0)

        def step() -> None:
            nonlocal seen
            if (version := self.version(name)) != seen:
                apply()
                seen = version  # only a success moves it, so a failed `apply` runs again

        def run() -> None:
            self.run_on_wake(stop, step, f"event log: following {name} failed; retrying")

        thread = threading.Thread(target=run, name=thread_name, daemon=True)
        thread.start()
        return thread

    def version(self, name: str) -> int:
        """The version of the state kept under `name`, 0 when none is kept; raises when the store cannot be read."""
        with self.engine.connect() as db:
            return db.execute(_WORKER_VERSION, {"name": name}).scalar() or 0

    def version_or(self, name: str, default: int) -> int:
        try:
            return self.version(name)
        except Exception:  # an unreadable store changes nothing, and the next look tries again
            logger.warning("EventLog: reading the version of %s failed", name, exc_info=True)
            return default

    def publish(self, stream: str, fields: Mapping[str, Any], *, event_id: str | None = None) -> int | None:
        """Append one event and return its cursor, or None when it was not appended; never raises.

        `event_id` is the caller's, else the fields', else minted; a row with that `event_id` already in the log
        is not appended again and its cursor is returned. Encoding sits inside the `try`: fields JSON refuses must
        fail open like an outage.
        """
        try:
            engine = self.engine
            key = event_id or str(fields.get("event_id") or "") or uuid.uuid4().hex
            with engine.begin() as db:
                cursor = insert_event(db, stream, fields, key)
        except Exception as exc:  # fail open, see module docstring
            logger.warning("EventLog: append to %s failed (event dropped): %s", stream, exc)
            return None
        if cursor is not None:
            self._observe_head(cursor)
        self._wake()
        return cursor

    def committed(self) -> None:
        """Wake the readers of this process after a transaction of the store inserted an event row (`insert_event`)."""
        try:
            self._observe_head(self.head() or 0)
        except Exception:  # the followers read the head themselves
            self._forget_head()
        self._wake()

    def _observe_head(self, head: int) -> None:
        with self._head_moved:
            if self._head is None or head > self._head:
                self._head = head
                self._head_moved.notify_all()

    def _forget_head(self) -> None:
        with self._head_moved:
            self._head = None
            self._head_moved.notify_all()

    def known_head(self) -> int | None:
        """The newest event id the commit watch has seen (0 for none), None while it is unknown. Starts the watch first,
        so a commit after this read moves the head."""
        self._watch()
        return self._head

    def wait_for_head(self, cursor: int | None, stop: StopEvent) -> None:
        """Return when the newest event id seen is not `cursor` (or is unknown) or `stop` is set; no timer ends it. A
        commit that appended no event wakes nothing here."""
        self._watch()
        stop.listen(self._notify_head)
        try:
            with self._head_moved:
                while self._head == (cursor or 0) and not stop.is_set():
                    self._head_moved.wait()
        finally:
            stop.unlisten(self._notify_head)

    def _notify_head(self) -> None:
        with self._head_moved:
            self._head_moved.notify_all()

    @property
    def appends(self) -> int:
        """How many appends and commits by other processes this log has seen: the `seen` for `wait_for_append`.

        Reading it starts the commit watch first, so a commit elsewhere after the read is counted, not taken into the
        watch's baseline."""
        self._watch()
        return self._appends

    def wait_for_append(self, seen: int, stop: StopEvent) -> None:
        """Return when `appends` has moved past `seen` or `stop` is set; no timer ends it.

        Read `appends` before the poll it precedes, so an append that lands during that poll still ends this wait.
        """
        self._watch()
        stop.listen(self._notify)  # before the check below, so a stop between the check and the wait is not lost
        try:
            with self._appended:
                while self._appends == seen and not stop.is_set():
                    self._appended.wait()
        finally:
            stop.unlisten(self._notify)

    def run_on_wake(self, stop: StopEvent, step: Callable[[], object], failure: str, signal: str | None = None) -> None:
        """Run `step` now, then after each append or commit by another process, until `stop`; no timer ends the wait.
        With `signal`, a statement returning what `step` reads, it runs again only when that value moved, so no
        commit that changed something else wakes it (a log with no file to watch wakes on every append). A step that
        raises is logged as `failure` and run again after `RETRY_DELAY`. `appends` is read before each step, so a
        commit that lands during it ends the next wait at once. Each wake is counted under the thread's name in
        `wakes`."""
        follower = threading.current_thread().name
        signal = signal if self._has_file() else None
        while not stop.is_set():
            try:
                seen = self.appends if signal is None else self._signal_version(signal)
                head = self._head
                step()
            except Exception:
                logger.exception(failure)
                # adr-exempt: retry
                stop.wait(RETRY_DELAY)
                continue
            if signal is None:
                self.wait_for_append(seen, stop)
            else:
                self._signal_watch().wait(signal, seen, stop)
            if not stop.is_set() and self.wakes.count(follower, self._head != head):
                self._publish_wakes()

    def keep_wakes(self, child: str) -> None:
        """Keep the wake counts of this process as `child` in the log's state, now and every `PUBLISH_EVERY` wakes, for
        the Page API to relay."""
        self._wakes_child = child
        self._publish_wakes()

    def _publish_wakes(self) -> None:
        if (child := self._wakes_child) is not None:
            try:
                self.put_state(WAKES_STATE + child, wake_samples(self.wakes.counts(), child))
            except Exception:
                logger.warning("EventLog: the follower wakes were not kept for the metric", exc_info=True)

    def _has_file(self) -> bool:
        return make_url(self.url).database not in (None, "", ":memory:")

    def _signal_version(self, sql: str) -> int:
        self._watch()
        return self._signal_watch().version(sql, self._read_signal)

    def _signal_watch(self) -> Signals:
        with self._lock:
            if self._signals is None:
                self._signals = Signals()  # a log no follower reads a signal from runs none of it, commit watch included
            return self._signals

    def _read_signal(self, sql: str) -> Any:
        connection = self.engine.raw_connection()
        try:
            return read_value(connection.driver_connection, sql)
        finally:
            connection.close()

    def _notify(self) -> None:
        with self._appended:
            self._appended.notify_all()

    def _wake(self) -> None:
        with self._appended:
            self._appends += 1
            self._appended.notify_all()

    def _watch(self) -> None:
        """Start, once, the thread that wakes waiters on another process's SQLite commit; nothing on an in-memory
        database, which has no other process to see. Returns once the thread has read its baseline (or
        failed to), so a commit after this call wakes waiters."""
        with self._lock:
            if self._watching:
                return
            self._watching = True
        url = make_url(self.url)
        if url.database not in (None, "", ":memory:"):
            baseline = threading.Event()
            ended, release = os.pipe()
            # the thread sees the pipe end when the log is dropped or closed
            self._unwatch = weakref.finalize(self, os.close, release)
            threading.Thread(
                target=_watch_commits,
                args=(weakref.ref(self), url.database, self._fallback_interval, baseline, ended),
                name="eventlog-commit-watch",
                daemon=True,
            ).start()
            # adr-exempt: handshake
            baseline.wait(_SQLITE_BUSY_TIMEOUT)

    def prune(self, retention: float, now: float | None = None, *, archive_dir: Path) -> int:
        """Archive and then delete the rows older than `retention` seconds and return how many; raises when the
        database or the archive does.

        Rows go to `archive_dir` first, in id order, one gzip JSONL file per UTC day of `at` (`YYYY-MM-DD.jsonl.gz`),
        appended to when a later pass prunes more of that day. A batch is deleted only after its lines were written
        and fsynced, so a failed write deletes nothing and a crash between write and delete archives those rows again
        on the next pass: a reader of the archive treats `id` as its key.
        """
        cutoff = (time.time() if now is None else now) - retention
        engine = self.engine
        pruned = last = 0
        while True:
            with engine.connect() as db:
                batch = db.execute(
                    select(events)
                    .where(events.c.at < cutoff, events.c.id > last, events.c.stream.not_in(RETAINED_STREAMS))
                    .order_by(events.c.id)
                    .limit(_PRUNE_BATCH)
                ).all()
            if not batch:
                return pruned
            _archive(archive_dir, batch)
            with engine.begin() as db:
                db.execute(
                    delete(events).where(
                        events.c.id > last,
                        events.c.id <= batch[-1].id,
                        events.c.at < cutoff,
                        events.c.stream.not_in(RETAINED_STREAMS),
                    )
                )
            pruned += len(batch)
            last = batch[-1].id

    def restore(self, archive_dir: Path) -> int:
        """Put the archived rows of `RETAINED_STREAMS` back in the log at their archived `id` and return how many were
        inserted; a row whose `id` or `event_id` the log holds is left as it is, so a second call inserts nothing.
        Raises when the database or the archive does."""
        restored = 0
        for path in sorted(archive_dir.glob("*.jsonl.gz")):
            with gzip.open(path, "rt") as day:
                wanted = (row for row in map(json.loads, day) if row["stream"] in RETAINED_STREAMS)
                for batch in batched(wanted, _PRUNE_BATCH):
                    with self.engine.begin() as db:
                        restored += db.execute(sqlite.insert(events).on_conflict_do_nothing(), list(batch)).rowcount
        return restored

    def last(self, stream: str) -> int | None:
        """The cursor of `stream`'s newest row, or None when it has none; raises when the database does."""
        with self.engine.connect() as db:
            return db.execute(select(func.max(events.c.id)).where(events.c.stream == stream)).scalar()

    def first(self, stream: str) -> int | None:
        """The cursor of `stream`'s oldest retained row, or None when it has none; raises when the database does."""
        with self.engine.connect() as db:
            return db.execute(select(func.min(events.c.id)).where(events.c.stream == stream)).scalar()

    def head(self) -> int | None:
        """The cursor of the newest row of any stream, or None when the log holds none; raises when the database does."""
        with self.engine.connect() as db:
            return db.execute(select(func.max(events.c.id))).scalar()

    def tail(self, stream: str, **kwargs: Any) -> Tail:
        """A `Tail` of `stream` on this log, the one way a reader outside this module comes by one: `kwargs` are the
        `Tail`'s own (`after`, `batch`, `streams`). `Tail.catch_up` reads what is retained, `Tail.run`
        follows what is appended."""
        return Tail(self, stream, **kwargs)

    def oldest(self) -> int | None:
        """The cursor of the oldest row the log retains, or None when it holds none; raises when the database does."""
        with self.engine.connect() as db:
            return db.execute(select(func.min(events.c.id))).scalar()


#: The longest a running tail waits between polls while they keep failing, in seconds.
MAX_POLL_BACKOFF = 60.0


class Tail:
    """One reader's cursor over one stream of the log.

    The start is named: `Tail(...)` resumes after `after`, the `id` of the last row the reader already handled (the
    history recorder's persisted cursor); `Tail.replay` reads everything the log still retains, which is not a gap
    however much was pruned before; `Tail.live` reads only what is appended after it was taken. Rows of other
    streams share the ids, so the cursor advances past them. A reader of several streams (`streams`, which default
    to `stream` alone) reads them in log order under one cursor, and `stream` then names the reader.
    """

    def __init__(
        self,
        log: EventLog,
        stream: str,
        *,
        after: int | None,
        batch: int = 500,
        streams: Sequence[str] | None = None,
    ) -> None:
        self.log = log
        self.stream = stream
        self.streams = tuple(streams or (stream,))
        self.cursor = after
        self.batch = batch
        self._traced: set[type[Exception]] = set()  # exception types whose traceback `run` has logged
        self._suppressed: Counter[type[Exception]] = Counter()  # repeats since the last summary

    @classmethod
    def replay(cls, log: EventLog, stream: str, **kwargs: Any) -> Tail:
        """A Tail that reads everything the log still retains."""
        return cls(log, stream, after=None, **kwargs)

    @classmethod
    def live(cls, log: EventLog, stream: str, **kwargs: Any) -> Tail:
        """A Tail that reads only the rows appended after the newest one of `stream` (of `streams`, when it reads
        several) now, for a reader that rebuilds its state from elsewhere and would discard the replay. Take it before
        that rebuild, so a row appended meanwhile is read. When the log cannot be reached it replays the retention,
        which is the safe start."""
        try:
            after = max(filter(None, map(log.last, kwargs.get("streams") or [stream])), default=None)
        except Exception as exc:  # the database is unreachable; `run` retries the polls
            logger.warning("Tail %s: cannot read the head, replaying the retention: %s", stream, exc)
            after = None
        return cls(log, stream, after=after, **kwargs)

    def poll(self) -> list[Entry]:
        """Read the next batch of this stream's rows past the cursor, move the cursor, and return them.

        The read runs on a connection that is returned before this call does, so no transaction outlasts a poll.
        Raises when the database is unreachable; `run` retries.
        """
        return [Entry(r.id, r.stream, r.event_id, r.fields, r.at) for r in self._rows(events)]

    def poll_json(self) -> list[tuple[int, str]]:
        """`poll`, as each row's `id` and its fields still the JSON text the log stores, for a reader that parses it itself."""
        return [(r.id, r.fields) for r in self._rows(events.c.id, type_coerce(events.c.fields, String).label("fields"))]

    def _rows(self, *columns: Any) -> Sequence[Any]:
        engine = self.log.engine
        head = self.log.known_head()
        with engine.connect() as db:
            if head is None:  # the watch has not read it yet: one query, which every later poll skips
                head = db.scalar(_HEAD) or 0
                self.log._observe_head(head)
            cursor = self.cursor
            if head == (cursor or 0):  # idle: no query ran
                return []
            rows = db.execute(
                select(*columns)
                .where(events.c.stream.in_(self.streams), events.c.id > (cursor or 0), events.c.id <= head)
                .order_by(events.c.id)
                .limit(self.batch)
            ).all()
        self.cursor = rows[-1].id if len(rows) == self.batch else head
        return rows

    def catch_up(self, handle: Callable[[Entry], None]) -> None:
        """Pass `handle` every entry past the cursor now retained, then return: the boundary before `run` follows live.
        A poll that fails raises, as `poll` does."""
        while batch := self.poll():
            for entry in batch:
                handle(entry)

    def _note_failure(self, exc: Exception, entry: Entry) -> None:
        """Log the first failure of each exception type with its traceback; count the repeats for the batch summary,
        so a replay of thousands of bad entries writes one traceback, not thousands."""
        kind = type(exc)
        if kind in self._traced:
            self._suppressed[kind] += 1
            return
        self._traced.add(kind)
        logger.error("Tail %s: handler failed on entry %s", self.stream, entry.id, exc_info=exc)

    def _summarize_failures(self) -> None:
        """Log one line per exception type for the repeats counted since the last summary, then reset the counts."""
        for kind, count in self._suppressed.items():
            logger.warning(
                "Tail %s: %d more handler failures of %s since the last summary; traceback logged once",
                self.stream,
                count,
                kind.__name__,
            )
        self._suppressed.clear()

    def run(
        self,
        handle: Callable[[Entry], None],
        stop: StopEvent,
        transient: tuple[type[BaseException], ...] = (),
        after_batch: Callable[[], None] | None = None,
    ) -> None:
        """Read until `stop` is set, passing each entry to `handle`, then calling `after_batch` once per batch that held
        an entry. Between reads an idle tail waits for the events head to move (`EventLog.wait_for_head`), which no timer ends.

        A read that fails (the database went away) is retried after `RETRY_DELAY`, then after twice that for each further
        failure up to `MAX_POLL_BACKOFF`. The outage logs one warning, without a trace, and one line when a poll
        succeeds again, so a missing table costs a few lines, not one per poll. A handler that raises is logged
        and the loop goes on with the next entry, so one bad event never stops a reader. Only the first failure of
        each exception type logs a traceback; the repeats are counted in a summary line after each batch. A handler that raises one of
        `transient` (its sink is down, the entry is not bad) is not skipped: the cursor goes back before that entry
        and the read after `RETRY_DELAY` reads it again.
        """
        delay = 0.0  # the wait after the last failed poll; 0 while polls succeed
        while not stop.is_set():
            try:
                entries = self.poll()
            except Exception as exc:  # the database is unreachable or locked; the next poll retries
                if not delay:
                    logger.warning("Tail %s: poll failed, backing off until it succeeds: %s", self.stream, exc)
                delay = min(delay * 2, MAX_POLL_BACKOFF) if delay else RETRY_DELAY
                # adr-exempt: retry
                stop.wait(delay)
                continue
            if delay:
                logger.info("Tail %s: poll succeeded again", self.stream)
                delay = 0.0
            retry = False
            for entry in entries:
                try:
                    handle(entry)
                except transient as exc:
                    logger.warning("Tail %s: sink down at entry %s, retrying: %s", self.stream, entry.id, exc)
                    self.cursor = entry.id - 1
                    retry = True
                    break
                except Exception as exc:  # a reader's bug must not stop the reader
                    self._note_failure(exc, entry)
            self._summarize_failures()
            if entries and after_batch:
                after_batch()
            if retry:
                # adr-exempt: retry
                stop.wait(RETRY_DELAY)
            elif len(entries) < self.batch:
                self.log.wait_for_head(self.cursor, stop)


def _archive(directory: Path, rows: Sequence[Any]) -> None:
    """Append `rows` to their UTC days' files in `directory` and fsync each file and the directory before returning.

    A write that fails is cut back to the file's earlier size, so no torn gzip member stays in a day's file.
    """
    days: dict[str, list[str]] = {}
    for row in rows:
        entry = {"id": row.id, "stream": row.stream, "event_id": row.event_id, "fields": row.fields, "at": row.at}
        day = datetime.fromtimestamp(row.at, UTC).strftime("%Y-%m-%d")
        days.setdefault(day, []).append(json.dumps(entry, separators=(",", ":")) + "\n")
    directory.mkdir(parents=True, exist_ok=True)
    for day, lines in days.items():
        with (directory / f"{day}.jsonl.gz").open("ab") as raw:
            size = raw.tell()
            try:
                with gzip.GzipFile(fileobj=raw, mode="wb") as member:  # a gzip file may hold several members
                    member.write("".join(lines).encode())
                raw.flush()
                os.fsync(raw.fileno())
            except BaseException:
                raw.truncate(size)
                raise
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)  # a new day's file must survive a crash as an entry of the directory
    finally:
        os.close(fd)


def insert_event(db: Connection, stream: str, fields: Mapping[str, Any], key: str) -> int | None:
    """Insert the event row `key` in `db`'s open transaction and return its cursor; a row holding `key` is not inserted
    again and its cursor is returned. The caller's commit makes it durable: a state change that inserts its event here
    lands with it or not at all."""
    known = select(events.c.id).where(events.c.event_id == key)
    statement = (
        sqlite.insert(events)
        .values(stream=stream, event_id=key, fields=dict(fields), at=time.time())
        .on_conflict_do_nothing()
        .returning(events.c.id)
    )
    # Look first: an ignored insert still spends an id, and a hole in the ids would read as a pruned span.
    cursor = db.execute(known).scalar()
    if cursor is None:
        cursor = db.execute(statement).scalar()
    if cursor is None:  # another process appended this event_id between the look and the insert
        cursor = db.execute(known).scalar()
    return cursor


def store_engine(url: str) -> Engine:
    """An engine on the store at `url` that waits on a locked SQLite database as long as the server does."""
    if make_url(url).database in (None, "", ":memory:"):  # one in-memory database per connection: no pool to size
        engine = create_engine(url, connect_args={"timeout": _SQLITE_BUSY_TIMEOUT})
    else:
        engine = create_engine(
            url, connect_args={"timeout": _SQLITE_BUSY_TIMEOUT}, pool_size=_POOL_SIZE, max_overflow=_POOL_OVERFLOW
        )
    event.listen(engine, "connect", _sqlite_pragmas)
    return engine


def unpooled_engine(engine: Engine) -> Engine:
    """An engine on `engine`'s database that opens a connection for each use and closes it after. sqlite keeps the last
    bound parameter of every cached statement until that statement runs again on its connection, so a writer of large
    values on pooled connections parks a copy of one on each of them. An in-memory database is one
    connection already: `engine` itself."""
    if engine.url.database in (None, "", ":memory:"):
        return engine
    unpooled = create_engine(engine.url, connect_args={"timeout": _SQLITE_BUSY_TIMEOUT}, poolclass=NullPool)
    event.listen(unpooled, "connect", _sqlite_pragmas)
    return unpooled
