"""The Runs context's seam with `serve`: the workflows each run adapter instance reports, kept in the event log.

`starpulse worker runs` runs the adapters, so `serve` never sees what they report directly. A `Publisher` stands in the
adapters' sink: it keeps what each instance last reported as its own entry of one log setting, which another process's
`Publisher` never overwrites, and announces each change on a stream, and `serve` applies that setting to its feed
(`Projected`) as the page's workflows, pools and startable workflows. A new `serve` or worker process reads the setting,
so neither restart blanks the page.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

PROJECTION = "runs.projection"
PROJECTED_STREAM = "runs:projected"
#: Seconds an idle tail waits for an append from another process.
POLL_S = 1.0
#: Seconds between looks at the Liveness of the opt-in workers, which a silent stop gives no announcement of.
RECHECK_S = 15.0


class Publisher:
    """Keeps each instance's last report in the log, announcing a change."""

    def __init__(self, log: EventLog) -> None:
        self._log = log
        self._lock = threading.Lock()
        self._kept: dict[str, dict] = {}

    def runs(self, instance: str, inner: Any) -> _Sink:
        """The sink the adapter of `instance` reports to; `inner` (the worker feed's) says which workflows are tied."""
        return _Sink(self, instance, inner)

    def report(
        self, instance: str, dags: list | None, error: str | None, pools: list | None, startable: list | None
    ) -> None:
        """Merge a report into the instance's kept one (None keeps the last dags, pools and startable) and write it
        when it changed. A log that cannot be written is tried again on the next report."""
        with self._lock:
            last = self._kept.get(instance, {"dags": [], "pools": [], "startable": None})
            kept = {
                "dags": last["dags"] if dags is None else dags,
                "error": error,
                "pools": last["pools"] if pools is None else pools,
                "startable": last["startable"] if startable is None else sorted(startable),
            }
            if kept == last:
                return
            try:
                self._log.set_setting_entry(PROJECTION, instance, kept)
            except Exception:
                logger.warning("runs: the projection was not kept", exc_info=True)
                return
            self._kept[instance] = kept
            self._log._append(PROJECTED_STREAM, {})


class _Sink:
    """What a run adapter reports to: `set_dags` and `tied`, as the feed's `InstanceRuns` has them."""

    def __init__(self, publisher: Publisher, instance: str, inner: Any) -> None:
        self._publisher = publisher
        self._instance = instance
        self._inner = inner

    @property
    def instance(self) -> str:
        return self._instance

    @property
    def tied(self) -> frozenset[str]:
        return getattr(self._inner, "tied", frozenset())

    def set_dags(
        self, dags: list | None, error: str | None, pools: list | None = None, startable: list[str] | None = None
    ) -> None:
        self._publisher.report(self._instance, dags, error, pools, startable)


class Projected:
    """Applies the worker's kept reports to the serving feed.

    `watched` maps an opt-in worker's instance to why that worker counts as down (`starpulse.runs.opt_in`):
    the page shows it as the instance's error, also for an instance whose worker never reported.
    """

    def __init__(self, log: EventLog, feed: Any, watched: Mapping[str, Callable[[], str | None]] | None = None) -> None:
        self._log = log
        self._feed = feed
        self._watched = dict(watched or {})

    def apply(self) -> None:
        """Take the kept reports; none kept yet, or one unreadable, leaves the feed as it was."""
        try:
            body = self._log.setting(PROJECTION)
        except Exception:
            logger.warning("runs: the projection was not read", exc_info=True)
            return
        reports = body if isinstance(body, dict) else {}
        for instance, report in reports.items():
            if isinstance(report, dict) and isinstance(report.get("dags"), list):
                down = self._down(instance)
                self._feed.set_dags(
                    instance,
                    report["dags"],
                    report.get("error") or down,
                    report.get("pools"),
                    report.get("startable"),
                )
        for instance in self._watched.keys() - reports.keys():
            self._feed.set_dags(instance, [], self._down(instance), None, None)

    def _down(self, instance: str) -> str | None:
        problem = self._watched.get(instance)
        return problem() if problem else None

    def follow(self, stop: threading.Event) -> threading.Thread:
        """Apply the kept reports now, then each one announced after, on a thread until `stop`."""
        from starpulse.event_log.event_log import Tail  # noqa: PLC0415 - the database stack loads when a log opens

        tail = Tail.live(self._log, PROJECTED_STREAM, interval=POLL_S)
        self.apply()
        if self._watched:
            threading.Thread(target=self._recheck, args=(stop,), name="runs-liveness", daemon=True).start()
        thread = threading.Thread(
            target=tail.run, args=(lambda _entry: self.apply(), stop), name="runs-projected", daemon=True
        )
        thread.start()
        return thread

    def _recheck(self, stop: threading.Event) -> None:
        while not stop.wait(RECHECK_S):
            self.apply()
