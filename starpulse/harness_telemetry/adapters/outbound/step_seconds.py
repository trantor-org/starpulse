"""Step timings and model-request totals as Prometheus series, so the event store keeps no telemetry of its own.

The seconds a `request`, `tool` or `hook` signal took are observed in `starpulse_step_seconds{harness,kind}` as the
adapter publishes the signal, and the adapter serves them at `/metrics` for Prometheus to scrape. The signal itself,
seconds included, goes to `TelemetryLog`; this is the aggregate Grafana reads. Each `request` signal also adds one to
`starpulse_model_requests_total`, its five token counts to `starpulse_model_*_tokens_total` and its cost to
`starpulse_model_cost_usd_total`, labelled by `model`, `origin` and `entrypoint` only, so the series count stays bounded.
The tokens of a Model step taken before its session named any task, so no task's Stay takes it, go to
`starpulse_unassigned_*_tokens_total{harness}`.
"""

from collections.abc import Iterable
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Histogram, generate_latest

from starpulse.contracts.signals import Signal

__all__ = ["CONTENT_TYPE", "exposition", "observe", "unassigned"]

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

_MODEL_LABELS = ["model", "origin", "entrypoint"]
_requests = Counter(
    "starpulse_model_requests_total",
    "Model requests, by model, origin and entrypoint",
    _MODEL_LABELS,
    registry=_registry,
)
_cost = Counter(
    "starpulse_model_cost_usd_total",
    "Cost in USD of model requests, by model, origin and entrypoint",
    _MODEL_LABELS,
    registry=_registry,
)
_tokens = {
    field: Counter(
        f"starpulse_model_{field}_tokens_total",
        f"{field} tokens of model requests, by model, origin and entrypoint",
        _MODEL_LABELS,
        registry=_registry,
    )
    for field in ("input", "output", "cache_read", "cache_write", "reasoning")
}
_unassigned = {
    field: Counter(
        f"starpulse_unassigned_{field}_tokens_total",
        f"{field} tokens of Model steps taken before their session named a task, by harness",
        ["harness"],
        registry=_registry,
    )
    for field in ("input", "output", "cache_read", "cache_write")
}


def observe(found: Iterable[Signal]) -> None:
    """Records the duration of each step signal that carries one, and the totals of each request."""
    for signal in found:
        if signal.kind in STEP_KINDS and signal.seconds > 0:
            _step_seconds.labels(signal.harness, signal.kind).observe(signal.seconds)
        if signal.kind == "request":
            labels = (signal.model, signal.origin, signal.entrypoint)
            _requests.labels(*labels).inc()
            _cost.labels(*labels).inc(signal.cost or 0)
            for field, counter in _tokens.items():
                counter.labels(*labels).inc(getattr(signal, field))


def unassigned(steps: Iterable[dict[str, Any]]) -> None:
    """Count the tokens of `steps`, Model steps taken before their session named any task, under their harness."""
    for step in steps:
        for field, counter in _unassigned.items():
            counter.labels(step["harness"]).inc(step["tokens"][field])


def exposition() -> bytes:
    """The histogram in the Prometheus text format."""
    return generate_latest(_registry)
