"""The run adapters that run as opt-in workers, and the Liveness of each: the process the worker announces in the event log.

An adapter module whose `WORKER` names a context (`starpulse worker <context>`) runs there and not in the supervised
`runs` worker: `serve` runs one such context for each `[[runs]]` instance that configures it, and restarts it like
any other context worker. An adapter that stopped or never started silently is the failure to show: the worker
announces its process id to the log once, and `Liveness` watches that process's exit, so the page draws the
instance's error the moment the worker is down, with no beat and no recheck.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import TYPE_CHECKING

from starpulse.event_log.process_exit import ExitWatch, exited

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog
    from starpulse.event_log.wake import StopEvent
    from starpulse.runs.model.config import RunsInstance


def worker_of(adapter: ModuleType) -> str | None:
    """The context of the opt-in worker that runs `adapter`, or None while the supervised `runs` worker does."""
    return getattr(adapter, "WORKER", None)


def followed_by(
    adapters: Sequence[tuple[RunsInstance, ModuleType]], context: str | None
) -> list[tuple[RunsInstance, ModuleType]]:
    """Each instance the worker of `context` runs: with None, the ones no opt-in worker runs."""
    return [(instance, adapter) for instance, adapter in adapters if worker_of(adapter) == context]


def _key(instance: str) -> str:
    return f"runs.worker.{instance}"


def announce(log: EventLog, instance: str, pid: int | None = None) -> None:
    """Write the process id that runs `instance`'s worker to the log, once per start."""
    log.put_state(_key(instance), {"pid": os.getpid() if pid is None else pid})


class Liveness:
    """Whether the process `instance`'s worker announced is running, read from its exit and never from a clock."""

    def __init__(self, log: EventLog, instance: str, gone: Callable[[int], bool] = exited) -> None:
        self._log = log
        self._instance = instance
        self._gone = gone

    def _pid(self) -> int | None:
        _, kept = self._log.state(_key(self._instance))
        pid = kept.get("pid") if isinstance(kept, dict) else None
        return pid if isinstance(pid, int) else None

    def problem(self) -> str | None:
        """Why the worker counts as down, or None while its process runs."""
        try:
            pid = self._pid()
        except Exception as exc:
            return f"the event log cannot be read: {exc}"
        if pid is None:
            return f"the {self._instance} worker has not reported"
        return f"the {self._instance} worker (pid {pid}) exited" if self._gone(pid) else None

    def follow(self, changed: Callable[[], None], stop: StopEvent) -> None:
        """Call `changed` when the announced process exits and when a worker announces itself, on threads until `stop`."""
        watching: set[int] = set()

        def announced() -> None:
            try:
                pid = self._pid()
            except Exception:
                return
            if pid is not None and pid not in watching:
                watching.add(pid)
                threading.Thread(target=exit_of, args=(pid,), name=f"runs-exit-{self._instance}", daemon=True).start()
            changed()

        def exit_of(pid: int) -> None:
            watch = ExitWatch(pid)
            try:
                watch.wait()
            finally:
                watch.close()
            if not stop.is_set():
                changed()

        self._log.follow_state(_key(self._instance), announced, stop, thread_name=f"runs-worker-{self._instance}")
        announced()
