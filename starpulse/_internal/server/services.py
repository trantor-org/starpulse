"""The collaborators a deployment may leave unconfigured, which the request handler's routes read from one place."""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from starpulse._internal.config.config import SLOW_READ_S

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse._internal.scheduler.remote import Remote
    from starpulse._internal.scheduler.runtime import Runtime
    from starpulse._internal.config.analytics import Analytics
    from starpulse._internal.config.harnesses import Harnesses
    from starpulse._internal.feed.search import SearchIndex
    from starpulse._internal.harnesses.telemetry import TelemetryLog
    from starpulse._internal.pulls.pull_refresh import PullRefresh
    from starpulse._internal.pulls.pulls import PullStore
    from starpulse._internal.runs.cloudevents import CloudEventsIngest


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
    pull_refresh: PullRefresh | None = None
    slow_read_s: float = SLOW_READ_S
    actor_metrics: Callable[[], str] | None = None
    lane_metrics: Callable[[], str] | None = None
    conformance_metrics: Callable[[], str] | None = None
