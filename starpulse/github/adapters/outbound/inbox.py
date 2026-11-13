"""The `github_inbox` table and the SQLAlchemy `Inbox` that saves a delivery into it.

The inbox is its own database (`[github] database_url`, SQLite by default), never the event store, so the process that
faces the internet cannot write an event. Its schema is the Alembic chain in `migrations/`, run when an inbox opens.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Collection
from pathlib import Path

from sqlalchemy import Column, Float, Integer, LargeBinary, MetaData, String, Table, create_engine, event, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from starpulse.github.model.delivery import Delivery
from starpulse.github.ports.inbox import InboxError

__all__ = ["Migrate", "SqlInbox", "github_inbox"]

VERSION_TABLE = "github_alembic_version"
#: Brings an engine's database to the head of a migration chain: `(engine, migrations directory, version table)`. The
#: composition root passes the event log's shared runner, which this context may not import.
Migrate = Callable[[Engine, Path, str], None]
_MIGRATIONS = Path(__file__).parent / "migrations"

metadata = MetaData()
github_inbox = Table(
    "github_inbox",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("delivery_id", String, nullable=False, unique=True),
    Column("source", String, nullable=False),
    Column("event", String, nullable=False),
    Column("action", String, nullable=False),
    Column("repository", String, nullable=False),
    Column("body", LargeBinary, nullable=False),
    Column("received_at", Float, nullable=False),
)
_INSERTS = {"sqlite": sqlite.insert, "postgresql": postgresql.insert}
#: Ids in one `IN (...)`, under SQLite's bound-variable limit.
_CHUNK = 500
#: The switch to WAL fails at once, without the busy timeout, while another connection opens or closes the database.
_WAL_ATTEMPTS = 20
#: Milliseconds a connection waits on another's lock: the listener, the reconcile pass, the consumer and agents' readers
#: share one file.
_BUSY_TIMEOUT_MS = 30_000


def _sqlite_pragmas(dbapi_connection: sqlite3.Connection, _record: object) -> None:
    dbapi_connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    dbapi_connection.execute("PRAGMA synchronous=NORMAL")


def _sqlite_wal(engine: Engine) -> None:
    # WAL lets readers run beside the one writer; the mode is kept in the file, so it is set once per open
    with engine.connect() as db:
        for attempt in range(_WAL_ATTEMPTS):
            try:
                db.exec_driver_sql("PRAGMA journal_mode=WAL")
                return
            except SQLAlchemyError:
                if attempt == _WAL_ATTEMPTS - 1:
                    raise
                time.sleep(0.05)


def _reason(error: SQLAlchemyError) -> str:
    # `str(error)` carries the INSERT's parameters, the raw body of a possibly private repository
    reason = str(getattr(error, "orig", None) or type(error).__name__)
    return reason.partition("\nDETAIL")[0]  # Postgres's DETAIL echoes the row


class SqlInbox:
    """Saves each delivery in one transaction: `INSERT ... ON CONFLICT (delivery_id) DO NOTHING`, then commit."""

    def __init__(self, database_url: str, migrate: Migrate, clock: Callable[[], float] = time.time) -> None:
        scheme = database_url.partition(":")[0].partition("+")[0]
        insert = _INSERTS.get(scheme)
        if insert is None:
            raise ValueError(f"github: database_url must be a sqlite or postgresql URL, not a {scheme!r} one")
        self._insert = insert
        self._clock = clock
        self.engine = create_engine(database_url)
        try:
            if scheme == "sqlite":
                event.listen(self.engine, "connect", _sqlite_pragmas)
                _sqlite_wal(self.engine)
            migrate(self.engine, _MIGRATIONS, VERSION_TABLE)
        except BaseException:
            self.engine.dispose()  # the `contexts` process retries `start`, which opens a new inbox
            raise

    def save(self, delivery: Delivery, source: str = "webhook") -> bool:
        statement = (
            self._insert(github_inbox)
            .values(
                delivery_id=delivery.delivery_id, source=source, event=delivery.event, action=delivery.action,
                repository=delivery.repository, body=delivery.body, received_at=self._clock(),
            )  # fmt: skip
            .on_conflict_do_nothing(index_elements=["delivery_id"])
        )
        try:
            with self.engine.begin() as db:
                return db.execute(statement).rowcount == 1
        except SQLAlchemyError as error:
            raise InboxError(_reason(error)) from None

    def known(self, delivery_ids: Collection[str]) -> set[str]:
        """The `delivery_ids` that have a row, whoever saved it."""
        wanted = list(delivery_ids)
        found: set[str] = set()
        with self.engine.connect() as db:
            for start in range(0, len(wanted), _CHUNK):
                chunk = wanted[start : start + _CHUNK]
                rows = db.execute(select(github_inbox.c.delivery_id).where(github_inbox.c.delivery_id.in_(chunk)))
                found.update(rows.scalars())
        return found
