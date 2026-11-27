"""The `starpulse_traces` table: a Trace row per case, written as its session folds, read as trace clusters."""

from typing import Any

from sqlalchemy import Connection, Engine, func, select
from sqlalchemy.dialects import sqlite

from starpulse.event_log.tables import signal_folds
from starpulse.event_log.tables import traces as table
from starpulse.flow_metrics.model.traces import cluster_key

__all__ = ["close", "clusters", "write"]


def write(db: Connection, harness: str, session: str, cases: list[dict[str, Any]], unfinished: bool) -> None:
    """Store each of `cases` that performed an Activity as a row of the session, replacing the row a refold or a later
    end of the same case wrote before."""
    rows = [
        {
            "harness": harness,
            "session": session,
            "task": case["task"],
            "skill": case["skill"],
            "started_at": case["started_at"],
            "ended_at": case["ended_at"],
            "activities": case["activities"],
            "cluster_key": cluster_key(case["activities"]),
            "unfinished": unfinished,
        }
        for case in cases
        if case["activities"]
    ]
    if not rows:
        return
    insert = sqlite.insert(table)
    db.execute(
        insert.on_conflict_do_update(
            index_elements=[*table.primary_key.columns],
            set_={c.name: insert.excluded[c.name] for c in table.c if c.name not in table.primary_key.columns},
        ),
        rows,
    )


def close(db: Connection, harness: str, session: str) -> None:
    """Store the case `session` left open as an unfinished Trace, from the ledger its last fold stored."""
    state = db.execute(
        select(signal_folds.c.result).where(
            signal_folds.c.view == "ledger", signal_folds.c.harness == harness, signal_folds.c.session == session
        )
    ).scalar()
    if state and state.get("open_case"):
        write(db, harness, session, [state["open_case"]], unfinished=True)


def clusters(engine: Engine) -> list[dict[str, Any]]:
    """The distinctive work cases did, most common first: each cluster's key, its Activities, how many cases and
    sessions did it and how many of those cases were left unfinished."""
    with engine.connect() as db:
        found = db.execute(
            select(
                table.c.cluster_key,
                func.min(table.c.activities).label("activities"),
                func.count().label("cases"),
                func.count(func.distinct(table.c.session)).label("sessions"),
                func.sum(table.c.unfinished).label("unfinished"),
            )
            .group_by(table.c.cluster_key)
            .order_by(func.count().desc(), table.c.cluster_key)
        ).all()
    return [dict(row._mapping) for row in found]
