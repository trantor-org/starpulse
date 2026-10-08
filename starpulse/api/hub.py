"""Hub mode: the same package served from a Postgres history, started by `starpulse serve --hub`.

This module and what it imports (Alembic, the Postgres driver) are the hub extras (`pip install 'starpulse[hub]'`).
Only `serve --hub` imports it, so an IC instance on SQLite runs without them.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import Connection, Engine, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from starpulse.domain.transitions import Table
from starpulse.store.events import STREAM
from starpulse.store.tables import day_rollups, events

logger = logging.getLogger(__name__)

__all__ = [
    "VERSION_TABLE",
    "HubError",
    "enforce_retention",
    "ensure_partitions",
    "keep",
    "maintain",
    "partition_name",
    "prepare",
    "rollup_day",
]

#: Where the database records the revision it is at, named so it never meets a host project's own Alembic table.
VERSION_TABLE = "starpulse_alembic_version"
_MIGRATIONS = Path(__file__).parents[1] / "store" / "migrations"


class HubError(ValueError):
    """The config cannot run a hub; the message says what to change."""


def prepare(database_url: str | None) -> None:
    """Bring the hub's Postgres database to the latest schema; a config that names none is refused."""
    try:
        postgres = database_url is not None and make_url(database_url).get_backend_name() == "postgresql"
    except ArgumentError:
        postgres = False
    if not postgres or database_url is None:
        raise HubError("hub mode needs a Postgres database_url (postgresql+psycopg://...) in the config")
    _upgrade(database_url)


def _upgrade(url: str) -> None:
    """Run every revision the database has not yet seen, in one transaction (Postgres DDL rolls back)."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(_MIGRATIONS))
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    except SQLAlchemyError as exc:
        raise HubError(f"cannot bring the hub database to the latest schema: {exc.__class__.__name__}: {exc}") from exc
    finally:
        engine.dispose()


def partition_name(day: date) -> str:
    """The partition of `starpulse_events` that holds `day`, a UTC day of the events' `at` clock."""
    return f"starpulse_events_{day:%Y%m%d}"


def _day_start(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())


def ensure_partitions(engine: Engine, *, today: date, ahead: int = 1) -> None:
    """Create the partitions for `today` and the `ahead` days after it that do not exist yet, so an insert at the
    next midnight finds its partition already there."""
    with engine.begin() as db:
        for offset in range(ahead + 1):
            day = today + timedelta(days=offset)
            db.execute(
                text(
                    f"CREATE TABLE IF NOT EXISTS {partition_name(day)} PARTITION OF starpulse_events "
                    f"FOR VALUES FROM ({_day_start(day)}) TO ({_day_start(day + timedelta(days=1))})"
                )
            )


def _partition_days(db: Connection) -> list[date]:
    """The days `starpulse_events` has a partition for, oldest first."""
    names = db.execute(
        text(
            "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
            "WHERE i.inhparent = 'starpulse_events'::regclass"
        )
    ).scalars()
    return sorted(datetime.strptime(name.removeprefix("starpulse_events_"), "%Y%m%d").date() for name in names)


