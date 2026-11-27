"""Build the board, its feed and the history store a `serve` or a worker context runs on, without the HTTP server."""

import functools
import logging
import os
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError

from starpulse.board.adapters import native, policy_store
from starpulse.board.application.queries.machine_tasks import MachineDeltas
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.policy import Policy, profile_matrix
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.event_log.readmodel.declared import declared_fields
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.github.adapters.inbound import reconcile
from starpulse.github.adapters.outbound.app_jwt import app_jwt
from starpulse.github.adapters.outbound.cursors import SqlCursors
from starpulse.github.adapters.outbound.inbox import SqlInbox
from starpulse.github.adapters.outbound.queue import backlogs
from starpulse.github.adapters.outbound.reconciled import Reconciled
from starpulse.github.adapters.outbound.rest import Client, connect_client
from starpulse.github.adapters.outbound.verdicts import Backlogs
from starpulse.github.model.github_config import GitHub
from starpulse.harness_telemetry.model.harness import SESSION_MACHINES
from starpulse.machine_engine.model.snapshot import qualifier
from starpulse.pulls.adapters.inbound.task_actor import ACTOR
from starpulse.pulls.adapters.outbound.github import GitHubAdapter, urls_of
from starpulse.pulls.model.ci import CiError, attach
from starpulse.runtime import read_model_follow
from starpulse.runtime.config import Config, ConfigError, runs_adapter
from starpulse.scheduler.model.config import ACTOR as SCHEDULER_ACTOR
from starpulse.sweeper.passes import Outcome, Step

if TYPE_CHECKING:
    from starpulse.pulls.adapters.outbound.pulls import PullStore
lazy from starpulse.pulls.adapters.outbound.github import GITHUB_MACHINES

logger = logging.getLogger(__name__)


def _holder_activity(config: Config) -> Callable[[str], dict[str, Any]]:
    harness = config.session_harness()
    return lambda assignee: harness.activity(assignee, time.time())


@functools.cache
def _pull_store(engine: Engine) -> PullStore:
    """The scheduler's one store of pull requests: building it reads every open and recent row, so it is built once."""
    from starpulse.pulls.adapters.outbound.pulls import PullStore

    return PullStore(engine)


def own_pull_merged(log: EventLog, agent: Mapping[str, Any]) -> bool:
    """Whether a pull request `agent` owns has merged; the scheduler reads it through `runtime`, as no context imports another.

    Asked of every Ready task on every tick, so it reads only the rows of the pull requests `agent` delivers."""
    from starpulse.pulls.adapters.outbound.pull_requests import PULL_URL, merged  # only the scheduler worker needs them

    if not agent["delivered"]:
        return False
    store = _pull_store(log.engine)
    cited = [PULL_URL.fullmatch(url) for url in agent["delivered"]]
    store.refresh([(found[1], int(found[2])) for found in cited if found])
    return merged(store, dict(agent))


def live_instances(config: Config) -> list[str]:
    """The runs instances whose workflows `domains_of` reads from the adapter: a read can come back short."""
    return [
        instance.name
        for instance in config.runs
        if instance.url and not instance.domains and hasattr(runs_adapter(instance.type), "domains")
    ]


def domains_of(config: Config) -> dict[str, tuple[str, ...]]:
    """The config's domains plus those a runs adapter reads from its workflows (`domains(url)`, optional), as
    `<instance>/<workflow>`, for an instance whose config lists no domains of its own; read once as the server starts.

    An instance the adapter cannot read contributes none, so its workflows are drawn outside any domain until a restart.
    """
    merged: dict[str, tuple[str, ...]] = dict(config.qualified_domains())
    for instance in config.runs:
        if not instance.url or instance.domains:
            continue
        read = getattr(runs_adapter(instance.type), "domains", None)
        if read is None:
            continue
        try:
            tagged = read(instance.url)
        except OSError, ValueError:
            continue
        for domain, names in tagged.items():
            merged[domain] = (*merged.get(domain, ()), *(f"{instance.name}/{n}" for n in names))
    return merged


