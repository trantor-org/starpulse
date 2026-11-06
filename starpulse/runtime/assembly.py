"""Build the board, its feed and the history store a `serve` or a worker context runs on, without the HTTP server."""

from __future__ import annotations

import functools
import logging
from collections.abc import Collection, Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine

from starpulse.board.board_feed import BoardFeed
from starpulse.board.machine_tasks import MachineDeltas
from starpulse.board.model.seam import Board
from starpulse.board.model.seam import load as load_board
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.event_log.readmodel.declared import declared_fields
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.harness_telemetry.adapters.inbound.telemetry import KEEP_S
from starpulse.harness_telemetry.model.harness import SESSION_MACHINES
from starpulse.machine_engine.model.snapshot import qualifier
from starpulse.pulls.adapters.inbound.task_actor import ACTOR
from starpulse.pulls.model.ci import CiError, attach
from starpulse.runtime import read_model_follow
from starpulse.runs.application.queries.reconcile import Reconcile
from starpulse.runs.model.config import RunsInstance
from starpulse.runtime.config import Config, ConfigError, runs_adapter
from starpulse.sweeper.passes import Outcome, Step

if TYPE_CHECKING:
    from starpulse.pulls.adapters.outbound.pulls import PullStore

logger = logging.getLogger(__name__)


@functools.cache
def _pull_store(engine: Engine) -> PullStore:
    """The scheduler's one store of pull requests: building it reads every open and recent row, so it is built once."""
    from starpulse.pulls.adapters.outbound.pulls import (
        PullStore,
    )  # only the scheduler worker needs it, not the `serve` supervisor

    return PullStore(engine)


def own_pull_merged(log: EventLog, agent: Mapping[str, Any]) -> bool:
    """Whether a pull request `agent` owns has merged; the scheduler reads it through `runtime`, as no context imports another.

    Asked of every Ready task on every tick, so it reads only the rows of the pull requests `agent` cites (TASK-9620)."""
    from starpulse.pulls.adapters.outbound.pull_requests import PULL_URL, merged  # only the scheduler worker needs them

    if not agent["prs"]:
        return False
    store = _pull_store(log.engine)
    cited = [PULL_URL.fullmatch(url) for url in agent["prs"]]
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


def assemble(
    config: Config,
    base: Path,
    window_s: float | None,
    run_safe: Collection[str],
    read_model: ReadModel | None = None,
) -> tuple[Board, BoardFeed]:
    """The board the config's `[board]` adapter builds, and the feed that draws it; `base` is the config's directory.

    A task whose latest move on a machine is older than `window_s` seconds (None: never) is not drawn there, and Run
    now is drawn on the `run_safe` workflows.
    """
    board = load_board(config.board_type, config.board, base)
    domains = domains_of(config)
    qualify = qualifier(domains)
    # `[board.actor]` makes the task actor a writer the machine may name beside the adapters' workflows.
    # An instance read live at startup may list short, so its writers are warned about, not refused (`<instance>/*`).
    listed = [
        *(name for names in domains.values() for name in names),
        *(f"{name}/*" for name in live_instances(config)),
    ]
    drawn = board.machines(qualify, [*listed, ACTOR] if config.task_actor else listed)
    # Every harness adapter writes this one machine, so the page draws it unless the board declares a machine of that name.
    machines = {**drawn, **{name: m for name, m in SESSION_MACHINES.items() if name not in drawn}}
    if config.ci:
        try:
            machines = attach(machines, config.ci)
        except CiError as exc:
            raise ConfigError(str(exc)) from exc
    if config.level:
        config.level.check(machines)
    feed = BoardFeed(
        window_s,
        board.keys,
        config.tracker_url,
        machines=machines,
        roles=board.roles,
        domains=domains,
        processes=config.qualified_processes(),
        run_safe=run_safe,
        cues=board.cues(qualify),
        source=board.source,
        capabilities={
            "edit": board.edit is not None,
            "archive": board.archive is not None,
            "create": board.create is not None,
        },
        hint=found_backlog(config, base),
        commit={instance.name: instance.commit for instance in config.runs if instance.commit},
        read_model=read_model,
        standing=board.standing or (lambda *_: None),
        readable=board.readable or (lambda *_: ""),
        default_profiles=config.board.get("default_profiles", {}),
    )
    return board, feed


def worker_board(config: Config, base: Path, log: EventLog, stop: StopEvent) -> tuple[Board, BoardFeed]:
    """The board and feed of a worker beside `serve`: the feed reads the read model the Board child folds, and the board
    is attached to `log`, so its writes append the History events that read model folds.
    Raises ValueError as `assemble` does."""
    board, feed, _ = _read_model_board(config, base, log)
    read_model_follow.follow(None, feed, stop, log)
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
    board, feed = assemble(config, base, None, [], model)
    # The read model folds only History events, so this worker's writes (the task actor's moves) must append them.
    if board.attach is not None:
        board.attach(log)
    feed.ready.set()
    return board, feed, model


def found_backlog(config: Config, base: Path) -> str | None:
    """The line that names a Backlog.md project beside `base` and how to switch to it, when the config names no board.

    The default board is StarPulse's own; a project that already has a `backlog/` is told, not adopted. The line ends
    `run: <command>`, which the Connect a tracker modal draws as a copyable block.
    """
    if "type" in config.board or not (project := base / "backlog" / "config.yml").is_file():
        return None
    return (
        f"Found a Backlog.md project at {project}; StarPulse is showing its own board. "
        "To show that project instead, run: starpulse connect backlog --path backlog"
    )


def history_store(config: Config, base: Path, machines: Mapping[str, dict]) -> HistoryStore:
    """StarPulse's store at `database_url` or beside the config: the one history `serve` records into and the page reads.

    Opening it puts every StarPulse table, the event log's included, on that database.
    """
    return HistoryStore(
        database_url(config.database_url, base), machines, retention_days=config.event_log_retention_days
    )


def prune_steps(log: EventLog, config: Config, base: Path) -> list[Step]:
    """The sweeper's event-log housekeeping: one pass of the prune, which archives each row it deletes under
    `event_log_archive_dir`, and one of the signal table and its folds, which keep the last `KEEP_S` seconds."""
    archive = base / config.event_log_archive_dir
    days = config.event_log_retention_days

    def events() -> None:
        if pruned := log.prune(days * 86400, archive_dir=archive):
            logger.info("EventLog: pruned %d rows older than %d days", pruned, days)

    def signals() -> None:
        if pruned := log.prune_signals(KEEP_S):
            logger.info("EventLog: pruned %d signals older than %d s", pruned, KEEP_S)

    return [Step("event-log-prune", events), Step("signal-prune", signals)]


class _RunsKind:
    """The sweeper's `runs` kind: `Reconcile` over the followed instances' sources."""

    name = "runs"

    def __init__(self, reconcile: Reconcile) -> None:
        self._reconcile = reconcile

    def run(self) -> Outcome:
        corrected, sampled = self._reconcile.run()
        return Outcome(corrected, sampled)


def runs_kind(log: EventLog, adapters: Sequence[tuple[RunsInstance, ModuleType]]) -> _RunsKind:
    """The `runs` kind over each instance whose adapter module has a `read(url)`, which lists the instance's workflows
    as the page draws them; the sweeper builds it here as it imports no context."""
    sources = {
        instance.name: functools.partial(adapter.read, instance.url)
        for instance, adapter in adapters
        if hasattr(adapter, "read")
    }
    return _RunsKind(Reconcile(log, sources))
