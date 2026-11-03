"""The intake's verdict counter, one registry per listener, in the Prometheus text format the listener serves at `/metrics`."""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, generate_latest

__all__ = ["CONTENT_TYPE", "Verdicts"]

CONTENT_TYPE = CONTENT_TYPE_LATEST


class Verdicts:
    """`starpulse_github_deliveries_total{event,verdict}`: how many POSTs each verdict closed, by event."""

    def __init__(self) -> None:
        self._registry = CollectorRegistry()
        self._deliveries = Counter(
            "starpulse_github_deliveries",
            "GitHub webhook deliveries by event and intake verdict",
            ["event", "verdict"],
            registry=self._registry,
        )

    def count(self, event: str, verdict: str) -> None:
        self._deliveries.labels(event, verdict).inc()

    def exposition(self) -> bytes:
        return generate_latest(self._registry)
