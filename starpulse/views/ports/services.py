"""The collaborators a deployment may leave unconfigured, which the request handler's routes read from one place."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.display_settings import DisplaySettings
    from starpulse.harness_telemetry.adapters.outbound.harness_settings import HarnessSettings
    from starpulse.board.adapters.search import SearchIndex
    from starpulse.contracts.analytics import Analytics
    from starpulse.event_log.machine_store import MachineStore
    from starpulse.harness_telemetry.model.harnesses import Harnesses
    from starpulse.pulls.adapters.outbound.pulls import PullStore
    from starpulse.runs.adapters.inbound.cloudevents import CloudEventsIngest
    from starpulse.scheduler.adapters.remote import Remote
    from starpulse.scheduler.adapters.runtime import Runtime
    from starpulse.views.ports.signal_folds import SignalFoldReader


@dataclass(frozen=True)
class Services:
    """What the routes use beside the Board: each field None (or empty) leaves its routes unconfigured."""

    harnesses: Harnesses | None = None
    harness_settings: HarnessSettings | None = None
    """The harness config `PUT /api/harnesses` keeps over `harnesses`; None refuses the PUT."""
    start_session: Callable[..., str] | None = None
    """Starts a task's session in the harness the page picked."""
    dispatch: Callable[[str, str, str], bool] | None = None
    """Publishes the dispatch of a session to a task, with the holder it replaces: `(task, session, replaces)`."""
    entrypoint: Callable[[str], str] | None = None
    """The `claude_code.entrypoint` of a session's running process, empty when none runs: a project thread's is `sdk-cli`."""
    live: Callable[[str], bool] | None = None
    """Whether the harness confirms the session an id names is running: a dispatch of any other id is refused."""
    events: CloudEventsIngest | None = None
    webhook: Callable[[str | None, bytes], tuple[int, dict]] | None = None
    """Answers one `POST /intake/grafana`: `(authorization, body)` to `(status, JSON body)`."""
    scheduler: Runtime | Remote | None = None
    display: DisplaySettings | None = None
    """The display and theme choices Admin keeps for every device."""
    contract: Callable[[], dict[str, Any]] | None = None
    ready: Callable[[], dict[str, Any]] | None = None
    pulls: PullStore | None = None
    telemetry: SignalFoldReader | None = None
    search: SearchIndex | None = None
    analytics: Analytics | None = None
    #: Sends the take-over Update to a task's workflow: False when the task has none.
    take_over: Callable[[str], bool] | None = None
    #: Each lane's tools, typed exit tools and bound skill by lane name, from the board policy.
    lanes: Callable[[], dict[str, Any]] | None = None
    #: The machines the store holds, which the machine write routes change; None refuses them.
    machines: MachineStore | None = None
    #: Seconds a rendered `/metrics` page is served again; 0 renders each scrape.
    scrape_cache_s: float = 0.0
    actor_metrics: Callable[[], str] | None = None
    #: Each configured view's stored GraphQL document by view name.
    views: Mapping[str, str] = field(default_factory=dict)
    lane_metrics: Callable[[], str] | None = None
    autopilot_metrics: Callable[[], str] | None = None
    storage_metrics: Callable[[], str] | None = None
    sweeper_metrics: Callable[[], str] | None = None
    bridge_metrics: Callable[[], str] | None = None
    history_lag_metrics: Callable[[], str] | None = None
    follower_lag_metrics: Callable[[], str] | None = None
    skill_cost_metrics: Callable[[], str] | None = None
    child_cpu_metrics: Callable[[], str] | None = None
    follower_wake_metrics: Callable[[], str] | None = None
    github_metrics: Callable[[], str] | None = None

    def harness_config(self) -> Harnesses | None:
        """The harness config `GET /api/harnesses` answers and `/start` checks: the kept one, else the declared one."""
        return self.harness_settings.read() if self.harness_settings else self.harnesses
