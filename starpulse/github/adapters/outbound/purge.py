"""The inbox purge, whole-inbox rather than per consumer: no consumer's own rows can pin another's body.

Past `RETENTION` a delivery no consumer has pending leaves the live inbox, archived first when a dead row still names
it (`restore` brings it back for a `requeue`). A delivery every consumer skipped keeps no body once `SKIP_GRACE` has
let a slow consumer seed it, except for the events a reader or the reconcile reads back. A delivery no consumer holds a row
for (one none handles) counts as skipped once a consumer holds a row at or past it.
"""

import base64
import gzip
import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, and_, delete, exists, func, select, update

from starpulse.github.adapters.outbound.inbox import INSERTS, github_inbox as inbox
from starpulse.github.adapters.outbound.queue import github_inbox_state, state
from starpulse.github.model.events import RETENTION

__all__ = ["SKIP_GRACE", "purge", "restore"]

#: How long a skipped delivery keeps its body, so a consumer that seeds late still reads it.
SKIP_GRACE = 6 * 3600

#: The events whose bodies a reader (`inbox_reader`) or the reconcile reads, skipped or not.
_READ = ("pull_request", "check_run", "check_suite", "deployment_status")

_BATCH = 2000  # rows a transaction, so the listener saves between them


def _has(*status: str):  # noqa: ANN202
    named = state.delivery_id == inbox.c.delivery_id
    return exists().where(and_(named, state.status.in_(status)) if status else named)


def _newest_held():  # noqa: ANN202
    """The newest inbox id some consumer holds a row for: a consumer seeds only past its own newest row, so a rowless
    delivery at or below it was seen and is not owed a body."""
    other = inbox.alias()
    return (
        select(other.c.id)
        .where(exists().where(state.delivery_id == other.c.delivery_id))
        .order_by(other.c.id.desc())
        .limit(1)
        .scalar_subquery()
    )


def purge(engine: Engine, archive: Path, clock: Callable[[], float]) -> None:
    """Empty the bodies every consumer skipped, then delete the deliveries past `RETENTION` that none has pending.

    The newest inbox row stays: SQLite hands the next save `max(id) + 1`, so a purge that emptied the table would
    reuse ids below a claim's cursor, in any process, and that claim would never seed the new deliveries.
    """
    now = clock()
    skipped = and_(
        inbox.c.received_at < now - SKIP_GRACE,
        inbox.c.event.not_in(_READ),
        func.length(inbox.c.body) > 0,
        ~exists().where(state.delivery_id == inbox.c.delivery_id, state.status != "skipped"),
        inbox.c.id <= _newest_held(),
    )
    old = and_(inbox.c.received_at < now - RETENTION, ~_has("pending"), inbox.c.id < select(func.max(inbox.c.id)).scalar_subquery())
    last = 0
    while ids := _ids(engine, skipped, last):
        with engine.begin() as db:
            db.execute(update(inbox).where(inbox.c.id.in_(ids)).values(body=b""))
        last = ids[-1]
    last = 0
    while True:
        with engine.connect() as db:
            rows = db.execute(select(inbox, _has("dead").label("dead")).where(old, inbox.c.id > last).order_by(inbox.c.id).limit(_BATCH)).all()
        if not rows:
            return
        if dead := [row for row in rows if row.dead]:
            _archive(archive, dead)
        with engine.begin() as db:
            # a dead row requeued since the read is pending now: its body stays
            db.execute(delete(inbox).where(inbox.c.id.in_([row.id for row in rows]), ~_has("pending")))
            gone = ~exists().where(inbox.c.delivery_id == state.delivery_id)
            db.execute(
                delete(github_inbox_state).where(
                    state.delivery_id.in_([row.delivery_id for row in rows]), state.status.in_(("done", "skipped")), gone
                )
            )
        last = rows[-1].id


def _ids(engine: Engine, where: Any, after: int) -> list[int]:
    with engine.connect() as db:
        return list(db.scalars(select(inbox.c.id).where(where, inbox.c.id > after).order_by(inbox.c.id).limit(_BATCH)))


def _archive(directory: Path, rows: list[Any]) -> None:
    """Append each row to the gzip JSONL file of its UTC day and fsync, before the caller deletes it."""
    days: dict[str, list[str]] = {}
    for row in rows:
        entry = {name: getattr(row, name) for name in ("id", "delivery_id", "source", "event", "action", "repository", "received_at")}
        entry["body"] = base64.b64encode(row.body).decode()
        day = datetime.fromtimestamp(row.received_at, UTC).strftime("%Y-%m-%d")
        days.setdefault(day, []).append(json.dumps(entry, separators=(",", ":")) + "\n")
    directory.mkdir(parents=True, exist_ok=True)
    for day, lines in days.items():
        with (directory / f"{day}.jsonl.gz").open("ab") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb") as member:  # a gzip file may hold several members
                member.write("".join(lines).encode())
            raw.flush()
            os.fsync(raw.fileno())


def restore(engine: Engine, archive: Path, delivery_id: str) -> bool:
    """Put an archived delivery back into the live inbox under a new id; `False` when no archive file holds it."""
    for path in sorted(archive.glob("*.jsonl.gz")):
        with gzip.open(path, "rt") as lines:
            for line in lines:
                if delivery_id not in line:
                    continue
                entry = json.loads(line)
                if entry["delivery_id"] != delivery_id:
                    continue
                entry.pop("id")
                entry["body"] = base64.b64decode(entry["body"])
                with engine.begin() as db:
                    db.execute(INSERTS[engine.dialect.name](inbox).values(**entry).on_conflict_do_nothing(index_elements=["delivery_id"]))
                return True
    return False
