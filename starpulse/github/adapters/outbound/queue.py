"""The `github_inbox_state` table and the SQLAlchemy `Queue` of one consumer over it.

A row is one delivery's state for one consumer: `pending` until it is `done`, `skipped` (nothing to do) or `dead` (the
operator requeues or dismisses it). A delivery the consumer has not seen has no row; `claim` makes it one.
"""

import time
from collections.abc import Callable

from sqlalchemy import Column, Float, Index, Integer, String, Table, and_, delete, exists, func, literal, select, update
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.engine import Engine

from starpulse.github.adapters.outbound.inbox import github_inbox as inbox
from starpulse.github.adapters.outbound.inbox import metadata
from starpulse.github.model.delivery import Delivery
from starpulse.github.model.events import BUDGET, RETENTION, backoff
from starpulse.github.ports.events import Entry

__all__ = ["SqlQueue", "github_inbox_state"]

#: Inbox ids one seeding transaction covers.
_SEED_WINDOW = 500

github_inbox_state = Table(
    "github_inbox_state",
    metadata,
    Column("delivery_id", String, primary_key=True),
    Column("consumer", String, primary_key=True),
    Column("status", String, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("next_attempt_at", Float, nullable=False),
    Column("last_error", String),
    Column("updated_at", Float, nullable=False),
    Index("ix_github_inbox_state_due", "consumer", "status", "next_attempt_at"),
)
state = github_inbox_state.c
_INSERTS = {"sqlite": sqlite.insert, "postgresql": postgresql.insert}
_SEED = ["delivery_id", "consumer", "status", "attempts", "next_attempt_at", "updated_at"]


class SqlQueue:
    """The deliveries of `consumer`: claim the due ones, then complete, skip or fail each."""

    def __init__(self, engine: Engine, consumer: str, clock: Callable[[], float] = time.time) -> None:
        self._engine, self._consumer, self._clock = engine, consumer, clock
        self._insert = _INSERTS[engine.dialect.name]
        self._seeded = 0  # the newest inbox id this queue has seeded: a claim looks only past it

    def _mine(self, delivery_id: str):  # noqa: ANN202
        return and_(state.delivery_id == delivery_id, state.consumer == self._consumer)

    def _set(self, delivery_id: str, *, only: str | None = None, **values: object) -> bool:
        where = self._mine(delivery_id) if only is None else and_(self._mine(delivery_id), state.status == only)
        with self._engine.begin() as db:
            return db.execute(update(github_inbox_state).where(where).values(updated_at=self._clock(), **values)).rowcount == 1

    def claim(self, limit: int = 100) -> list[Entry]:
        now = self._clock()
        seen = exists().where(state.delivery_id == inbox.c.delivery_id, state.consumer == self._consumer)
        newest = select(func.coalesce(func.max(inbox.c.id), 0))
        due = (
            select(inbox, state.attempts)
            .join(github_inbox_state, state.delivery_id == inbox.c.delivery_id)
            .where(state.consumer == self._consumer, state.status == "pending", state.next_attempt_at <= now)
            .order_by(inbox.c.id)
            .limit(limit)
        )
        with self._engine.connect() as db:
            seeded = db.execute(newest).scalar_one()
        # SQLite has one writer, so ids commit in order; a Postgres sequence does not, and always looks from the start.
        # An inbox that lost its newest rows reuses their ids.
        sqlite_db = self._engine.dialect.name == "sqlite"
        after = self._seeded if sqlite_db and self._seeded <= seeded else 0
        # A seed holds SQLite's one write lock while it scans: a first claim over a multi-GB inbox took over a minute and
        # dropped the listener's saves, so a window of ids is one transaction and the listener writes between windows.
        window = _SEED_WINDOW if sqlite_db else max(seeded - after, 1)
        for start in range(after, seeded, window):
            unseen = select(
                inbox.c.delivery_id, literal(self._consumer), literal("pending"), literal(0), literal(now), literal(now)
            ).where(inbox.c.id > start, inbox.c.id <= min(start + window, seeded), ~seen)
            with self._engine.begin() as db:
                db.execute(self._insert(github_inbox_state).from_select(_SEED, unseen).on_conflict_do_nothing())
        with self._engine.connect() as db:
            rows = db.execute(due).all()
        self._seeded = seeded
        return [
            Entry(Delivery(row.delivery_id, row.event, row.action, row.repository, bytes(row.body)), row.attempts)
            for row in rows
        ]

    def due_in(self) -> float | None:
        """Seconds until the earliest pending delivery is due (0 when one is due now), or `None` with none pending."""
        with self._engine.connect() as db:
            earliest = db.execute(
                select(func.min(state.next_attempt_at)).where(state.consumer == self._consumer, state.status == "pending")
            ).scalar_one()
        return None if earliest is None else max(0.0, earliest - self._clock())

    def complete(self, delivery_id: str) -> None:
        self._set(delivery_id, status="done", last_error=None)

    def skip(self, delivery_id: str, reason: str) -> None:
        self._set(delivery_id, status="skipped", last_error=reason)

    def fail(self, delivery_id: str, error: str, *, fatal: bool = False, exhausted: str = "dead") -> str:
        with self._engine.begin() as db:
            spent = db.execute(select(state.attempts).where(self._mine(delivery_id))).scalar_one() + 1
            status = "dead" if fatal else exhausted if spent >= BUDGET else "pending"
            db.execute(
                update(github_inbox_state)
                .where(self._mine(delivery_id))
                .values(
                    status=status, attempts=spent, last_error=error, updated_at=self._clock(),
                    next_attempt_at=self._clock() + backoff(spent),
                )  # fmt: skip
            )
        return status

    def defer(self, delivery_id: str, error: str, until: float) -> None:
        self._set(delivery_id, status="pending", last_error=error, next_attempt_at=until)

    def requeue(self, delivery_id: str) -> bool:
        """Make a dead row pending again with its attempts spent anew; `False` for a row that is not dead."""
        return self._set(delivery_id, only="dead", status="pending", attempts=0, next_attempt_at=self._clock(), last_error=None)

    def dismiss(self, delivery_id: str) -> bool:
        """Skip a dead row for good, keeping its last error; `False` for a row that is not dead."""
        return self._set(delivery_id, only="dead", status="skipped")

    def dead_counts(self) -> dict[str, int]:
        with self._engine.connect() as db:
            dead = db.execute(
                select(func.count()).where(state.consumer == self._consumer, state.status == "dead")
            ).scalar_one()
        return {self._consumer: dead}

    def purge(self) -> None:
        """Delete the done and skipped rows older than `RETENTION`, and the inbox rows no other row still needs.

        The newest inbox row stays: SQLite hands the next save `max(id) + 1`, so a purge that emptied the table would
        reuse ids below a claim's cursor, in any process, and that claim would never seed the new deliveries.
        """
        old = and_(
            state.consumer == self._consumer, state.status.in_(("done", "skipped")), state.updated_at < self._clock() - RETENTION
        )
        gone = select(state.delivery_id).where(old)
        kept = select(state.delivery_id).where(~old)
        with self._engine.begin() as db:
            newest = select(func.max(inbox.c.id)).scalar_subquery()
            db.execute(delete(inbox).where(inbox.c.delivery_id.in_(gone), inbox.c.delivery_id.not_in(kept), inbox.c.id < newest))
            db.execute(delete(github_inbox_state).where(old))
