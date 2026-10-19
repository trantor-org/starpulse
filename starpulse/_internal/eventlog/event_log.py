"""StarPulse's event log: an append-only table in the history store that producers write and readers poll.

Every producer on the host appends one row (`EventLog.append`), which never raises, so reporting an event never
fails the work that caused it. Every reader keeps its own cursor, the `id` of the last row it passed, and
polls `id > cursor` (`Tail`); there are no consumer groups. A tail without a cursor replays the retained log, one
given a cursor resumes after it, and `EventLog.prune` drops rows older than a retention, which `serve` runs hourly
(`prune_forever`) after writing each row to its UTC day's gzip JSONL archive file. A cursor below the oldest retained row means rows were pruned unread, which is recorded in
`starpulse_gaps`.

The database is the history store's: SQLite by default (in WAL mode, so processes on the host append while the
server reads) or the Postgres a `database_url` names. Delivery is at-least-once within retention, so a handler
treats `event_id` as its idempotency key. Latency is the poll interval, so a reader polls often (one indexed
`id > ?` query) and holds no connection, hence no read transaction, between polls: a held SQLite read transaction
would stop WAL checkpoints and grow the `-wal` file without bound.

A running tail does not sleep out the interval. An append in this process wakes every waiting tail at once, and on
SQLite so does a commit by another process, seen as a change of `PRAGMA data_version` that one watcher thread per log
checks (`EventLog.wait_for_append`). The interval is the fallback bound: it alone delivers a Postgres append from
another process, and it recovers a wake-up that went missing.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import Engine, Table, create_engine, delete, event, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import SQLAlchemyError

from starpulse._internal.eventlog import DEFAULT_POLL_INTERVAL
from starpulse._internal.eventlog.migrate import migrate
from starpulse._internal.eventlog.tables import (
    autopilot_runs,
    board_state,
    day_rollups,
    events,
    gaps,
    metadata,
    retired_tasks,
    settings,
    source_instances,
)

__all__ = ["Entry", "EventLog", "Tail"]

logger = logging.getLogger(__name__)

#: How often the SQLite watcher looks for a commit by another process, in seconds.
_DATA_VERSION_INTERVAL = 0.25

#: The longest a waiting tail sleeps before it looks at its stop event again, in seconds.
_STOP_SLICE = 0.5

#: How long SQLite waits on another process's write lock before an append gives up and fails open, in seconds.
_SQLITE_BUSY_TIMEOUT = 5.0

#: How many times a new SQLite connection tries to switch to WAL, which fails at once, without waiting on the busy
#: timeout, while another connection opens or closes the database.
_PRAGMA_ATTEMPTS = 20

#: How many rows a prune archives and deletes at a time, so a long backlog is never held in memory at once.
_PRUNE_BATCH = 1000

#: How many times a producer looks for the tables, creating those missing, before the failure counts.
_CREATE_ATTEMPTS = 5


class Entry(NamedTuple):
    """One row of the log: `id` is the cursor to resume after."""

    id: int
    stream: str
    event_id: str
    fields: dict[str, Any]
    at: float


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:  # pragma: no mutate block — sqlite3 tuning
    cursor = dbapi_connection.cursor()
    for attempt in range(_PRAGMA_ATTEMPTS):
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            break
        except sqlite3.OperationalError:
            if attempt == _PRAGMA_ATTEMPTS - 1:
                raise
            time.sleep(0.05)
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


class EventLog:
    """The log in one database. Opening it is lazy and retried, so a producer that starts before its database is
    reachable appends once it is."""

    def __init__(self, url: str, *, engine: Engine | None = None) -> None:
        self.url = url
        self._engine = engine
        self._ready = False
        self._lock = threading.Lock()
        self._appended = threading.Condition()
        self._appends = 0
        self._watching = False

    def close(self) -> None:
        """Release the database connections the log holds; the log reopens on its next use."""
        with self._lock:
            if self._engine is not None:
                self._engine.dispose()

    @property
    def engine(self) -> Engine:
        """The engine with the log's tables created; raises while the database cannot be opened."""
        with self._lock:
            if not self._ready:
                if self._engine is None:
                    self._engine = _create_engine(self.url)
                if self._engine.dialect.name == "sqlite":
                    event.listen(self._engine, "connect", _sqlite_pragmas)
                create_tables(
                    self._engine,
                    [events, gaps, board_state, source_instances, settings, autopilot_runs, retired_tasks],
                )
                self._ready = True
            assert self._engine is not None
            return self._engine

    def bind_source(self, source: str, instance: str) -> str | None:
        """The instance `source` is bound to once this call is done: `instance` when the source held no binding (this
        call took it) or already held this one, else the instance that holds it. None when the database refused;
        never raises.

        Taking the binding is one insert that ignores a row already there, so two first batches racing bind the one
        that committed first.
        """
        try:
            engine = self.engine
            take = (
                _dialect(engine)
                .insert(source_instances)
                .values(source=source, instance=instance, bound_at=time.time())
                .on_conflict_do_nothing()
            )
            with engine.begin() as db:
                db.execute(take)
                return db.execute(
                    select(source_instances.c.instance).where(source_instances.c.source == source)
                ).scalar()
        except Exception as exc:  # fail open, see module docstring
            logger.warning("EventLog: binding source %s failed: %s", source, exc)
            return None

    def unbind_source(self, source: str) -> bool:
        """Drop `source`'s binding so the next instance to send binds it: True when it held one. Raises on a database
        error, since an operator asked for it."""
        with self.engine.begin() as db:
            return db.execute(delete(source_instances).where(source_instances.c.source == source)).rowcount > 0

    def setting(self, key: str) -> Any | None:
        """The value kept under `key`, or None when no row holds one. Raises on a database error, so a caller that
        must fail closed decides what an unreadable setting means."""
        with self.engine.connect() as db:
            return db.execute(select(settings.c.value).where(settings.c.key == key)).scalar()

    def set_setting(self, key: str, value: Any, *, updated_at: float | None = None) -> None:
        """Keep `value` under `key`, replacing what was there, stamped now or at `updated_at`. Raises on a database
        error."""
        engine = self.engine
        now = time.time() if updated_at is None else updated_at
        upsert = _dialect(engine).insert(settings).values(key=key, value=value, updated_at=now)
        with engine.begin() as db:
            db.execute(
                upsert.on_conflict_do_update(
                    index_elements=[settings.c.key], set_={"value": value, "updated_at": now}
                )
            )

    def setting_updated_at(self, key: str) -> float | None:
        """The epoch second `key` was last written, or None when no row holds it. Raises on a database error."""
        with self.engine.connect() as db:
            return db.execute(select(settings.c.updated_at).where(settings.c.key == key)).scalar()

    def delete_setting(self, key: str) -> None:
        """Drop `key`'s row, so the setting reads as its default again. Raises on a database error."""
        with self.engine.begin() as db:
            db.execute(delete(settings).where(settings.c.key == key))

    def append(self, stream: str, fields: Mapping[str, Any], *, event_id: str | None = None) -> int | None:
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
        self._wake()
        return cursor

    def committed(self) -> None:
        """Wake the readers of this process after a transaction of the store inserted an event row (`insert_event`)."""
        self._wake()

    @property
    def appends(self) -> int:
        """How many appends and commits by other processes this log has seen: the `seen` for `wait_for_append`.

        Reading it starts the commit watch first, so a commit elsewhere after the read is counted, not taken into the
        watch's baseline."""
        self._watch()
        return self._appends

    def wait_for_append(self, seen: int, timeout: float, stop: threading.Event) -> None:
        """Return when `appends` has moved past `seen`, `stop` is set, or `timeout` seconds have passed.

        Read `appends` before the poll it precedes, so an append that lands during that poll still ends this wait.
        """
        self._watch()
        deadline = time.monotonic() + timeout
        with self._appended:
            while self._appends == seen and not stop.is_set() and (left := deadline - time.monotonic()) > 0:
                self._appended.wait(min(left, _STOP_SLICE))

    def _wake(self) -> None:
        with self._appended:
            self._appends += 1
            self._appended.notify_all()

    def _watch(self) -> None:
        """Start, once, the thread that wakes waiters on another process's SQLite commit; nothing on Postgres or an
        in-memory database, which have no other process to see. Returns once the thread has read its baseline (or
        failed to), so a commit after this call wakes waiters."""
        with self._lock:
            if self._watching:
                return
            self._watching = True
        url = make_url(self.url)
        if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
            baseline = threading.Event()
            threading.Thread(
                target=self._watch_data_version,
                args=(url.database, baseline),
                name="eventlog-data-version",
                daemon=True,
            ).start()
            baseline.wait(_SQLITE_BUSY_TIMEOUT)

    def _watch_data_version(self, database: str, baseline: threading.Event) -> None:
        """Wake waiters whenever another connection commits to `database`, setting `baseline` after the first read.
        `PRAGMA data_version` changes only for commits made through other connections, and a connection without a
        transaction holds no read lock, so this one never stalls a checkpoint."""
        version = None
        connection = None
        while True:
            try:
                if connection is None:
                    connection = sqlite3.connect(database, timeout=_SQLITE_BUSY_TIMEOUT, isolation_level=None)
                current = connection.execute("PRAGMA data_version").fetchone()[0]
                if version is not None and current != version:
                    self._wake()
                version = current
            except sqlite3.Error as exc:  # the file is locked or gone; the interval still delivers
                logger.debug("EventLog: data_version check failed: %s", exc)
                connection, version = None, None
            baseline.set()
            time.sleep(_DATA_VERSION_INTERVAL)

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
                    .where(events.c.at < cutoff, events.c.id > last)
                    .order_by(events.c.id)
                    .limit(_PRUNE_BATCH)
                ).all()
            if not batch:
                return pruned
            _archive(archive_dir, batch)
            with engine.begin() as db:
                db.execute(delete(events).where(events.c.id > last, events.c.id <= batch[-1].id, events.c.at < cutoff))
            pruned += len(batch)
            last = batch[-1].id

    def last(self, stream: str) -> int | None:
        """The cursor of `stream`'s newest row, or None when it has none; raises when the database does."""
        with self.engine.connect() as db:
            return db.execute(select(func.max(events.c.id)).where(events.c.stream == stream)).scalar()

    def head(self) -> int | None:
        """The cursor of the newest row of any stream, or None when the log holds none; raises when the database does."""
        with self.engine.connect() as db:
            return db.execute(select(func.max(events.c.id))).scalar()

    def oldest(self) -> int | None:
        """The cursor of the oldest row the log retains, or None when it holds none; raises when the database does."""
        with self.engine.connect() as db:
            return db.execute(select(func.min(events.c.id))).scalar()

    def save_board_state(self, stream: str, cursor: str, state: dict) -> None:
        """Keep `state`, the Board a reader built from `stream` up to the entry `cursor`, in place of the last one.

        A key ending `@<hash>` also removes the Boards saved under the same base with another hash: a projection
        change saved under a new key, and the old row would otherwise stay forever.
        """
        engine = self.engine
        base, at, _ = stream.rpartition("@")
        superseded = board_state.c.stream.startswith(base + at, autoescape=True) & (board_state.c.stream != stream)
        insert = (
            _dialect(engine)
            .insert(board_state)
            .values(stream=stream, after_id=cursor, state=state, saved_at=time.time())
        )
        with engine.begin() as db:
            db.execute(
                insert.on_conflict_do_update(
                    index_elements=["stream"],
                    set_={
                        "after_id": insert.excluded.after_id,
                        "state": insert.excluded.state,
                        "saved_at": insert.excluded.saved_at,
                    },
                )
            )
            if at:
                db.execute(delete(board_state).where(superseded))

    def load_board_state(self, stream: str) -> tuple[str, dict] | None:
        """The cursor and state last saved for `stream`, or None when none was; raises when the database does."""
        with self.engine.connect() as db:
            row = db.execute(
                select(board_state.c.after_id, board_state.c.state).where(board_state.c.stream == stream)
            ).first()
        return None if row is None else (row.after_id, row.state)

    def record_gap(self, stream: str, after_id: int, before_id: int, lost: int) -> None:
        """Note that up to `lost` rows between `after_id` and `before_id` were pruned before `stream`'s reader read
        them; the same `after_id` again updates that gap."""
        engine = self.engine
        insert = (
            _dialect(engine)
            .insert(gaps)
            .values(stream=stream, after_id=str(after_id), before_id=str(before_id), lost=lost, noted_at=time.time())
        )
        with engine.begin() as db:
            db.execute(
                insert.on_conflict_do_update(
                    index_elements=["stream", "after_id"],
                    set_={"before_id": insert.excluded.before_id, "lost": insert.excluded.lost},
                )
            )


