"""The intake's verdict counter, one registry per listener, in the Prometheus text format the listener serves at `/metrics`."""

from collections.abc import Callable, Iterator

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, generate_latest
from prometheus_client.core import GaugeMetricFamily

from starpulse.github.adapters.outbound.queue import Backlog

__all__ = ["CONTENT_TYPE", "Backlogs", "Verdicts"]

CONTENT_TYPE = CONTENT_TYPE_LATEST


class Backlogs:
    """`starpulse_github_{pending_rows,oldest_due_seconds,dead_rows}{consumer}`, read from the queue at each scrape."""

    def __init__(self, backlogs: Callable[[], dict[str, Backlog]]) -> None:
        self._backlogs = backlogs

    def collect(self) -> Iterator[GaugeMetricFamily]:
        help_of = {
            "pending_rows": "Deliveries a consumer has yet to finish",
            "oldest_due_seconds": "Seconds the oldest due pending delivery has waited",
            "dead_rows": "Deliveries a consumer gave up on, until requeued or dismissed",
        }
        gauges = [GaugeMetricFamily(f"starpulse_github_{name}", text, labels=["consumer"]) for name, text in help_of.items()]
        for consumer, backlog in self._backlogs().items():
            for gauge, value in zip(gauges, (backlog.pending, backlog.oldest_due_s, backlog.dead), strict=True):
                gauge.add_metric([consumer], value)
        yield from gauges

    def exposition(self) -> str:
        registry = CollectorRegistry()
        registry.register(self)
        return generate_latest(registry).decode()


class Verdicts:
    """`starpulse_github_deliveries_total{event,verdict}`: how many POSTs each verdict closed, by event, and
    the `Backlogs` gauges when given the queue's `backlogs`."""

    def __init__(self, backlogs: Callable[[], dict[str, Backlog]] | None = None) -> None:
        self._registry = CollectorRegistry()
        if backlogs is not None:
            self._registry.register(Backlogs(backlogs))
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
