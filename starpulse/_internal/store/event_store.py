"""The event store's envelope, its append and its read."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from starpulse._internal.store.tables import outbox, stream_events


class StaleVersion(Exception):
    """An append named a head the stream no longer has; the caller rereads the stream and decides again."""


@dataclass(frozen=True)
class NewEvent:
    type: str
    payload: Mapping[str, Any]
    actor: str
    writer: str
    schema_version: int = 1
    definition_hash: str | None = None
    causation_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class StoredEvent:
    event_id: str
    subject_kind: str
    subject_id: str
    version: int
    type: str
    schema_version: int
    at: float
    actor: str
    writer: str
    definition_hash: str | None
    causation_id: str | None
    correlation_id: str | None
    payload: Mapping[str, Any]
    position: int = 0
    """The Event's place in the order every stream was appended in; 0 on an Event not yet stored."""


class Upcasters:
    """How a stored payload of an older schema version reads as the newest: one function per (type, version), applied
    in turn. Stored Events are never rewritten."""

    def __init__(self) -> None:
        self._steps: dict[tuple[str, int], Callable[[dict[str, Any]], dict[str, Any]]] = {}

    def register(self, type: str, from_version: int, upcast: Callable[[dict[str, Any]], dict[str, Any]]) -> None:
        """Read a `type` payload of `from_version` as `from_version + 1` through `upcast`."""
        self._steps[(type, from_version)] = upcast

    def apply(self, event: StoredEvent) -> StoredEvent:
        """`event` read at the newest schema version the registered steps reach."""
        version, payload = event.schema_version, dict(event.payload)
        while (step := self._steps.get((event.type, version))) is not None:
            payload, version = step(payload), version + 1
        return replace(event, schema_version=version, payload=payload)


class EventStore:
    """The streams in one database. An append is a compare-and-swap on the stream head and fails closed: it raises
    rather than lose an Event."""

    def __init__(self, engine: Engine, upcasters: Upcasters | None = None) -> None:
        self._engine = engine
        self._upcasters = upcasters or Upcasters()

    def append(
        self,
        subject_kind: str,
        subject_id: str,
        expected_version: int,
        events: Sequence[NewEvent],
        *,
        at: float | None = None,
        connection: Connection | None = None,
    ) -> list[StoredEvent]:
        """Write `events` as the versions after `expected_version`, the head the caller read (0 for a new stream), with
        an outbox row each in the same transaction. Raises `StaleVersion` when the head has moved. With `connection`,
        the write joins the caller's transaction, so appends to several streams commit or roll back together."""
        at = time.time() if at is None else at
        rows = [
            {
                "event_id": uuid.uuid4().hex,
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "version": expected_version + offset,
                "type": event.type,
                "schema_version": event.schema_version,
                "at": at,
                "actor": event.actor,
                "writer": event.writer,
                "definition_hash": event.definition_hash,
                "causation_id": event.causation_id,
                "correlation_id": event.correlation_id,
                "payload": dict(event.payload),
            }
            for offset, event in enumerate(events, start=1)
        ]
        try:
            if connection is None:
                with self._engine.begin() as db:
                    positions = self._insert(db, subject_kind, subject_id, expected_version, rows)
            else:
                positions = self._insert(connection, subject_kind, subject_id, expected_version, rows)
        except IntegrityError as exc:
            raise StaleVersion(f"{subject_kind} {subject_id} moved past version {expected_version}") from exc
        return [self._upcasters.apply(_stored(row | {"id": positions[row["event_id"]]})) for row in rows]

    def _insert(
        self, db: Connection, subject_kind: str, subject_id: str, expected_version: int, rows: list[dict[str, Any]]
    ) -> dict[str, int]:
        head = self._head(db, subject_kind, subject_id)
        if head != expected_version:
            raise StaleVersion(f"{subject_kind} {subject_id} is at version {head}, not {expected_version}")
        db.execute(insert(stream_events), rows)
        db.execute(insert(outbox), [{"event_id": row["event_id"]} for row in rows])
        ids = select(stream_events.c.event_id, stream_events.c.id).where(
            stream_events.c.event_id.in_([row["event_id"] for row in rows])
        )
        return dict(db.execute(ids).tuples().all())

    def read(self, subject_kind: str, subject_id: str, after: int = 0) -> list[StoredEvent]:
        """The stream's Events after version `after`, in order, at their newest schema version."""
        query = (
            select(stream_events)
            .where(
                stream_events.c.subject_kind == subject_kind,
                stream_events.c.subject_id == subject_id,
                stream_events.c.version > after,
            )
            .order_by(stream_events.c.version)
        )
        with self._engine.connect() as db:
            return [self._upcasters.apply(_stored(row)) for row in db.execute(query).mappings()]

    def read_after(self, subject_kind: str, position: int, limit: int = 1000) -> list[StoredEvent]:
        """Up to `limit` Events of every `subject_kind` stream after `position`, in the order they were appended."""
        query = (
            select(stream_events)
            .where(stream_events.c.subject_kind == subject_kind, stream_events.c.id > position)
            .order_by(stream_events.c.id)
            .limit(limit)
        )
        with self._engine.connect() as db:
            return [self._upcasters.apply(_stored(row)) for row in db.execute(query).mappings()]

    def head(self, subject_kind: str, subject_id: str) -> int:
        """The stream's newest version, 0 when it has none."""
        with self._engine.connect() as db:
            return self._head(db, subject_kind, subject_id)

    def outbox_pending(self, limit: int = 100) -> list[StoredEvent]:
        """The oldest Events the stream has not acknowledged."""
        query = (
            select(stream_events)
            .join(outbox, outbox.c.event_id == stream_events.c.event_id)
            .where(outbox.c.sent_at.is_(None))
            .order_by(stream_events.c.id)
            .limit(limit)
        )
        with self._engine.connect() as db:
            return [self._upcasters.apply(_stored(row)) for row in db.execute(query).mappings()]

    def mark_sent(self, event_ids: Sequence[str]) -> None:
        """Record that the stream acknowledged `event_ids`; one already marked keeps its first time."""
        with self._engine.begin() as db:
            db.execute(
                update(outbox)
                .where(outbox.c.event_id.in_(event_ids), outbox.c.sent_at.is_(None))
                .values(sent_at=time.time())
            )

    @staticmethod
    def _head(db: Connection, subject_kind: str, subject_id: str) -> int:
        query = select(func.coalesce(func.max(stream_events.c.version), 0)).where(
            stream_events.c.subject_kind == subject_kind, stream_events.c.subject_id == subject_id
        )
        return db.execute(query).scalar_one()


def _stored(row: Mapping[str, Any]) -> StoredEvent:
    values = {name: row[name] for name in StoredEvent.__dataclass_fields__ if name != "position"}
    return StoredEvent(position=row.get("id", 0), **values)
