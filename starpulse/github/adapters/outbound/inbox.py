"""The `github_inbox` table and the SQLAlchemy `Inbox` that saves a delivery into it.

The inbox lives in the main store: its tables are durable tables of the main chain (`event_log/migrations`), and the
engine an inbox is built on is the one that opens that store.
"""

import time
from collections.abc import Callable, Collection

from sqlalchemy import Column, Float, Index, Integer, LargeBinary, MetaData, String, Table, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from starpulse.github.model.delivery import Delivery
from starpulse.github.ports.inbox import InboxError

__all__ = ["INSERTS", "SqlInbox", "github_inbox", "metadata"]

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
    Index("github_inbox_fact", "repository", "event", "action", "received_at"),
)
INSERTS = {"sqlite": sqlite.insert, "postgresql": postgresql.insert}
#: Ids in one `IN (...)`, under SQLite's bound-variable limit.
_CHUNK = 500


def _reason(error: SQLAlchemyError) -> str:
    # `str(error)` carries the INSERT's parameters, the raw body of a possibly private repository
    reason = str(getattr(error, "orig", None) or type(error).__name__)
    return reason.partition("\nDETAIL")[0]  # Postgres's DETAIL echoes the row


class SqlInbox:
    """Saves each delivery in one transaction: `INSERT ... ON CONFLICT (delivery_id) DO NOTHING`, then commit."""

    def __init__(self, engine: Engine, clock: Callable[[], float] = time.time) -> None:
        self._insert = INSERTS[engine.dialect.name]
        self._clock = clock
        self.engine = engine

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

    def bodies(self, delivery: Delivery, start: float, end: float) -> list[bytes]:
        c = github_inbox.c
        with self.engine.connect() as db:
            rows = db.execute(
                select(c.body).where(
                    c.event == delivery.event, c.action == delivery.action, c.repository == delivery.repository,
                    c.received_at.between(start, end),
                )  # fmt: skip
            )
            return list(rows.scalars())
