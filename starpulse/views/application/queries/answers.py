"""The answers of the telemetry analytics views, kept past a restart so a read never waits on the fold of its window.

Folding a 168 h window of the harnesses' signals takes minutes on a cold process (the log is fetched from Loki and every
signal read) and tens of seconds on a warm one, longer than the CLI waits. `Answers` keeps the last good body of each
view and query in the `starpulse_answers` table, one row per view and query: a read answers with its row at once, and
one older than `fresh_s` also starts a refold in the background, so the answer is at most one refold behind and at most
`fresh_s` plus a fold old. A restarted process answers from the saved rows before it has read a signal. Only the first
read of a query nobody has asked since its row was saved waits for a fold, all readers of it for the same one. A
refusal (400, 501, 503) is returned and never kept.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import NamedTuple

from sqlalchemy import Engine, delete, select
from sqlalchemy.dialects import sqlite

from starpulse.event_log.tables import analytics_answers

__all__ = ["Answers"]

logger = logging.getLogger(__name__)

_Key = tuple[str, str]


class _Held(NamedTuple):
    body: bytes
    status: int
    folded_at: float


class Answers:
    """The last good `(body, status)` of each view and query, refolded in the background once `fresh_s` old; at most
    `kept` are saved, the oldest folded dropped first."""

    def __init__(
        self,
        engine: Engine,
        *,
        fresh_s: float = 300.0,
        kept: int = 32,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._engine, self._fresh_s, self._kept, self._clock = engine, fresh_s, kept, clock
        self._lock = threading.Lock()
        self._folding = threading.Lock()  # one fold at a time: each holds a window's rows as Python data
        self._tried: dict[_Key, float] = {}
        self._jobs: dict[_Key, Future[tuple[bytes, int]]] = {}
        self._threads: set[threading.Thread] = set()

    def _read(self, key: _Key) -> _Held | None:
        view, query = key
        where = (analytics_answers.c.view == view) & (analytics_answers.c.query == query)
        try:
            with self._engine.connect() as db:
                row = db.execute(
                    select(analytics_answers.c.body, analytics_answers.c.status, analytics_answers.c.folded_at).where(
                        where
                    )
                ).first()
        except Exception:  # fail open: the database is unreachable, so fold as if nothing was saved
            logger.warning("analytics answers: cannot read the saved answer of %s", key, exc_info=True)
            return None
        return None if row is None else _Held(bytes(row.body), row.status, row.folded_at)

    def answer(self, view: str, query: str, compute: Callable[[], tuple[bytes, int]]) -> tuple[bytes, int]:
        """The answer for `view` and `query`: the saved body at once when there is one, refolding with `compute` in the
        background when it is `fresh_s` old; else the result of the fold of `compute`, which concurrent readers share."""
        key = (view, query)
        held = self._read(key)
        with self._lock:
            job = self._jobs.get(key)
            if job is None and held is None:
                held = self._read(key)  # a fold that ended since the read above has saved its row
            last = max(self._tried.get(key, 0.0), held.folded_at if held else 0.0)
            if job is None and (held is None or self._clock() - last >= self._fresh_s):
                job = self._start(key, compute)
        return (held.body, held.status) if held else job.result()

    def _start(self, key: _Key, compute: Callable[[], tuple[bytes, int]]) -> Future[tuple[bytes, int]]:
        job: Future[tuple[bytes, int]] = Future()
        thread = threading.Thread(target=self._fold, args=(key, compute, job), name="analytics-answers", daemon=True)
        self._jobs[key] = job
        self._tried[key] = self._clock()
        self._threads.add(thread)
        thread.start()
        return job

    def _fold(self, key: _Key, compute: Callable[[], tuple[bytes, int]], job: Future[tuple[bytes, int]]) -> None:
        try:
            with self._folding:
                body, status = compute()
        except BaseException as exc:  # noqa: BLE001 - the reader that waits on the job raises it; a stale answer stays
            logger.warning("analytics answers: the fold of %s failed: %s", key, exc)
            with self._lock:
                self._jobs.pop(key, None)
            job.set_exception(exc)
            return
        if status == 200:
            self._save(key, body, status)  # before the job leaves `_jobs`, so a reader that finds none finds the row
        with self._lock:
            self._jobs.pop(key, None)
        job.set_result((body, status))

    def _save(self, key: _Key, body: bytes, status: int) -> None:
        view, query = key
        insert = sqlite.insert(analytics_answers).values(
            view=view, query=query, body=body, status=status, folded_at=self._clock()
        )
        upsert = insert.on_conflict_do_update(
            index_elements=[analytics_answers.c.view, analytics_answers.c.query],
            set_={"body": insert.excluded.body, "status": insert.excluded.status, "folded_at": insert.excluded.folded_at},
        )
        kept_floor = (
            select(analytics_answers.c.folded_at)
            .order_by(analytics_answers.c.folded_at.desc())
            .offset(self._kept - 1)
            .limit(1)
            .scalar_subquery()
        )
        try:
            with self._engine.begin() as db:
                db.execute(upsert)
                db.execute(delete(analytics_answers).where(analytics_answers.c.folded_at < kept_floor))
        except Exception:  # fail open: the answer is served from the fold, only a restart loses it
            logger.warning("analytics answers: cannot save the answer of %s", key, exc_info=True)

    def join(self) -> None:
        """Wait for the folds running now."""
        with self._lock:
            running = list(self._threads)
        for thread in running:
            thread.join()
        with self._lock:
            self._threads.difference_update(running)
