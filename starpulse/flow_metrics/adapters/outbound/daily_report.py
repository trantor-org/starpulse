"""The daily report: per machine, local day and transition, the moves recorded and the seconds each had spent in the
state it left.

`add` is called by the recorder in the transaction that writes a move, so a row never holds a move the history lacks
and a move recorded twice is counted once. `statement` is the one range read over the primary key `(machine, day,
from_state, to_state)`; it names no event table, so a range of any length costs the days in it.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Select, func, literal, select
from sqlalchemy.dialects import sqlite

from starpulse.event_log.tables import daily_report as _report

__all__ = ["add", "day_of", "read", "statement"]

#: Days are cut at local midnight here, as the operator reads them.
ZONE = ZoneInfo("America/Phoenix")
#: The characters of a `YYYY-MM-DD` day that name each bucket.
_PREFIX = {"day": 10, "month": 7, "year": 4}


def day_of(at: float) -> str:
    return datetime.fromtimestamp(at, ZONE).date().isoformat()


def add(db: Connection, machine: str, at: float, before: str, after: str, seconds: float) -> None:
    """Count one move of `machine` at `at` from `before` to `after` ('' when unknown), `seconds` after the one before."""
    c = _report.c
    row = sqlite.insert(_report).values(
        machine=machine, day=day_of(at), from_state=before, to_state=after, count=1, seconds=max(seconds, 0.0)
    )
    db.execute(
        row.on_conflict_do_update(
            index_elements=[c.machine, c.day, c.from_state, c.to_state],
            set_={"count": c.count + 1, "seconds": c.seconds + row.excluded.seconds},
        )
    )


def statement(machine: str, since: str, until: str, *, state: str | None = None, bucket: str = "range") -> Select:
    """The sum of `machine`'s rows from day `since` to `until`, both inclusive, per `bucket` (`day`, `month`, `year` or
    `range`); with a `state`, only the moves out of it."""
    c = _report.c
    key = literal("range") if bucket == "range" else func.substr(c.day, 1, _PREFIX[bucket])
    query = (
        select(key.label("bucket"), func.sum(c.count).label("count"), func.sum(c.seconds).label("seconds"))
        .where(c.machine == machine, c.day.between(since, until))
        .group_by(key)
        .order_by(key)
    )
    return query if state is None else query.where(c.from_state == state)


def read(db: Connection, machine: str, since: str, until: str, *, state: str | None, bucket: str) -> list[dict]:
    """The rows `statement` sums; no row for a bucket with no moves, so a range with none reads `[]`."""
    rows = db.execute(statement(machine, since, until, state=state, bucket=bucket)).all()
    return [{"bucket": b, "count": int(n), "seconds": float(s)} for b, n, s in rows if n is not None]
