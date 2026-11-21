"""The board audit's costly-transition series, `starpulse_skill_agent_seconds_total{kind,size,skill}` and
`starpulse_skill_tasks_total{kind,size,skill}`: the agent seconds charged to each skill machine within a task's kind and
size, and the tasks that entered it. The `signal-folds` worker adds what each session fold gains and keeps the
exposition in the log; the Page API relays it on `/metrics`. Labels are the board's declared kinds, sizes and skill
machines only, so the series count stays bounded."""

from collections.abc import Callable, Mapping

from prometheus_client import CollectorRegistry, Counter, generate_latest

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.kept_text import kept_text

__all__ = ["STATE", "add", "exposition", "metrics_of"]

STATE = "signal_folds.skill_cost"

_registry = CollectorRegistry()
_LABELS = ["kind", "size", "skill"]
_seconds = Counter(
    "starpulse_skill_agent_seconds_total", "Agent seconds charged to a skill, by kind, size and skill", _LABELS, registry=_registry
)
_tasks = Counter(
    "starpulse_skill_tasks_total", "Tasks that entered a skill, by kind, size and skill", _LABELS, registry=_registry
)


def add(increase: Mapping[tuple[str, int, str], tuple[float, int]]) -> None:
    """Adds each cell's agent seconds and newly entered tasks, as `cells.cost_increase` returns them."""
    for (kind, size, skill), (seconds, entered) in increase.items():
        _seconds.labels(kind, str(size), skill).inc(seconds)
        _tasks.labels(kind, str(size), skill).inc(entered)


def exposition() -> str:
    return generate_latest(_registry).decode()


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The exposition as last kept by the worker; empty before it kept any."""
    return kept_text(log, STATE)
