"""The steps of the agent's gate and fixed-cost commands as Prometheus series, so the event store keeps no timing of its own.

`agent_step_seconds{command,step,outcome}` holds the seconds each step of a client's command run took, `command` being
the name the client gives it and `outcome` how the run ended; `agent_reuse_total{command,result}` counts the times a pass
record was read, `hit` or `miss`. `StepsRequest` bounds every label to a short name, so the series count never grows with
what a client sends.
"""

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

from starpulse.contracts.api.dto.requests import StepsRequest

BUCKETS = (0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300, 600)

_registry = CollectorRegistry()
_seconds = Histogram(
    "agent_step_seconds",
    "Seconds one step of an agent gate or fixed-cost command took, by command, step and the run's outcome",
    ["command", "step", "outcome"],
    buckets=BUCKETS,
    registry=_registry,
)
_reuse = Counter(
    "agent_reuse_total",
    "Times an agent command read a pass record, by command and whether it was a hit or a miss",
    ["command", "result"],
    registry=_registry,
)


def observe(steps: StepsRequest) -> None:
    for step, seconds in steps.steps.items():
        _seconds.labels(steps.command, step, steps.outcome).observe(seconds)
    if steps.reuse:
        _reuse.labels(steps.command, steps.reuse).inc()


def exposition() -> str:
    return generate_latest(_registry).decode()
