"""The run adapters that run as opt-in workers, and the Liveness of each: a beat the worker keeps in the event log.

An adapter module whose `WORKER` names a context (`starpulse worker <context>`) runs there and nowhere in `serve`: not in
the supervised `runs` worker, and `serve` supervises no child for it. Nothing starts it but the operator, so an adapter
that never started or stopped silently is the failure to show: the worker writes the time to the log every `BEAT_S`, and
`problem` says why `serve` counts it as down, which the page draws as the instance's error.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse._internal.config.config import RunsInstance
    from starpulse._internal.eventlog.event_log import EventLog

logger = logging.getLogger(__name__)

BEAT_S = 15.0
DOWN_S = 60.0


def worker_of(adapter: ModuleType) -> str | None:
    """The context of the opt-in worker that runs `adapter`, or None while the supervised `runs` worker does."""
    return getattr(adapter, "WORKER", None)


def followed_by(
    adapters: Sequence[tuple[RunsInstance, ModuleType]], context: str | None
) -> list[tuple[RunsInstance, ModuleType]]:
    """Each instance the worker of `context` runs: with None, the ones no opt-in worker runs."""
    return [(instance, adapter) for instance, adapter in adapters if worker_of(adapter) == context]


def _key(instance: str) -> str:
    return f"runs.beat.{instance}"


def beat(log: EventLog, instance: str, clock: Callable[[], float] = time.time) -> None:
    """Write the time to the log as `instance`'s worker's latest beat."""
    log.set_setting(_key(instance), {"at": clock()})


def keep_beating(log: EventLog, instance: str, stop: threading.Event) -> threading.Thread:
    """Beat every `BEAT_S` on a thread until `stop`; a log that cannot be written is tried again at the next beat."""

    def run() -> None:
        while not stop.is_set():
            try:
                beat(log, instance)
            except Exception:
                logger.warning("runs: the %s worker's beat was not kept", instance, exc_info=True)
            stop.wait(BEAT_S)

    thread = threading.Thread(target=run, name=f"runs-beat-{instance}", daemon=True)
    thread.start()
    return thread


def problem(log: EventLog, instance: str, clock: Callable[[], float] = time.time) -> Callable[[], str | None]:
    """Why `instance`'s worker counts as down, or None while its beat is under `DOWN_S` old."""

    def read() -> str | None:
        try:
            kept = log.setting(_key(instance))
        except Exception as exc:
            return f"the event log cannot be read: {exc}"
        at = kept.get("at") if isinstance(kept, dict) else None
        if not isinstance(at, int | float):
            return f"the {instance} worker has not reported"
        age = clock() - at
        return None if age <= DOWN_S else f"the {instance} worker last reported {age:.0f}s ago"

    return read