class Tail:
    """One reader's cursor over one stream of the log.

    `after` is the `id` of the last row the reader already handled (the history recorder's persisted cursor); None
    replays everything the log still retains, which is not a gap however much was pruned before. Rows of other
    streams share the ids, so the cursor advances past them and a gap's `lost` counts every pruned id in its span,
    an upper bound for this stream. A reader of several streams (`streams`, which default to `stream` alone) reads
    them in log order under one cursor, and `stream` then names the reader.
    """

    def __init__(
        self,
        log: EventLog,
        stream: str,
        *,
        after: int | None = None,
        interval: float = DEFAULT_POLL_INTERVAL,
        batch: int = 500,
        streams: Sequence[str] | None = None,
    ) -> None:
        self.log = log
        self.stream = stream
        self.streams = tuple(streams or (stream,))
        self.cursor = after
        self.interval = interval
        self.batch = batch

    @classmethod
    def at_head(cls, log: EventLog, stream: str, **kwargs: Any) -> Tail:
        """A Tail that reads only the rows appended after `stream`'s newest one now, for a reader that rebuilds its
        state from elsewhere and would discard the replay. Take it before that rebuild, so a row appended meanwhile is
        read. When the log cannot be reached it replays the retention, which is the safe start."""
        try:
            after = log.last(stream)
        except Exception as exc:  # the database is unreachable; `run` retries the polls
            logger.warning("Tail %s: cannot read the head, replaying the retention: %s", stream, exc)
            after = None
        return cls(log, stream, after=after, **kwargs)

    def poll(self) -> list[Entry]:
        """Read the next batch of this stream's rows past the cursor, move the cursor, and return them.

        The read runs on a connection that is returned before this call does, so no transaction outlasts a poll.
        Raises when the database is unreachable; `run` retries.
        """
        engine = self.log.engine
        with engine.connect() as db:
            # Scalar subqueries: SQLite answers a lone min or max from the primary key, but scans an index for both.
            oldest, head = db.execute(
                select(select(func.min(events.c.id)).scalar_subquery(), select(func.max(events.c.id)).scalar_subquery())
            ).one()
            cursor = self.cursor
            if head is None or head == cursor:  # idle: the one query above is the whole poll
                return []
            gap = cursor is not None and oldest > cursor + 1
            start = oldest - 1 if gap else cursor or 0
            rows = db.execute(
                select(events)
                .where(events.c.stream.in_(self.streams), events.c.id > start, events.c.id <= head)
                .order_by(events.c.id)
                .limit(self.batch)
            ).all()
        if gap:
            self.log.record_gap(self.stream, cursor, oldest, oldest - cursor - 1)
        self.cursor = rows[-1].id if len(rows) == self.batch else head
        return [Entry(r.id, r.stream, r.event_id, r.fields, r.at) for r in rows]

    def run(
        self,
        handle: Callable[[Entry], None],
        stop: threading.Event,
        transient: tuple[type[BaseException], ...] = (),
    ) -> None:
        """Poll until `stop` is set, passing each entry to `handle`. Between polls an idle tail waits for an append
        (`EventLog.wait_for_append`), so `interval` bounds the wait rather than setting it.

        A poll that fails (the database went away) is retried after the interval. A handler that raises is logged
        and the loop goes on with the next entry, so one bad event never stops a reader. A handler that raises one of
        `transient` (its sink is down, the entry is not bad) is not skipped: the cursor goes back before that entry
        and the poll after the interval reads it again.
        """
        while not stop.is_set():
            seen = self.log.appends  # before the poll, so an append during it still ends the wait below
            try:
                entries = self.poll()
            except Exception as exc:  # the database is unreachable or locked; the next poll retries
                logger.warning("Tail %s: poll failed, retrying in %ss: %s", self.stream, self.interval, exc)
                stop.wait(self.interval)
                continue
            retry = False
            for entry in entries:
                try:
                    handle(entry)
                except transient as exc:
                    logger.warning("Tail %s: sink down at entry %s, retrying: %s", self.stream, entry.id, exc)
                    self.cursor = entry.id - 1
                    retry = True
                    break
                except Exception:  # a reader's bug must not stop the reader
                    logger.exception("Tail %s: handler failed on entry %s", self.stream, entry.id)
            if retry:
                stop.wait(self.interval)
            elif len(entries) < self.batch:
                self.log.wait_for_append(seen, self.interval, stop)


