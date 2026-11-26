"""The event store's envelope, its append and its read."""

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import ColumnElement, Connection, Engine, func, insert, select
from sqlalchemy.exc import IntegrityError

from starpulse.event_log.store.tables import stream_events


def lacks_history(subject_kind: str, subject_id: ColumnElement[str]) -> ColumnElement[bool]:
    """A filter keeping the rows whose `subject_id` has no Event of `subject_kind`; one `NOT EXISTS`, so a query reads the
    subjects without a stream and none other."""
    return ~select(stream_events.c.id).where(
        stream_events.c.subject_kind == subject_kind,
        stream_events.c.subject_id == subject_id,
        stream_events.c.version == 1,
    ).exists()


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
        if (event.type, event.schema_version) not in self._steps:
            return event
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
        """Write `events` as the versions after `expected_version`, the head the caller read (0 for a new stream).
        Raises `StaleVersion` when the head has moved. With `connection`, the write joins the caller's transaction, so
        appends to several streams commit or roll back together."""
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
        ids = select(stream_events.c.event_id, stream_events.c.id).where(
            stream_events.c.event_id.in_([row["event_id"] for row in rows])
        )
        return dict(db.execute(ids).tuples().all())

    def read(self, subject_kind: str, subject_id: str, after: int = 0) -> list[StoredEvent]:
        """The stream's Events after version `after`, in order, at their newest schema version."""
        with self._engine.connect() as db:
            return self.read_in(db, subject_kind, subject_id, after)

    def read_in(self, db: Connection, subject_kind: str, subject_id: str, after: int = 0) -> list[StoredEvent]:
        """`read` inside the caller's transaction `db`."""
        query = (
            select(stream_events)
            .where(
                stream_events.c.subject_kind == subject_kind,
                stream_events.c.subject_id == subject_id,
                stream_events.c.version > after,
            )
            .order_by(stream_events.c.version)
        )
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

    def head_in(self, db: Connection, subject_kind: str, subject_id: str) -> int:
        """`head` read inside the caller's transaction `db`."""
        return self._head(db, subject_kind, subject_id)

    def heads(self, subject_kind: str) -> dict[str, int]:
        """The newest version of every stream of `subject_kind`, in one query."""
        query = (
            select(stream_events.c.subject_id, func.max(stream_events.c.version))
            .where(stream_events.c.subject_kind == subject_kind)
            .group_by(stream_events.c.subject_id)
        )
        with self._engine.connect() as db:
            return {subject: version for subject, version in db.execute(query)}

    @staticmethod
    def _head(db: Connection, subject_kind: str, subject_id: str) -> int:
        query = select(func.coalesce(func.max(stream_events.c.version), 0)).where(
            stream_events.c.subject_kind == subject_kind, stream_events.c.subject_id == subject_id
        )
        return db.execute(query).scalar_one()


def _stored(row: Mapping[str, Any]) -> StoredEvent:
    values = {name: row[name] for name in StoredEvent.__dataclass_fields__ if name != "position"}
    return StoredEvent(position=row.get("id", 0), **values)
