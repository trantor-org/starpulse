"""The intake's verdict counter, one registry per listener, in the Prometheus text format the listener serves at `/metrics`."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, generate_latest
from prometheus_client.core import GaugeMetricFamily

__all__ = ["CONTENT_TYPE", "Verdicts"]

CONTENT_TYPE = CONTENT_TYPE_LATEST


class _DeadRows:
    """`starpulse_github_dead_rows{consumer}`, read from the queue at each scrape."""

    def __init__(self, counts: Callable[[], dict[str, int]]) -> None:
        self._counts = counts

    def collect(self) -> Iterator[GaugeMetricFamily]:
        gauge = GaugeMetricFamily(
            "starpulse_github_dead_rows", "Deliveries a consumer gave up on, until requeued or dismissed", labels=["consumer"]
        )
        for consumer, dead in self._counts().items():
            gauge.add_metric([consumer], dead)
        yield gauge


class Verdicts:
    """`starpulse_github_deliveries_total{event,verdict}`: how many POSTs each verdict closed, by event, and
    `starpulse_github_dead_rows{consumer}` when given the queue's `dead_counts`."""

    def __init__(self, dead_counts: Callable[[], dict[str, int]] | None = None) -> None:
        self._registry = CollectorRegistry()
        if dead_counts is not None:
            self._registry.register(_DeadRows(dead_counts))
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