def prune_forever(
    log: EventLog, *, retention_days: int, archive_dir: Path, stop: threading.Event, interval: float = 3600
) -> None:
    """Prune the rows older than `retention_days` into `archive_dir` at start and then every `interval` seconds until
    `stop` is set. A pass that fails is logged and the next one retries, so a database that was briefly away, or an
    archive that could not be written, does not end the pruning."""
    while True:
        try:
            if pruned := log.prune(retention_days * 86400, archive_dir=archive_dir):
                logger.info("EventLog: pruned %d rows older than %d days", pruned, retention_days)
        except Exception:  # the database is unreachable or locked; the next pass retries
            logger.exception("EventLog: prune failed; retrying in %ss", interval)
        if stop.wait(interval):
            return


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
        _dialect(db.engine)
        .insert(events)
        .values(stream=stream, event_id=key, fields=dict(fields), at=time.time())
        .on_conflict_do_nothing()  # any unique key: the hub keys a row on (event_id, at), the IC log on event_id
        .returning(events.c.id)
    )
    # Look first: an ignored insert still spends an id, and a hole in the ids would read as a pruned span.
    cursor = db.execute(known).scalar()
    if cursor is None:
        cursor = db.execute(statement).scalar()
    if cursor is None:  # another process appended this event_id between the look and the insert
        cursor = db.execute(known).scalar()
    return cursor