def rollup_day(db: Connection, day: date, machines: Mapping[str, Table]) -> None:
    """Write `day`'s rollup rows from its raw machine events, replacing any an earlier run wrote.

    Each event is run through its machine's transitions as the live feed does. An event that leaves a task or run
    where it was (a loop) or that no machine row names is skipped; the others enter a state, counted against the
    `team` the entering event names (`""` when it names none). A state's seconds run until the next event that moves
    that task or run out of it, which may sit in a later partition; one still in it counts as open.
    """
    start, end = _day_start(day), _day_start(day + timedelta(days=1))
    totals: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0, 0, 0.0])
    held: dict[tuple[str, str], tuple[str, float, str]] = {}  # (machine, key) -> state, entered at, team

    def step(row, current: Mapping[tuple[str, str], tuple[str, float, str]]) -> tuple[tuple[str, str], str] | None:
        """The (machine, key) slot and the state this row moves it into, or None when it moves nothing."""
        fields = row.fields
        machine, key = fields.get("machine"), fields.get("task") or fields.get("run")
        if (table := machines.get(machine)) is None or key is None:
            return None
        slot = (machine, key)
        before = current[slot][0] if slot in current else None
        state = table.target(before, fields.get("event"))
        return None if state is None or state == before else (slot, state)

    day_rows = select(events.c.fields, events.c.at).where(
        events.c.stream == STREAM, events.c.at >= start, events.c.at < end
    )
    for row in db.execute(day_rows.order_by(events.c.at, events.c.id)):
        if (moved := step(row, held)) is None:
            continue
        slot, state = moved
        if slot in held:
            before, entered, team = held[slot]
            totals[team, slot[0], before][2] += row.at - entered
        team = row.fields.get("team", "")
        held[slot] = (state, row.at, team)
        totals[team, slot[0], state][0] += 1
    waiting = dict(held)
    later = select(events.c.fields, events.c.at).where(events.c.stream == STREAM, events.c.at >= end)
    for row in db.execute(later.order_by(events.c.at, events.c.id)):
        if not waiting:
            break
        if (moved := step(row, waiting)) is None:
            continue
        slot, _ = moved
        state, entered, team = waiting.pop(slot)
        totals[team, slot[0], state][2] += row.at - entered
    for slot, (state, _, team) in waiting.items():
        totals[team, slot[0], state][1] += 1
    for (team, machine, state), (entries, open_entries, seconds) in totals.items():
        row = {
            "day": day, "team": team, "machine": machine, "state": state,
            "entries": entries, "open_entries": open_entries, "seconds": seconds,
        }  # fmt: skip
        statement = insert(day_rollups).values(row)
        db.execute(
            statement.on_conflict_do_update(
                index_elements=["day", "team", "machine", "state"],
                set_={name: statement.excluded[name] for name in ("entries", "open_entries", "seconds")},
            )
        )


def enforce_retention(engine: Engine, *, today: date, retention_days: int, machines: Mapping[str, Table]) -> list[date]:
    """Roll up, then drop, every partition of a day more than `retention_days` before `today`; return those days,
    oldest first.

    A day is rolled up (`rollup_day`) and its partition dropped in one transaction, so a partition is never dropped
    without its rollup, and dropped whole, never row by row. A reader whose cursor sat in a dropped day finds the
    oldest retained id past its cursor on its next poll, which records the gap (`Tail.poll`).
    """
    cutoff = today - timedelta(days=retention_days)
    with engine.begin() as db:
        expired = [day for day in _partition_days(db) if day < cutoff]
        for day in expired:
            rollup_day(db, day, machines)
            db.execute(text(f"DROP TABLE {partition_name(day)}"))
    return expired


def maintain(
    engine: Engine, *, retention_days: int, machines: Mapping[str, Table], now: datetime | None = None
) -> None:
    """One maintenance pass at `now` (the clock by default): the partitions for today and tomorrow exist, and every day
    past the retention bound is rolled up and dropped."""
    today = (now or datetime.now(UTC)).date()
    ensure_partitions(engine, today=today)
    enforce_retention(engine, today=today, retention_days=retention_days, machines=machines)


def keep(
    engine: Engine,
    *,
    retention_days: int,
    machines: Mapping[str, Table],
    stop: threading.Event,
    interval: float = 3600,
) -> None:
    """Run `maintain` every `interval` seconds until `stop` is set; the caller ran the first pass. A pass that fails is
    logged and the next one retries, so a database that was briefly away does not end the hub's housekeeping."""
    while not stop.wait(interval):
        try:
            maintain(engine, retention_days=retention_days, machines=machines)
        except Exception:  # the database is unreachable or mid-restart; the next pass retries
            logger.exception("hub maintenance pass failed; retrying in %ss", interval)
