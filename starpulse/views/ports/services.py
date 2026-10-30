"""The collaborators a deployment may leave unconfigured, which the request handler's routes read from one place."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.search import SearchIndex
    from starpulse.contracts.analytics import Analytics
    from starpulse.harness_telemetry.adapters.inbound.telemetry import TelemetryLog
    from starpulse.harness_telemetry.model.harnesses import Harnesses
    from starpulse.pulls.adapters.inbound.pull_refresh import PullRefresh
    from starpulse.pulls.adapters.outbound.pulls import PullStore
    from starpulse.runs.adapters.inbound.cloudevents import CloudEventsIngest
    from starpulse.scheduler.adapters.remote import Remote
    from starpulse.scheduler.adapters.runtime import Runtime


class KeptAnswers(Protocol):
    """The answers of the telemetry analytics kept past a restart (`Answers`)."""

    def answer(self, view: str, query: str, compute: Callable[[], tuple[bytes, int]]) -> tuple[bytes, int]: ...


#: The default of `slow_read_seconds`.
SLOW_READ_S = 1.0


@dataclass(frozen=True)
class Services:
    """What the routes use beside the Board: each field None (or empty) leaves its routes unconfigured."""

    starts: Mapping[str, Callable[[str], str]] = field(default_factory=dict)
    """What starts each workflow run, by qualified name."""
    run_safe: Collection[str] = frozenset()
    """The workflows the config marks run-safe, the only ones a run or rerun may name."""
    reruns: Mapping[str, Callable[[str, Mapping[str, str]], str]] | None = None
    """What reruns a workflow run, by qualified name."""
    harnesses: Harnesses | None = None
    start_session: Callable[..., str] | None = None
    """Starts a task's session in the harness the page picked."""
    events: CloudEventsIngest | None = None
    scheduler: Runtime | Remote | None = None
    contract: Callable[[], dict[str, Any]] | None = None
    pulls: PullStore | None = None
    telemetry: TelemetryLog | None = None
    search: SearchIndex | None = None
    analytics: Analytics | None = None
    #: Keeps the telemetry analytics' answers past a restart so a read never waits on a fold; None folds per request.
    answers: KeptAnswers | None = None
    pull_refresh: PullRefresh | None = None
    #: Sends the take-over Update to a task's workflow: False when the task has none.
    take_over: Callable[[str], bool] | None = None
    slow_read_s: float = SLOW_READ_S
    actor_metrics: Callable[[], str] | None = None
    lane_metrics: Callable[[], str] | None = None
    conformance_metrics: Callable[[], str] | None = None
    lane_sweep_metrics: Callable[[], str] | None = None
    autopilot_metrics: Callable[[], str] | None = None