def _create_engine(url: str) -> Engine:
    if make_url(url).get_backend_name() == "sqlite":
        return create_engine(url, connect_args={"timeout": _SQLITE_BUSY_TIMEOUT})
    return create_engine(url)


def create_tables(engine: Engine, tables: Sequence[Table] | None = None) -> None:
    """Bring `engine`'s database to the schema the migration chain declares, the hub's rollups apart.

    A SQLite store is built and versioned by the chain, whole whichever `tables` the caller needs. Another database is
    not: the hub's Postgres arrives through its own migrations, and an instance on it creates `tables`, or every
    StarPulse table but the rollups for None, where they are missing.

    A caller that lost a race to create them looks again and finds them: each lost race means another process or
    thread created a table meanwhile, and the tables are created once, so a few looks suffice; the last failure is a
    real one and raises.
    """
    if engine.dialect.name == "sqlite":
        return migrate(engine)
    if tables is None:
        tables = [table for table in metadata.sorted_tables if table is not day_rollups]
    for _ in range(_CREATE_ATTEMPTS - 1):
        try:
            return metadata.create_all(engine, tables=tables)
        except SQLAlchemyError:
            continue
    return metadata.create_all(engine, tables=tables)


def _dialect(engine: Engine):
    return postgresql if engine.dialect.name == "postgresql" else sqlite
