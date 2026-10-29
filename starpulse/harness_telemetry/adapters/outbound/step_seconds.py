"""Step timings as a Prometheus histogram, so the event store keeps no telemetry of its own.

The seconds a `request`, `tool` or `hook` signal took are observed in `starpulse_step_seconds{harness,kind}` as the
adapter publishes the signal, and the adapter serves them at `/metrics` for Prometheus to scrape. The signal itself,
seconds included, goes to `TelemetryLog`; this is the aggregate Grafana reads.
"""

from __future__ import annotations

from collections.abc import Iterable

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Histogram, generate_latest

from starpulse.contracts.signals import Signal

__all__ = ["CONTENT_TYPE", "exposition", "observe"]

CONTENT_TYPE = CONTENT_TYPE_LATEST
STEP_KINDS = frozenset({"request", "tool", "hook"})
BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300)

_registry = CollectorRegistry()
_step_seconds = Histogram(
    "starpulse_step_seconds",
    "Seconds a model request, tool call or hook run took, by harness and kind",
    ["harness", "kind"],
    buckets=BUCKETS,
    registry=_registry,
)


def observe(found: Iterable[Signal]) -> None:
    """Records the duration of each step signal that carries one."""
    for signal in found:
        if signal.kind in STEP_KINDS and signal.seconds > 0:
            _step_seconds.labels(signal.harness, signal.kind).observe(signal.seconds)


def exposition() -> bytes:
    """The histogram in the Prometheus text format."""
    return generate_latest(_registry)