def declared(config: Config, base: Path) -> tuple[Board, dict[str, dict], Mapping[str, Sequence[str]], Policy | None]:
    """The board the config's `[board]` adapter builds, the machines it and the harness adapters draw, the config's
    domains and the stored policy: all a reader of the declarations, with no feed, needs. Raises ValueError as
    `assemble` does."""
    rows = policy_store.held(database_url(config.database_url, base))
    board = native.board({**config.board, "policy_rows": rows}, base)
    domains = domains_of(config)
    qualify = qualifier(domains)
    # `[board.actor]` makes the task actor a writer the machine may name beside the adapters' workflows; the scheduler is always one.
    # An instance read live at startup may list short, so its writers are warned about, not refused (`<instance>/*`).
    listed = [
        *(name for names in domains.values() for name in names),
        *(f"{name}/*" for name in live_instances(config)),
    ]
    drawn = board.machines(qualify, [*listed, SCHEDULER_ACTOR, *([ACTOR] if config.task_actor else [])])
    # Every harness adapter writes this one machine, so the page draws it unless the board declares a machine of that name.
    machines = {**drawn, **{name: m for name, m in SESSION_MACHINES.items() if name not in drawn}}
    if config.ci:
        try:
            machines = attach(machines, config.ci)
        except CiError as exc:
            raise ConfigError(str(exc)) from exc
    if config.level:
        config.level.check(machines)
    return board, machines, domains, rows


def assemble(
    config: Config,
    base: Path,
    window_s: float | None,
    read_model: ReadModel,
) -> tuple[Board, BoardFeed]:
    """The board the config's `[board]` adapter builds, and the feed that draws it from `read_model`; `base` is the config's directory.

    A task whose latest move on a machine is older than `window_s` seconds (None: never) is not drawn there.
    """
    board, machines, domains, rows = declared(config, base)
    qualify = qualifier(domains)
    feed = BoardFeed(
        read_model,
        window_s,
        board.keys,
        machines=machines,
        roles=board.roles,
        domains=domains,
        processes=config.qualified_processes(),
        cues=board.cues(qualify),
        source=board.source,
        commit={instance.name: instance.commit for instance in config.runs if instance.commit},
        start_urls={instance.name: instance.start_url for instance in config.runs if instance.start_url},
        standing=board.standing,
        readable=board.readable,
        activity=_holder_activity(config),
        default_profiles=profile_matrix(rows or Policy()),
        change_url=urls_of({"github": GitHubAdapter()}),
    )
    return board, feed


def worker_board(config: Config, base: Path, log: EventLog, stop: StopEvent) -> tuple[Board, BoardFeed]:
    """The board and feed of a worker beside `serve`: the feed reads the read model the Board child folds and publishes
    its task and machine-row deltas, and the board is attached to `log`, so its writes append the History events that
    read model folds. The task actor hands a finished delivery's verdict to its holder from a machine `move` delta.
    Raises ValueError as `assemble` does."""
    board, feed, model = _read_model_board(config, base, log)
    read_model_follow.follow(None, feed, stop, log)
    MachineDeltas(feed, model).follow(stop, log)
    return board, feed


def scheduler_board(config: Config, base: Path, log: EventLog, stop: StopEvent) -> tuple[Board, BoardFeed]:
    """The board and feed of the Scheduler: every question is answered from the read model and nothing is folded here.
    Its change deltas are polled from the read model by `scheduler.adapters.changes`, which ends with `stop`.
    Raises ValueError as `assemble` does."""
    from starpulse.scheduler.adapters.changes import follow_changes

    board, feed, model = _read_model_board(config, base, log)
    follow_changes(feed, MachineDeltas(feed, model), stop, log)
    return board, feed


def _read_model_board(config: Config, base: Path, log: EventLog) -> tuple[Board, BoardFeed, ReadModel]:
    """The assembled board and feed over the read model, attached to `log` and ready, with no follower started."""
    model = ReadModel(log.engine, declared_fields(config.board))
    board, feed = assemble(config, base, None, model)
    # The read model folds only History events, so this worker's writes (the task actor's moves) must append them.
    board.attach(log)
    feed.ready.set()
    return board, feed, model


def history_store(config: Config, base: Path, machines: Mapping[str, dict]) -> HistoryStore:
    """StarPulse's store at `database_url` or beside the config: the one history `serve` records into and the page reads.

    Opening it puts every StarPulse table, the event log's included, on that database. It reads the `pr-checks`
    machine beside the board's, so a task's check rollup is in its events.
    """

    return HistoryStore(
        database_url(config.database_url, base),
        {**machines, "pr-checks": GITHUB_MACHINES["pr-checks"]},
        retention_days=config.event_log_retention_days,
    )


_RESTORED = "event_log_archive_restored"


