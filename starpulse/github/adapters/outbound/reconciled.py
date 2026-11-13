"""The reconcile pass's counters, in the Prometheus text format: redeliveries asked, rows inserted, and how far each cursor lags."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest

__all__ = ["Reconciled"]


class Reconciled:
    """`starpulse_github_redeliveries_total`, `starpulse_github_reconcile_rows_total{kind}` and
    `starpulse_github_reconcile_cursor_lag_seconds{cursor}`."""

    def __init__(self) -> None:
        self._registry = CollectorRegistry()
        self._redeliveries = Counter(
            "starpulse_github_redeliveries", "Redeliveries the reconcile pass asked GitHub for", registry=self._registry
        )
        self._rows = Counter(
            "starpulse_github_reconcile_rows",
            "Inbox rows the reconcile pass inserted, by the kind of fact",
            ["kind"],
            registry=self._registry,
        )
        self._lag = Gauge(
            "starpulse_github_reconcile_cursor_lag_seconds",
            "Seconds between now and the newest timestamp a reconcile cursor has reached",
            ["cursor"],
            registry=self._registry,
        )
        self._sampled = 0
        self._corrected = 0

    def redelivered(self) -> None:
        self._redeliveries.inc()
        self._corrected += 1

    def inserted(self, kind: str) -> None:
        self._rows.labels(kind).inc()
        self._corrected += 1

    def looked(self) -> None:
        """A cursor's list was read, which a 304 answers as well as a page does."""
        self._sampled += 1

    def take(self) -> tuple[int, int]:
        """The lists read and the facts recovered (a redelivery asked, a row inserted) since the last `take`."""
        taken = (self._sampled, self._corrected)
        self._sampled = self._corrected = 0
        return taken

    def lag(self, cursor: str, seconds: float) -> None:
        self._lag.labels(cursor).set(max(seconds, 0.0))

    def exposition(self) -> bytes:
        return generate_latest(self._registry)
