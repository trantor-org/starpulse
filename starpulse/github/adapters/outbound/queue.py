"""The `github_inbox_state` table and the SQLAlchemy `Queue` of one consumer over it.

A row is one delivery's state for one consumer: `pending` until it is `done`, `skipped` (nothing to do) or `dead` (the
operator requeues or dismisses it). A delivery the consumer has not seen has no row; `claim` makes it one.
"""

from __future__ import annotations

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

    def _mine(self, delivery_id: str):  # noqa: ANN202
        return and_(state.delivery_id == delivery_id, state.consumer == self._consumer)

    def _set(self, delivery_id: str, *, only: str | None = None, **values: object) -> bool:
        where = self._mine(delivery_id) if only is None else and_(self._mine(delivery_id), state.status == only)
        with self._engine.begin() as db:
            return db.execute(update(github_inbox_state).where(where).values(updated_at=self._clock(), **values)).rowcount == 1

    def claim(self, limit: int = 100) -> list[Entry]:
        now = self._clock()
        seen = exists().where(state.delivery_id == inbox.c.delivery_id, state.consumer == self._consumer)
        unseen = select(
            inbox.c.delivery_id, literal(self._consumer), literal("pending"), literal(0), literal(now), literal(now)
        ).where(~seen)
        seed = self._insert(github_inbox_state).from_select(_SEED, unseen).on_conflict_do_nothing()
        due = (
            select(inbox, state.attempts)
            .join(github_inbox_state, state.delivery_id == inbox.c.delivery_id)
            .where(state.consumer == self._consumer, state.status == "pending", state.next_attempt_at <= now)
            .order_by(inbox.c.id)
            .limit(limit)
        )
        with self._engine.begin() as db:
            db.execute(seed)
            rows = db.execute(due).all()
        return [
            Entry(Delivery(row.delivery_id, row.event, row.action, row.repository, bytes(row.body)), row.attempts)
            for row in rows
        ]

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
        """Delete the done and skipped rows older than `RETENTION`, and the inbox rows no other row still needs."""
        old = and_(
            state.consumer == self._consumer, state.status.in_(("done", "skipped")), state.updated_at < self._clock() - RETENTION
        )
        gone = select(state.delivery_id).where(old)
        kept = select(state.delivery_id).where(~old)
        with self._engine.begin() as db:
            db.execute(delete(inbox).where(inbox.c.delivery_id.in_(gone), inbox.c.delivery_id.not_in(kept)))
            db.execute(delete(github_inbox_state).where(old))
