"""The Board writer's stored snapshot: the encoded bodies and the deltas published since, kept in the instance store so
the API serves bytes it never builds."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sqlalchemy import Engine, delete, func, insert, select, update

from starpulse.event_log.readmodel.tables import snapshot_deltas, snapshots

#: The deltas kept behind the stored sequence, so a page that read the snapshot a moment ago still replays what followed;
#: a cursor older than that reads a fresh snapshot.
KEEP = 500


class SnapshotStore:
    """`encode` draws the bodies of a snapshot, by view (`slim`, `full`)."""

    def __init__(self, engine: Engine, encode: Callable[[Any, dict], Mapping[str, bytes]], keep: int = KEEP) -> None:
        self._engine, self._encode, self._keep = engine, encode, keep
        self._held: dict = {}

    def save(self, changes: Sequence[tuple[str, dict]], snapshot: Any | None, at: float) -> int:
        """Append `changes` as deltas, store `snapshot` (None: the one stored already reflects them) with the sequence of
        the last one, and prune the deltas behind the window; all in one transaction. Returns that sequence."""
        bodies = None if snapshot is None else self._encode(snapshot, self._held)
        with self._engine.begin() as db:
            head = db.execute(select(func.max(snapshot_deltas.c.seq))).scalar() or 0
            if changes:
                db.execute(
                    insert(snapshot_deltas),
                    [{"seq": head + n, "kind": kind, "data": data} for n, (kind, data) in enumerate(changes, 1)],
                )
                head += len(changes)
            if bodies is None:
                db.execute(update(snapshots).values(seq=head))
            for view, body in (bodies or {}).items():
                values = {"seq": head, "body": body, "stored_at": at}
                if not db.execute(update(snapshots).where(snapshots.c.view == view).values(**values)).rowcount:
                    db.execute(insert(snapshots).values(view=view, **values))
            db.execute(delete(snapshot_deltas).where(snapshot_deltas.c.seq <= head - self._keep))
        return head

    def body(self, view: str) -> tuple[int, bytes] | None:
        """The stored body of `view` with the sequence it reflects; None before the first fold."""
        with self._engine.connect() as db:
            row = db.execute(select(snapshots.c.seq, snapshots.c.body).where(snapshots.c.view == view)).first()
        return None if row is None else (row.seq, row.body)

    def since(self, seq: int) -> list[tuple[int, str, dict]]:
        """The retained deltas after `seq`, oldest first, as (seq, kind, data)."""
        statement = select(snapshot_deltas).where(snapshot_deltas.c.seq > seq).order_by(snapshot_deltas.c.seq)
        with self._engine.connect() as db:
            return [(row.seq, row.kind, row.data) for row in db.execute(statement)]
