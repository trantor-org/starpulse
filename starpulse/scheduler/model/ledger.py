"""The run ledger: each scheduler run's outcome, duration and resource peak, kept against its task.

It is the labelled data the admission rule learns demand from and an optional predictor trains on. One row per run in
the history store's `starpulse_scheduler_runs` table, so a restart keeps it and the store's snapshot carries it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from sqlalchemy import func, insert, select

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import scheduler_runs

logger = logging.getLogger(__name__)

#: The ledger's file before it moved into the store; `starpulse migrate` imports a file by this name once.
LEDGER_FILE = "starpulse-scheduler-runs.jsonl"


@dataclass(frozen=True)
class RunRecord:
    """One finished run: the lane its task ended in (`outcome`), how long it ran, and the demand it drew at its highest.

    `peak` is that demand per capacity dimension in the dimension's own unit, the shape of a task's demand vector.
    """

    task: str
    tier: str
    points: int
    outcome: str
    duration_s: float
    peak: Mapping[str, float]


class Ledger:
    """The runs kept in `log`'s store."""

    def __init__(self, log: EventLog) -> None:
        self.log = log
        self._kept: tuple[tuple[int, int | None], dict[tuple[str, int], tuple[int, dict[str, float]]]] = ((0, None), {})

    def record(self, run: RunRecord) -> None:
        """Keep `run`, stamped now. Raises when the store cannot be written."""
        with self.log.engine.begin() as db:
            db.execute(insert(scheduler_runs).values(**asdict(run), recorded_at=time.time()))

    def runs(self, task: str | None = None) -> list[RunRecord]:
        """Every recorded run, oldest first, or only `task`'s. Raises when the store cannot be read."""
        query = select(scheduler_runs).order_by(scheduler_runs.c.id)
        if task is not None:
            query = query.where(scheduler_runs.c.task == task)
        with self.log.engine.connect() as db:
            return [
                RunRecord(row.task, row.tier, row.points, row.outcome, row.duration_s, row.peak)
                for row in db.execute(query)
            ]

    def measured(self, tier: str, points: int, min_runs: int) -> dict[str, float] | None:
        """The mean peak of the runs of `tier` and `points`, or None while fewer than `min_runs` exist or the store
        cannot be read, so admission falls back to the declared demand.

        Admission asks for each eligible task on every pass, so a mean is read once and kept until the store's run count
        or newest run changes, whichever ledger recorded it."""
        try:
            count, mean = self._mean(tier, points)
        except Exception as exc:  # an unreadable ledger measures nothing
            logger.warning("scheduler ledger: reading runs failed: %s", exc)
            return None
        return mean if count and count >= min_runs else None

    def _mean(self, tier: str, points: int) -> tuple[int, dict[str, float]]:
        """How many runs of `tier` and `points` the store holds and the mean of their peaks."""
        with self.log.engine.connect() as db:
            stamp = tuple(db.execute(select(func.count(), func.max(scheduler_runs.c.id))).one())
            if self._kept[0] != stamp:
                self._kept = (stamp, {})
            kept = self._kept[1]
            if (tier, points) not in kept:
                query = select(scheduler_runs.c.peak).where(
                    scheduler_runs.c.tier == tier, scheduler_runs.c.points == points
                )
                peaks = list(db.execute(query).scalars())
                kept[tier, points] = (
                    len(peaks),
                    {n: sum(p[n] for p in peaks) / len(peaks) for n in peaks[0]} if peaks else {},
                )
            return kept[tier, points]
