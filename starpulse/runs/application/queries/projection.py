"""The Runs context's seam with `serve`: the workflows each run adapter instance reports, kept in the event log.

`starpulse worker runs` and each adapter's own worker run the adapters, so `serve` never sees what they report directly. A `Publisher` stands in the
adapters' sink: it keeps what each instance last reported as its own entry of one worker state, which another process's
`Publisher` never overwrites, and `serve` applies that state to its feed (`Projected`) as the page's workflows, pools and
startable workflows when its version moves. A new `serve` or worker process reads the state, so neither restart blanks
the page.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter, ValidationError

from starpulse.contracts import Dag

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

PROJECTION = "runs.projection"
_DAGS = TypeAdapter(list[Dag])
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
        self,
        instance: str,
        dags: list | None,
        error: str | None,
        pools: list | None,
        startable: list | None,
        cpu: dict | None = None,
    ) -> None:
        """Merge a report into the instance's kept one (None keeps the last dags, pools, startable and cpu) and write it
        when it changed. A log that cannot be written is tried again on the next report."""
        with self._lock:
            last = self._kept.get(instance, {"dags": [], "pools": [], "startable": None, "cpu": None})
            kept = {
                "dags": last["dags"] if dags is None else dags,
                "error": error,
                "pools": last["pools"] if pools is None else pools,
                "startable": last["startable"] if startable is None else sorted(startable),
                "cpu": last.get("cpu") if cpu is None else cpu,
            }
            if kept == last:
                return
            try:
                self._log.put_state_entry(PROJECTION, instance, kept)
            except Exception:
                logger.warning("runs: the projection was not kept", exc_info=True)
                return
            self._kept[instance] = kept


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
        self,
        dags: list | None,
        error: str | None,
        pools: list | None = None,
        startable: list[str] | None = None,
        cpu: dict | None = None,
    ) -> None:
        self._publisher.report(self._instance, dags, error, pools, startable, cpu)


class Projected:
    """Applies the worker's kept reports to the serving feed.

    `watched` maps an opt-in worker's instance to why that worker counts as down (`starpulse.runs.model.opt_in`):
    the page shows it as the instance's error, also for an instance whose worker never reported.
    """

    def __init__(self, log: EventLog, feed: Any, watched: Mapping[str, Callable[[], str | None]] | None = None) -> None:
        self._log = log
        self._feed = feed
        self._watched = dict(watched or {})

    def apply(self) -> None:
        """Take the kept reports; none kept yet, or one unreadable, leaves the feed as it was."""
        try:
            _, body = self._log.state(PROJECTION)
        except Exception:
            logger.warning("runs: the projection was not read", exc_info=True)
            return
        reports = body if isinstance(body, dict) else {}
        for instance, report in reports.items():
            if isinstance(report, dict) and isinstance(report.get("dags"), list):
                down = self._down(instance)
                self._feed.set_dags(
                    instance,
                    self._current(instance, report["dags"]),
                    report.get("error") or down,
                    report.get("pools"),
                    report.get("startable"),
                    report.get("cpu"),
                )
        for instance in self._watched.keys() - reports.keys():
            self._feed.set_dags(instance, [], self._down(instance), None, None)

    def _current(self, instance: str, dags: list) -> list:
        """The kept workflows, or none when they predate the contract: a body the page's model refuses is a 500 on
        every request until the worker reports again, and a sealed canary's worker never does."""
        try:
            _DAGS.validate_python(dags)
        except ValidationError:
            logger.warning("runs: the kept workflows of %s predate the contract; showing none", instance)
            return []
        return dags

    def _down(self, instance: str) -> str | None:
        problem = self._watched.get(instance)
        return problem() if problem else None

    def follow(self, stop: threading.Event) -> threading.Thread:
        """Apply the kept reports now, then each one announced after, on a thread until `stop`."""
        thread = self._log.follow_state(PROJECTION, self.apply, stop, interval=POLL_S, thread_name="runs-projected")
        self.apply()
        if self._watched:
            threading.Thread(target=self._recheck, args=(stop,), name="runs-liveness", daemon=True).start()
        return thread

    def _recheck(self, stop: threading.Event) -> None:
        while not stop.wait(RECHECK_S):
            self.apply()
