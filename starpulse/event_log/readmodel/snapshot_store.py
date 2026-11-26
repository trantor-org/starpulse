"""The Board writer's stored snapshot: the encoded bodies and the deltas published since, kept in the instance store so
the API serves bytes it never builds."""

import gzip
import struct
import zlib
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import Connection, Engine, delete, func, insert, select, update

from starpulse.event_log.event_log import unpooled_engine
from starpulse.event_log.readmodel.tables import SNAPSHOT_TABLES, snapshot_deltas, snapshots
from starpulse.event_log.table_registry import empty_unless_stamped, stamped

#: The deltas kept behind the stored sequence, so a page that read the snapshot a moment ago still replays what followed;
#: a cursor older than that reads a fresh snapshot.
KEEP = 500
#: A body this size or smaller is stored as it is, and one over it with its gzip at level 1: the 4.9 MB snapshot takes
#: ~60 ms there against ~190 ms at level 6, which is 22% larger.
GZIP_MIN_BYTES = 64 * 1024
GZIP_LEVEL = 1


#: The sequence of a body stored outside the folds (`put`): a fold never moves it.
STANDALONE = -1


def _gzipped(body: bytes, deflated: dict[bytes, bytes] | None = None) -> bytes | None:
    """The gzip of `body` when it is over `GZIP_MIN_BYTES`. A body that names the `segments` it was joined from is
    deflated piece by piece, each ended on a byte boundary so the pieces concatenate into one stream: `deflated` holds
    the pieces of the last body, so a piece the body has again is not compressed again. Both give the same gzip member."""
    if len(body) <= GZIP_MIN_BYTES:
        return None
    pieces = getattr(body, "segments", None)
    if pieces is None or deflated is None:
        return gzip.compress(body, compresslevel=GZIP_LEVEL, mtime=0)
    parts = [(piece, deflated.get(piece) or _deflate(piece)) for piece in pieces if piece]
    deflated.clear()
    deflated.update(parts)
    return b"".join([_HEADER, *(deflate for _, deflate in parts), _END, struct.pack("<II", zlib.crc32(body), len(body) & 0xFFFFFFFF)])


def _deflate(piece: bytes) -> bytes:
    deflater = zlib.compressobj(GZIP_LEVEL, zlib.DEFLATED, -zlib.MAX_WBITS)
    return deflater.compress(piece) + deflater.flush(zlib.Z_FULL_FLUSH)


#: A gzip member's header as `gzip.compress` writes it, and the final empty block that ends its pieces' stream.
_HEADER = gzip.compress(b"", compresslevel=GZIP_LEVEL, mtime=0)[:10]
_END = b"\x03\x00"


def _store(db: Connection, view: str, seq: int, body: bytes, at: float, deflated: dict[bytes, bytes] | None = None) -> bool:
    """Store `body` as `view`; True when that inserted the view's row."""
    values = {"seq": seq, "body": body, "gzipped": _gzipped(body, deflated), "stored_at": at}
    if db.execute(update(snapshots).where(snapshots.c.view == view).values(**values)).rowcount:
        return False
    db.execute(insert(snapshots).values(view=view, **values))
    return True


#: The one stored snapshot body's row in `starpulse_snapshots`, which a store of the three bodies (`slim`, `full`,
#: `flows`) left rows beside.
LIVE = "live"


def build(engine: Engine, read_model: str) -> None:
    """Empty the stored snapshot and its deltas when they were not stored under this definition and read-model stamp: the
    Board writer stores a snapshot again at its start. One stored under them is left as it is."""
    empty_unless_stamped(engine, "snapshots", SNAPSHOT_TABLES, read_model)


def built(engine: Engine, read_model: str) -> bool:
    """Whether the stored snapshot is the one `build` leaves: stored under this definition and read-model stamp."""
    return stamped(engine, "snapshots", SNAPSHOT_TABLES, read_model)


class SnapshotStore:
    """`encode` draws the one body the API serves of a snapshot, stored with its gzip."""

    def __init__(self, engine: Engine, encode: Callable[[Any, dict], bytes], keep: int = KEEP) -> None:
        self._engine, self._encode, self.keep = engine, encode, keep
        self._held: dict = {}
        self._deflated: dict[bytes, bytes] = {}
        self._writer = unpooled_engine(engine)

    def save(self, changes: Sequence[tuple[str, dict]], snapshot: Any | None, at: float, current: bool = True) -> int:
        """Append `changes` as deltas, store `snapshot` with the sequence of the last one, and prune the deltas behind the
        window; all in one transaction. Returns that sequence. With no `snapshot` the stored one keeps its body, and
        moves to that sequence only when `current` (it already reflects the changes)."""
        body = None if snapshot is None else self._encode(snapshot, self._held)
        with self._writer.begin() as db:
            head = db.execute(select(func.max(snapshot_deltas.c.seq))).scalar() or 0
            if changes:
                db.execute(
                    insert(snapshot_deltas),
                    [{"seq": head + n, "kind": kind, "data": data} for n, (kind, data) in enumerate(changes, 1)],
                )
                head += len(changes)
            if body is None and current:
                db.execute(update(snapshots).where(snapshots.c.seq != STANDALONE).values(seq=head))
            if body is not None:
                if _store(db, LIVE, head, body, at, self._deflated):  # the first save: clear what the three-body store left
                    db.execute(delete(snapshots).where(snapshots.c.view != LIVE, snapshots.c.seq != STANDALONE))
            db.execute(delete(snapshot_deltas).where(snapshot_deltas.c.seq <= head - self.keep))
        return head

    def put(self, view: str, body: bytes, at: float) -> None:
        """Store `body` and its gzip as `view`, a body made outside the snapshot's folds (`STANDALONE`)."""
        with self._writer.begin() as db:
            _store(db, view, STANDALONE, body, at)

    def body(self, view: str = LIVE) -> tuple[int, bytes, bytes | None] | None:
        """The stored body of `view`, its gzip, and the sequence it reflects; None before the first fold."""
        with self._engine.connect() as db:
            row = db.execute(
                select(snapshots.c.seq, snapshots.c.body, snapshots.c.gzipped).where(snapshots.c.view == view)
            ).first()
        return None if row is None else (row.seq, row.body, row.gzipped)

    def stamp(self, view: str = LIVE) -> tuple[int, float] | None:
        """The sequence and the time of the stored body of `view`, read without the body: it changes when the body does,
        a rebuild at an unmoved sequence included. None before the first fold."""
        with self._engine.connect() as db:
            row = db.execute(select(snapshots.c.seq, snapshots.c.stored_at).where(snapshots.c.view == view)).first()
        return None if row is None else (row.seq, row.stored_at)

    def head(self) -> int:
        """The sequence of the newest delta, 0 while there is none."""
        with self._engine.connect() as db:
            return db.execute(select(func.max(snapshot_deltas.c.seq))).scalar() or 0

    def since(self, seq: int) -> list[tuple[int, str, dict]]:
        """The retained deltas after `seq`, oldest first, as (seq, kind, data)."""
        statement = select(snapshot_deltas).where(snapshot_deltas.c.seq > seq).order_by(snapshot_deltas.c.seq)
        with self._engine.connect() as db:
            return [(row.seq, row.kind, row.data) for row in db.execute(statement)]
