"""`starpulse_task_completion_steps{kind,size}`: the steps of each task slice that completed clean, relayed to `/metrics`.

The signal folds run in the `contexts` child and the Page API serves `/metrics`, so the observer keeps its exposition
in the event log's state and the Page API reads it back. A restart resets the histogram; Prometheus reads that as a
counter reset. The labels are the board's kind and size labels, so the series count stays bounded and no task id is
carried.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Any

from prometheus_client import CollectorRegistry, Histogram, generate_latest

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.kept_text import kept_text
from starpulse.flow_metrics.model.cells import clean_steps

logger = logging.getLogger(__name__)

STATE = "completion_steps.metrics"
BUCKETS = (5, 10, 25, 50, 100, 200, 400, 800, 1600, 3200)


class CompletionSteps:
    def __init__(self, log: EventLog, titled: Callable[[], Mapping[str, Mapping[str, Any]]]) -> None:
        self._log = log
        self._titled = titled
        self._registry = CollectorRegistry()
        self._histogram = Histogram(
            "starpulse_task_completion_steps",
            "Main and subagent model requests of a task slice that completed clean, by task kind and size",
            ["kind", "size"],
            buckets=BUCKETS,
            registry=self._registry,
        )

    def observe(self, slices: list[dict[str, Any]]) -> None:
        """Observe each of `slices` that completed clean in a kind x size cell, then keep the exposition."""
        titled = self._titled()
        observed = [found for s in slices if (found := clean_steps(s, titled))]
        for kind, size, steps in observed:
            self._histogram.labels(kind, str(size)).observe(steps)
        if observed:
            try:
                self._log.put_state(STATE, generate_latest(self._registry).decode())
            except Exception:
                logger.warning("completion-steps: the metrics were not kept", exc_info=True)


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The histogram's text as last kept; empty before a clean completion or when the log cannot be read."""
    return kept_text(log, STATE)
