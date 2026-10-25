"""Build the board, its feed and the history store a `serve` or a worker context runs on, without the HTTP server."""

from __future__ import annotations

import threading
from collections.abc import Collection, Mapping
from pathlib import Path

from starpulse._internal.board import replica
from starpulse._internal.board.seam import Board
from starpulse._internal.board.seam import load as load_board
from starpulse._internal.ci.ci import attach
from starpulse._internal.config.config import Config
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.harness import HARNESS_MACHINES
from starpulse._internal.pulls.task_actor import ACTOR
from starpulse._internal.server import read_model_follow
from starpulse.event_log.event_log import EventLog, prune_forever
from starpulse.event_log.opening import database_url
from starpulse.event_log.readmodel.declared import declared_fields
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.flow_metrics.history import HistoryStore
from starpulse.machine_engine.model.snapshot import qualifier


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
    domains = config.qualified_domains()
    qualify = qualifier(domains)
    # `[board.actor]` makes the task actor a writer the machine may name beside the adapters' workflows.
    listed = [name for names in domains.values() for name in names]
    drawn = board.machines(qualify, [*listed, ACTOR] if config.task_actor else listed)
    # Every harness adapter writes this one machine, so the page draws it unless the board declares a machine of that name.
    machines = {**drawn, **{name: m for name, m in HARNESS_MACHINES.items() if name not in drawn}}
    if config.ci:
        machines = attach(machines, config.ci)
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
    )
    return board, feed


def worker_board(
    config: Config, base: Path, log: EventLog, group: str, stop: threading.Event
) -> tuple[Board, BoardFeed]:
    """The board and feed of a worker beside `serve`: the feed reads the replica the Board child publishes
    (`replica.read`), or under `read_model` the read model the Board child folds, since no replica is published then.
    Raises ValueError as `assemble` does."""
    if not config.read_model:
        board, feed = assemble(config, base, None, [])
        replica.read(board, feed, group, log, config, stop)
        return board, feed
    board, feed = assemble(config, base, None, [], ReadModel(log.engine, declared_fields(config.board)))
    feed.ready.set()
    read_model_follow.follow(None, feed, stop)
    return board, feed


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
    return HistoryStore(database_url(config.database_url, base), machines)


def keep_event_log(log: EventLog, config: Config, base: Path, *, stop: threading.Event) -> threading.Thread:
    """Start the hourly prune of the event log, which archives each row it deletes under `event_log_archive_dir`."""
    thread = threading.Thread(
        target=prune_forever,
        args=(log,),
        kwargs={
            "retention_days": config.event_log_retention_days,
            "archive_dir": base / config.event_log_archive_dir,
            "stop": stop,
        },
        name="event-log-prune",
        daemon=True,
    )
    thread.start()
    return thread