def prune_steps(log: EventLog, config: Config, base: Path) -> list[Step]:
    """The sweeper's event-log housekeeping: one pass of the prune, which archives each row it deletes under
    `event_log_archive_dir` and first, once, puts the retained streams' archived rows back."""
    archive = base / config.event_log_archive_dir
    days = config.event_log_retention_days

    def events() -> None:
        if log.setting(_RESTORED) is None:
            restored = log.restore(archive)
            log.set_setting(_RESTORED, True)
            if restored:
                logger.info("EventLog: restored %d archived rows of the retained streams", restored)
        if pruned := log.prune(days * 86400, archive_dir=archive):
            logger.info("EventLog: pruned %d rows older than %d days", pruned, days)

    return [Step("event-log-prune", events)]


def stored_updates(store: PullStore) -> Callable[[str, int], str | None]:
    """The `updatedAt` the store holds for a pull request, `None` for one it lacks."""

    def stored(repository: str, number: int) -> str | None:
        found = store.find(repository, number, bodies=False)
        return found[0]["updatedAt"] if found else None

    return stored


def pull_updates(log: EventLog) -> Callable[[str, int], str | None]:
    """`stored_updates` over the scheduler's store of `log`, built on first use: a sweeper with no `[github]` never reads it."""
    return lambda repository, number: stored_updates(_pull_store(log.engine))(repository, number)


class GithubKind:
    """The sweeper's `github` kind: one reconcile pass of the inbox against GitHub. A list read is a sample, an
    inbox row inserted a correction; a redelivery asked is the webhook pushed again, so it is none."""

    name = "github"

    def __init__(
        self,
        client: Client,
        inbox: SqlInbox,
        cursors: SqlCursors,
        settings: GitHub,
        clock: Callable[[], float],
        stored: Callable[[str, int], str | None],
    ) -> None:
        self._arguments = (client, inbox, cursors, settings)
        self._clock = clock
        self._stored = stored
        self._counted = Reconciled()

    def run(self) -> Outcome:
        reconcile.reconcile(*self._arguments, self._counted, self._clock, self._stored)
        sampled, corrected = self._counted.take()
        return Outcome(corrected=corrected, sampled=sampled)

    def exposition(self) -> str:
        return self._counted.exposition().decode()


def github_kinds(config: Any, log: EventLog) -> list[GithubKind]:
    """The `github` kind over the inbox in `log`'s store, as the list the sweeper's `contexts` joins; empty without the
    table or its `reconcile_token_env`."""
    settings = config.github
    if settings is None or not settings.reconcile_token_env:
        return []
    inbox = SqlInbox(log.engine)
    client = connect_client(lambda: os.environ.get(settings.reconcile_token_env or ""), app_jwt, caller="reconcile")
    return [GithubKind(client, inbox, SqlCursors(inbox.engine), settings, time.time, pull_updates(log))]


class _BoardKind:
    """One of the sweeper's board kinds: `reconcile` looks again at what a push or a deadline should have settled and
    returns (sampled, corrected)."""

    def __init__(self, name: str, reconcile: Callable[[], tuple[int, int]]) -> None:
        self.name = name
        self._reconcile = reconcile

    def run(self) -> Outcome:
        sampled, corrected = self._reconcile()
        return Outcome(corrected, sampled)


def board_kinds(shared: Callable[[], tuple[Board, BoardFeed]]) -> list[_BoardKind]:
    """The `waiting` and `board-files` kinds over the board and feed `shared` hands out, read at the first pass
    (the Board context may publish them after the sweeper starts). The task actor that releases a Waiting task
    registers its pass on the feed; a kind whose owner is not running in this process samples
    nothing."""

    def registered(name: str) -> Callable[[], tuple[int, int]]:
        return lambda: shared()[1].reconcilers.get(name, lambda: (0, 0))()

    return [
        _BoardKind("waiting", registered("waiting")),
        _BoardKind("board-files", registered("board-files")),
    ]


def github_metrics(config: Any, base: Path) -> Callable[[], str]:
    """The reader of every inbox consumer's backlog gauges for the page's `/metrics`, which Prometheus scrapes: empty
    without the `[github]` table, or while the inbox has no table yet."""
    settings = config.github
    if settings is None:
        return lambda: ""
    gauges = Backlogs(functools.partial(backlogs, create_engine(database_url(config.database_url, base))))

    def read() -> str:
        try:
            return gauges.exposition()
        except SQLAlchemyError:
            logger.warning("github inbox backlog unreadable", exc_info=True)
            return ""

    return read
