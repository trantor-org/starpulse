"""StarPulse's event log: an append-only table in the history store that producers write and readers poll.

Every producer on the host appends one row (`EventLog.append`), which never raises, so reporting an event never
fails the work that caused it. Every reader keeps its own cursor, the `id` of the last row it passed, and
polls `id > cursor` (`Tail`); there are no consumer groups. A tail without a cursor replays the retained log, one
given a cursor resumes after it, and `EventLog.prune` drops rows older than a retention. A cursor below the oldest
retained row means rows were pruned unread, which is recorded in `starpulse_gaps`.

The database is the history store's: SQLite by default (in WAL mode, so processes on the host append while the
server reads) or the Postgres a `database_url` names. Delivery is at-least-once within retention, so a handler
treats `event_id` as its idempotency key. Latency is the poll interval, so a reader polls often (one indexed
`id > ?` query) and holds no connection, hence no read transaction, between polls: a held SQLite read transaction
would stop WAL checkpoints and grow the `-wal` file without bound.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from typing import Any, NamedTuple

from sqlalchemy import Engine, Table, create_engine, delete, event, func, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from starpulse.tables import board_state, day_rollups, events, gaps, metadata

__all__ = ["Entry", "EventLog", "Tail"]

logger = logging.getLogger(__name__)

#: How often a running tail polls, in seconds. It is the delivery latency a producer's event adds.
DEFAULT_POLL_INTERVAL = 0.25

#: How long SQLite waits on another process's write lock before an append gives up and fails open, in seconds.
_SQLITE_BUSY_TIMEOUT = 5.0

#: How many times a new SQLite connection tries to switch to WAL, which fails at once, without waiting on the busy
#: timeout, while another connection opens or closes the database.
_PRAGMA_ATTEMPTS = 20

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

    @property
    def engine(self) -> Engine:
        """The engine with the log's tables created; raises while the database cannot be opened."""
        with self._lock:
            if not self._ready:
                if self._engine is None:
                    self._engine = _create_engine(self.url)
                if self._engine.dialect.name == "sqlite":
                    event.listen(self._engine, "connect", _sqlite_pragmas)
                create_tables(self._engine, [events, gaps, board_state])
                self._ready = True
            assert self._engine is not None
            return self._engine

    def append(self, stream: str, fields: Mapping[str, Any], *, event_id: str | None = None) -> int | None:
        """Append one event and return its cursor, or None when it was not appended; never raises.

        `event_id` is the caller's, else the fields', else minted; a row with that `event_id` already in the log
        is not appended again and its cursor is returned. Encoding sits inside the `try`: fields JSON refuses must
        fail open like an outage.
        """
        try:
            engine = self.engine
            key = event_id or str(fields.get("event_id") or "") or uuid.uuid4().hex
            known = select(events.c.id).where(events.c.event_id == key)
            statement = (
                _dialect(engine)
                .insert(events)
                .values(stream=stream, event_id=key, fields=dict(fields), at=time.time())
                .on_conflict_do_nothing()  # any unique key: the hub keys a row on (event_id, at), the IC log on event_id
                .returning(events.c.id)
            )
            with engine.begin() as db:
                # Look first: an ignored insert still spends an id, and a hole in the ids would read as a pruned span.
                cursor = db.execute(known).scalar()
                if cursor is None:
                    cursor = db.execute(statement).scalar()
                if cursor is None:  # another process appended this event_id between the look and the insert
                    cursor = db.execute(known).scalar()
            return cursor
        except Exception as exc:  # fail open, see module docstring
            logger.warning("EventLog: append to %s failed (event dropped): %s", stream, exc)
            return None

    def prune(self, retention: float, now: float | None = None) -> int:
        """Delete the rows older than `retention` seconds and return how many; raises when the database does."""
        cutoff = (time.time() if now is None else now) - retention
        with self.engine.begin() as db:
            return db.execute(delete(events).where(events.c.at < cutoff)).rowcount

    def last(self, stream: str) -> int | None:
        """The cursor of `stream`'s newest row, or None when it has none; raises when the database does."""
        with self.engine.connect() as db:
            return db.execute(select(func.max(events.c.id)).where(events.c.stream == stream)).scalar()

    def oldest(self) -> int | None:
        """The cursor of the oldest row the log retains, or None when it holds none; raises when the database does."""
        with self.engine.connect() as db:
            return db.execute(select(func.min(events.c.id))).scalar()

    def save_board_state(self, stream: str, cursor: str, state: dict) -> None:
        """Keep `state`, the Board a reader built from `stream` up to the entry `cursor`, in place of the last one."""
        engine = self.engine
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
    an upper bound for this stream.
    """

    def __init__(
        self,
        log: EventLog,
        stream: str,
        *,
        after: int | None = None,
        interval: float = DEFAULT_POLL_INTERVAL,
        batch: int = 500,
    ) -> None:
        self.log = log
        self.stream = stream
        self.cursor = after
        self.interval = interval
        self.batch = batch

    def poll(self) -> list[Entry]:
        """Read the next batch of this stream's rows past the cursor, move the cursor, and return them.

        The read runs on a connection that is returned before this call does, so no transaction outlasts a poll.
        Raises when the database is unreachable; `run` retries.
        """
        engine = self.log.engine
        with engine.connect() as db:
            oldest = db.execute(select(func.min(events.c.id))).scalar()
            head = db.execute(select(func.max(events.c.id))).scalar()
            if head is None:
                return []
            cursor = self.cursor
            gap = cursor is not None and oldest > cursor + 1
            start = oldest - 1 if gap else cursor or 0
            rows = db.execute(
                select(events)
                .where(events.c.stream == self.stream, events.c.id > start, events.c.id <= head)
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
        """Poll until `stop` is set, passing each entry to `handle`.

        A poll that fails (the database went away) is retried after the interval. A handler that raises is logged
        and the loop goes on with the next entry, so one bad event never stops a reader. A handler that raises one of
        `transient` (its sink is down, the entry is not bad) is not skipped: the cursor goes back before that entry
        and the poll after the interval reads it again.
        """
        while not stop.is_set():
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
            if retry or len(entries) < self.batch:
                stop.wait(self.interval)


def _create_engine(url: str) -> Engine:
    if make_url(url).get_backend_name() == "sqlite":
        return create_engine(url, connect_args={"timeout": _SQLITE_BUSY_TIMEOUT})
    return create_engine(url)


def create_tables(engine: Engine, tables: Sequence[Table] | None = None) -> None:
    """Create `tables`, or every StarPulse table but the hub's rollups for None, in `engine`'s database.

    The rollups belong to a hub and arrive with its migrations, so an instance's own database never gains them here.

    A caller that lost a race to create them looks again and finds them: each lost race means another process or
    thread created a table meanwhile, and the tables are created once, so a few looks suffice; the last failure is a
    real one and raises.
    """
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
