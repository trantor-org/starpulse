"""The run ledger: each scheduler run's outcome, duration and resource peak, kept against its task.

It is the labelled data the admission rule learns demand from and an optional predictor trains on. One row per run in
the history store's `starpulse_scheduler_runs` table, so a restart keeps it and the store's snapshot carries it. A
ledger file from before the table (one JSON line per run) is imported once, stamped with the file's modification time,
then renamed so it is neither read nor written again; a store that already holds runs ignores a file.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import insert, select

from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.eventlog.operator_settings import RETIRED_SUFFIX
from starpulse._internal.eventlog.tables import scheduler_runs

logger = logging.getLogger(__name__)

#: The ledger's file before it moved into the store; a file by this name in `state_dir` is imported once.
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
    """The runs kept in `log`'s store; `legacy` is the old file, imported before the first read or write."""

    def __init__(self, log: EventLog, legacy: Path) -> None:
        self.log = log
        self.legacy = legacy
        self._imported = False
        self._lock = threading.Lock()

    def record(self, run: RunRecord) -> None:
        """Keep `run`, stamped now. Raises when the store cannot be written."""
        self._import()
        with self.log.engine.begin() as db:
            db.execute(insert(scheduler_runs).values(**asdict(run), recorded_at=time.time()))

    def runs(self, task: str | None = None) -> list[RunRecord]:
        """Every recorded run, oldest first, or only `task`'s. Raises when the store cannot be read."""
        self._import()
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
        cannot be read, so admission falls back to the declared demand."""
        try:
            peaks = [run.peak for run in self.runs() if (run.tier, run.points) == (tier, points)]
        except Exception as exc:  # an unreadable ledger measures nothing
            logger.warning("scheduler ledger: reading runs failed: %s", exc)
            return None
        if not peaks or len(peaks) < min_runs:
            return None
        return {name: sum(peak[name] for peak in peaks) / len(peaks) for name in peaks[0]}

    def _import(self) -> None:
        """Move the old file's runs into the store once, then retire the file; a store that cannot be written leaves
        the file for the next call."""
        with self._lock:
            if self._imported:
                return
            try:
                text = self.legacy.read_text()
                written = self.legacy.stat().st_mtime
            except FileNotFoundError:
                self._imported = True
                return
            except OSError as exc:
                logger.warning("scheduler ledger: reading %s failed: %s", self.legacy, exc)
                return
            rows = [{**json.loads(line), "recorded_at": written} for line in text.splitlines() if line.strip()]
            with self.log.engine.begin() as db:
                # A store that already holds runs wins over a file beside it, which also makes a rerun after an
                # interrupted import (written, not yet renamed) add nothing.
                if rows and db.execute(select(scheduler_runs.c.id).limit(1)).first() is None:
                    db.execute(insert(scheduler_runs), rows)
            self._retire()
            self._imported = True

    def _retire(self) -> None:
        try:
            self.legacy.replace(self.legacy.with_name(self.legacy.name + RETIRED_SUFFIX))
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("scheduler ledger: retiring %s failed: %s", self.legacy, exc)
