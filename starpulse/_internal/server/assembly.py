"""Build the board, its feed and the history store a `serve` or a worker context runs on, without the HTTP server."""

from __future__ import annotations

import threading
from collections.abc import Collection, Mapping
from pathlib import Path

from starpulse._internal.board.seam import Board
from starpulse._internal.board.seam import load as load_board
from starpulse._internal.ci.ci import attach
from starpulse._internal.config.config import Config
from starpulse._internal.eventlog.event_log import EventLog, prune_forever
from starpulse._internal.eventlog.history import HistoryStore, database_url
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.harnesses.harness import HARNESS_MACHINES
from starpulse._internal.machines.snapshot import qualifier
from starpulse._internal.pulls.task_actor import ACTOR


def assemble(config: Config, base: Path, window_s: float | None, run_safe: Collection[str]) -> tuple[Board, BoardFeed]:
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
    )
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


def keep_event_log(
    log: EventLog, config: Config, base: Path, *, hub: bool, stop: threading.Event
) -> threading.Thread | None:
    """Start the hourly prune of the event log, which archives each row it deletes under `event_log_archive_dir`.

    A hub starts none: it drops a whole day's partition once it has rolled the day up, so its rows are never deleted
    one by one.
    """
    if hub:
        return None
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
