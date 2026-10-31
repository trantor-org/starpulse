"""The answers of the telemetry analytics views, kept past a restart so a read never waits on the fold of its window.

Folding a 168 h window of the harnesses' signals takes minutes on a cold process (the log is fetched from Loki and every
signal read) and tens of seconds on a warm one, longer than the CLI waits. `Answers` keeps the last good body of each
view and query instead: a read answers with it at once, and one older than `fresh_s` also starts a refold in the
background, so the answer is at most one refold behind and at most `fresh_s` plus a fold old. The bodies are saved to
the event log's checkpoints, so a restarted process answers from the saved ones before it has read a signal. Only the
first read of a query nobody has asked since the answers were first saved waits for a fold, all readers of it for the
same one. A refusal (400, 501, 503) is returned and never kept.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import ClassVar, Protocol

from pydantic import BaseModel

__all__ = ["AnswerStore", "Answers"]

logger = logging.getLogger(__name__)

NAME = "analytics-answers"


class AnswerStore(Protocol):
    """Where the answers are saved: the event log's `Checkpoints`, or any store that holds one snapshot per name."""

    def load(self, name: str, model: type[BaseModel] | None = None) -> tuple[int | None, BaseModel | None]: ...

    def save(self, name: str, position: int, model: BaseModel | None = None) -> None: ...


class _Kept(BaseModel):
    at: float
    body: str


class _Snapshot(BaseModel):
    SCHEMA_VERSION: ClassVar[int] = 1

    answers: dict[str, _Kept]


class Answers:
    """The last good `(body, status)` of each query key, refolded in the background once `fresh_s` old; at most `kept`
    keys are held, the oldest answered dropped first."""

    def __init__(
        self,
        store: AnswerStore | None,
        *,
        fresh_s: float = 300.0,
        kept: int = 32,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store, self._fresh_s, self._kept, self._clock = store, fresh_s, kept, clock
        self._lock = threading.Lock()
        self._held = self._load()
        self._tried = {key: at for key, (at, _) in self._held.items()}
        self._jobs: dict[str, Future[tuple[bytes, int]]] = {}
        self._threads: set[threading.Thread] = set()

    def _load(self) -> dict[str, tuple[float, bytes]]:
        if self._store is None:
            return {}
        try:
            _, snapshot = self._store.load(NAME, _Snapshot)
        except Exception:  # the database is unreachable: fold as if nothing was saved
            logger.warning("analytics answers: cannot load the saved answers", exc_info=True)
            return {}
        if not isinstance(snapshot, _Snapshot):
            return {}
        return {key: (kept.at, kept.body.encode()) for key, kept in snapshot.answers.items()}

    def answer(self, key: str, compute: Callable[[], tuple[bytes, int]]) -> tuple[bytes, int]:
        """The answer for `key`: the kept body at once (200) when there is one, refolding with `compute` in the
        background when it is `fresh_s` old; else the result of the fold of `compute`, which concurrent readers share."""
        with self._lock:
            held = self._held.get(key)
            job = self._jobs.get(key)
            if job is None and (held is None or self._clock() - self._tried[key] >= self._fresh_s):
                job = self._start(key, compute)
        return (held[1], 200) if held else job.result()

    def _start(self, key: str, compute: Callable[[], tuple[bytes, int]]) -> Future[tuple[bytes, int]]:
        job: Future[tuple[bytes, int]] = Future()
        thread = threading.Thread(target=self._fold, args=(key, compute, job), name="analytics-answers", daemon=True)
        self._jobs[key] = job
        self._tried[key] = self._clock()
        self._threads.add(thread)
        thread.start()
        return job

    def _fold(self, key: str, compute: Callable[[], tuple[bytes, int]], job: Future[tuple[bytes, int]]) -> None:
        try:
            body, status = compute()
        except BaseException as exc:  # noqa: BLE001 - the reader that waits on the job raises it; a stale answer stays
            logger.warning("analytics answers: the fold of %s failed: %s", key, exc)
            with self._lock:
                self._jobs.pop(key, None)
            job.set_exception(exc)
            return
        with self._lock:
            self._jobs.pop(key, None)
            if status == 200:
                self._held[key] = (self._clock(), body)
                for old in sorted(self._held, key=lambda held: self._held[held][0])[: -self._kept]:
                    del self._held[old], self._tried[old]
                snapshot = _Snapshot(answers={k: _Kept(at=at, body=b.decode()) for k, (at, b) in self._held.items()})
        job.set_result((body, status))
        if status == 200:
            self._save(snapshot)

    def _save(self, snapshot: _Snapshot) -> None:
        if self._store is None:
            return
        try:
            self._store.save(NAME, 0, snapshot)
        except Exception:  # fail open: the answer is held in memory, only a restart loses it
            logger.warning("analytics answers: cannot save the answers", exc_info=True)

    def join(self) -> None:
        """Wait for the folds running now."""
        with self._lock:
            running = list(self._threads)
        for thread in running:
            thread.join()
        with self._lock:
            self._threads.difference_update(running)
