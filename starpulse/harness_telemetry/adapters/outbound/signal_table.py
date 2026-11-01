"""The signal store: `starpulse_signals` in the history database, one row per signal key.

`insert` ignores a key the table holds, so an export replayed, a copy rerun, and two writers racing on one signal each
leave one row. Nothing reads the table yet (the adapters and views move in later slices).
"""

from __future__ import annotations

from collections.abc import Iterable
from itertools import batched
from typing import Any

from sqlalchemy import Engine
from sqlalchemy.dialects import sqlite

from starpulse.event_log.tables import signals

__all__ = ["SignalTable"]

BATCH = 1000


class SignalTable:
    """Writes signal rows (a `Signal`'s stored fields, as `dataclasses.asdict` gives them) to `starpulse_signals`."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def insert(self, rows: Iterable[dict[str, Any]]) -> int:
        """Adds the rows whose `key` the table lacks, in one transaction, and returns how many it added; raises when
        the database does."""
        added = 0
        with self._engine.begin() as db:
            for batch in batched(rows, BATCH):
                values = [
                    {
                        "key": row["key"],
                        "harness": row["harness"],
                        "session": row["session"],
                        "time": row["time"],
                        "kind": row["kind"],
                        "fields": row,
                    }
                    for row in batch
                ]
                statement = sqlite.insert(signals).values(values).on_conflict_do_nothing().returning(signals.c.key)
                added += len(db.execute(statement).all())
        return added
