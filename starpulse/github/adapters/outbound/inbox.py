"""The `github_inbox` table and the SQLAlchemy `Inbox` that saves a delivery into it.

The inbox is its own database (`[github] database_url`, SQLite by default), never the event store, so the process that
faces the internet cannot write an event. Its schema is the Alembic chain in `migrations/`, run when an inbox opens.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Column, Float, Integer, LargeBinary, MetaData, String, Table, create_engine
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import SQLAlchemyError

from starpulse.event_log.migrate import migrate_chain
from starpulse.github.model.delivery import Delivery
from starpulse.github.ports.inbox import InboxError

__all__ = ["SqlInbox", "github_inbox"]

VERSION_TABLE = "github_alembic_version"
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


class SqlInbox:
    """Saves each delivery in one transaction: `INSERT ... ON CONFLICT (delivery_id) DO NOTHING`, then commit."""

    def __init__(self, database_url: str, clock: Callable[[], float] = time.time) -> None:
        scheme = database_url.partition(":")[0].partition("+")[0]
        insert = _INSERTS.get(scheme)
        if insert is None:
            raise ValueError(f"github: database_url must be a sqlite or postgresql URL, not a {scheme!r} one")
        self._insert = insert
        self._clock = clock
        self.engine = create_engine(database_url)
        try:
            migrate_chain(self.engine, _MIGRATIONS, VERSION_TABLE)
        except BaseException:
            self.engine.dispose()  # the `contexts` process retries `start`, which opens a new inbox
            raise

    def save(self, delivery: Delivery) -> bool:
        statement = (
            self._insert(github_inbox)
            .values(
                delivery_id=delivery.delivery_id, source="webhook", event=delivery.event, action=delivery.action,
                repository=delivery.repository, body=delivery.body, received_at=self._clock(),
            )  # fmt: skip
            .on_conflict_do_nothing(index_elements=["delivery_id"])
        )
        try:
            with self.engine.begin() as db:
                return db.execute(statement).rowcount == 1
        except SQLAlchemyError as error:
            # `str(error)` carries the INSERT's parameters, the raw body of a possibly private repository
            reason = str(getattr(error, "orig", None) or type(error).__name__)
            raise InboxError(reason.partition("\nDETAIL")[0]) from None  # Postgres's DETAIL echoes the row
