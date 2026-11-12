"""`starpulse_bridge_published_total{entity,event}`: messages the bridge published, relayed to `/metrics`.

The bridge runs in the `contexts` child and the Page API serves `/metrics`, so the bridge keeps its exposition in the
event log's state and the Page API reads it back. A restart resets the counter; Prometheus reads that as a counter reset.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from prometheus_client import CollectorRegistry, Counter, generate_latest

from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

STATE = "bridge.metrics"


class Published:
    def __init__(self, log: EventLog) -> None:
        self._log = log
        self._registry = CollectorRegistry()
        self._counter = Counter(
            "starpulse_bridge_published",
            "Messages the bridge published to NATS, by subject entity and event",
            ["entity", "event"],
            registry=self._registry,
        )

    def count(self, subject: str) -> None:
        """Count one message on `starpulse.<board>.<entity>.<id>.<event>` and keep the exposition for the Page API."""
        *_, entity, _, event = subject.split(".")
        self._counter.labels(entity, event).inc()
        try:
            self._log.put_state(STATE, generate_latest(self._registry).decode())
        except Exception:
            logger.warning("bridge: the metrics were not kept", exc_info=True)


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The bridge's metrics text as last kept; empty before it published or when the log cannot be read."""

    def read() -> str:
        try:
            _, text = log.state(STATE)
        except Exception:
            return ""
        return text if isinstance(text, str) else ""

    return read
