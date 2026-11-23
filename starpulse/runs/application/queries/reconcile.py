"""The Runs context's reconcile, which the sweeper's `runs` kind runs each pass.

Each run source is listed and compared with the workflows the projection holds for its instance
(`starpulse.runs.application.queries.projection`). An instance whose runs differ missed a pushed event: it is counted as
resynced by a `RESYNC` entry naming it, so the worker that owns its adapter reads the source again, and counted as
corrected only when a run a push announces differs. A Temporal Schedule starts its runs (`command-job/*` workflow ids)
with no start post and no completion callback, so the sweeper keeps them by design: they resync, never count. A
process's first pass compares nothing: the projection predates a restart and each adapter lists its source at start, so
a difference there is catch-up, not a missed push.
"""

import logging
from collections.abc import Callable, Mapping

from starpulse.event_log.event_log import EventLog
from starpulse.runs.application.queries.projection import PROJECTION
from starpulse.runs.model.run_events import RESYNC

logger = logging.getLogger(__name__)

__all__ = ["RESYNC", "Reconcile"]


_SCHEDULED = "/workflows/command-job%2F"
"""The run url part of a Temporal Schedule's workflow id (`command-job/<job>-<fire time>`), which no push announces."""


def _scheduled(run: dict) -> bool:
    return _SCHEDULED in run.get("url", "")


def _runs(dags: list[dict], *, pushed: bool = False) -> dict[str, tuple]:
    """Each workflow's latest run and status, with the ids of its active runs; `pushed` leaves out the scheduled runs."""
    found = {}
    for dag in dags:
        latest, status, active, recent = dag.get("runId"), dag.get("status"), dag.get("active", []), dag.get("recent", [])
        if pushed:
            skipped = {run["runId"] for run in [*active, *recent] if _scheduled(run)}
            active = [run for run in active if run["runId"] not in skipped]
            if latest in skipped:
                newest = active[-1] if active else next((run for run in recent if run["runId"] not in skipped), None)
                latest, status = (newest["runId"], "running" if active else newest["status"]) if newest else (None, None)
        found[dag["name"]] = (latest, status, sorted(run["runId"] for run in active))
    return found


class Reconcile:
    """Compares each source's listing with the projection and asks the owning worker to resync an instance that differs."""

    def __init__(self, log: EventLog, sources: Mapping[str, Callable[[], list[dict]]]) -> None:
        self._log = log
        self._sources = dict(sources)
        self._started = False

    def run(self) -> tuple[int, int]:
        """The `(corrected, sampled)` of one pass, `(0, 0)` for the process's first; a source that cannot be read is skipped,
        never counted as a miss."""
        if not self._started:
            self._started = True
            return 0, 0
        _, body = self._log.state(PROJECTION)
        kept = body if isinstance(body, dict) else {}
        corrected = sampled = 0
        for instance, source in self._sources.items():
            try:
                listed = source()
            except (OSError, ValueError, KeyError, TypeError):
                logger.warning("runs: %s cannot be listed; skipping it this pass", instance, exc_info=True)
                continue
            sampled += 1
            held = kept.get(instance, {}).get("dags", []) if isinstance(kept.get(instance), dict) else []
            if (now := _runs(listed)) != (before := _runs(held)):
                corrected += _runs(listed, pushed=True) != _runs(held, pushed=True)
                differing = sorted(name for name in now.keys() | before.keys() if now.get(name) != before.get(name))
                logger.info("runs: %s differs from the projection in %s; resyncing it", instance, ", ".join(differing))
                self._log.publish(RESYNC, {"instance": instance})
        return corrected, sampled
