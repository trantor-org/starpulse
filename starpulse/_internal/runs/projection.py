"""The Runs context's seam with `serve`: the workflows each run adapter instance reports, kept in the event log.

`starpulse worker runs` runs the adapters, so `serve` never sees what they report directly. A `Publisher` stands in the
adapters' sink: it keeps what each instance last reported as one log setting and announces each change on a stream, and
`serve` applies that setting to its feed (`Projected`) as the page's workflows, pools and startable workflows. A new
`serve` or worker process reads the setting, so neither restart blanks the page.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from starpulse._internal.eventlog.event_log import EventLog, Tail

logger = logging.getLogger(__name__)

PROJECTION = "runs.projection"
PROJECTED_STREAM = "runs:projected"
#: Seconds an idle tail waits for an append from another process.
POLL_S = 1.0


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
            body = {**self._kept, instance: kept}
            try:
                self._log.set_setting(PROJECTION, body)
            except Exception:
                logger.warning("runs: the projection was not kept", exc_info=True)
                return
            self._kept[instance] = kept
            self._log.append(PROJECTED_STREAM, {})


class _Sink:
    """What a run adapter reports to: `set_dags` and `tied`, as the feed's `InstanceRuns` has them."""

    def __init__(self, publisher: Publisher, instance: str, inner: Any) -> None:
        self._publisher = publisher
        self._instance = instance
        self._inner = inner

    @property
    def tied(self) -> frozenset[str]:
        return getattr(self._inner, "tied", frozenset())

    def set_dags(
        self, dags: list | None, error: str | None, pools: list | None = None, startable: list[str] | None = None
    ) -> None:
        self._publisher.report(self._instance, dags, error, pools, startable)


class Projected:
    """Applies the worker's kept reports to the serving feed."""

    def __init__(self, log: EventLog, feed: Any) -> None:
        self._log = log
        self._feed = feed

    def apply(self) -> None:
        """Take the kept reports; none kept yet, or one unreadable, leaves the feed as it was."""
        try:
            body = self._log.setting(PROJECTION)
        except Exception:
            logger.warning("runs: the projection was not read", exc_info=True)
            return
        if not isinstance(body, dict):
            return
        for instance, report in body.items():
            if isinstance(report, dict) and isinstance(report.get("dags"), list):
                self._feed.set_dags(
                    instance, report["dags"], report.get("error"), report.get("pools"), report.get("startable")
                )

    def follow(self, stop: threading.Event) -> threading.Thread:
        """Apply the kept reports now, then each one announced after, on a thread until `stop`."""
        tail = Tail(self._log, PROJECTED_STREAM, after=self._log.head() or 0, interval=POLL_S)
        self.apply()
        thread = threading.Thread(
            target=tail.run, args=(lambda _entry: self.apply(), stop), name="runs-projected", daemon=True
        )
        thread.start()
        return thread
