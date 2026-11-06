"""The Runs context's reconcile, which the sweeper's `runs` kind runs each pass.

Each run source is listed and compared with the workflows the projection holds for its instance
(`starpulse.runs.application.queries.projection`). An instance whose runs differ missed a pushed event: it is counted as
corrected and a `RESYNC` entry names it, so the worker that owns its adapter reads the source again.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping

from starpulse.event_log.event_log import EventLog
from starpulse.runs.application.queries.projection import PROJECTION
from starpulse.runs.model.run_events import RESYNC

logger = logging.getLogger(__name__)

__all__ = ["RESYNC", "Reconcile"]


def _runs(dags: list[dict]) -> dict[str, tuple]:
    """Each workflow's latest run and status, with the ids of its active runs."""
    return {
        dag["name"]: (dag.get("runId"), dag.get("status"), sorted(run["runId"] for run in dag.get("active", [])))
        for dag in dags
    }


class Reconcile:
    """Compares each source's listing with the projection and asks the owning worker to resync an instance that differs."""

    def __init__(self, log: EventLog, sources: Mapping[str, Callable[[], list[dict]]]) -> None:
        self._log = log
        self._sources = dict(sources)

    def run(self) -> tuple[int, int]:
        """The `(corrected, sampled)` of one pass; a source that cannot be read is skipped, never counted as a miss."""
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
            if _runs(listed) != _runs(held):
                corrected += 1
                self._log.publish(RESYNC, {"instance": instance})
        return corrected, sampled
