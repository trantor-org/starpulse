"""`starpulse worker sweeper`: the one leased sweeper, as its own process or as a thread of the `contexts` child.

It takes the `sweeper` lease at start, so a second instance exits non-zero naming the holder. It runs a pass at start and
then every `[sweeper] interval_s` (default 3600) until `SIGTERM`: the kinds in order (`readers`, then the `[[sweeper.kinds]]`
commands), then the housekeeping (the event-log prune the runtime passes in, then the `[[sweeper.housekeeping]]`
commands). It keeps the pass metrics in the event log for the Page API's `/metrics`. `SIGHUP` re-reads the config and, as
the kinds are built once, only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.event_log.wake import StopEvent
from starpulse.sweeper.bin.blocks import SweeperBlocks as SweeperConfig
from starpulse.sweeper.bin.blocks import sweeper_built_blocks
from starpulse.sweeper.commands import CommandHousekeeping, CommandKind
from starpulse.sweeper.lease import Lease, LeaseHeld, acquire, process_alive
from starpulse.sweeper.passes import Housekeeping, Kind, Metrics, run_pass
from starpulse.sweeper.publish import publish_metrics
from starpulse.sweeper.readers import Readers

logger = logging.getLogger(__name__)

LEASE = "sweeper"


def reload(path: Path | None, config: SweeperConfig, load: Callable[[Path | None], SweeperConfig]) -> None:
    """Re-read `path`; an invalid config is logged, and a changed `[sweeper]` table asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if sweeper_built_blocks(new) != sweeper_built_blocks(config):
        logger.warning("reload: a database, event log or [sweeper] setting changed; restart the worker to apply it")
    else:
        logger.info("reload: no sweeper setting changed")


def _loop(
    log: EventLog, lease: Lease, kinds: Sequence[Kind], housekeeping: Sequence[Housekeeping], interval_s: float,
    stop: StopEvent,
) -> None:  # fmt: skip
    """Pass now and then every `interval_s` until `stop`, keeping the metrics after each; the lease is released at the end."""
    metrics = Metrics([kind.name for kind in kinds])
    try:
        while not stop.is_set():
            run_pass(kinds, housekeeping, metrics)
            publish_metrics(log, metrics.exposition())
            stop.wait(interval_s)
    finally:
        lease.release()


def start(
    config: SweeperConfig,
    path: Path | None,
    base: Path,
    log: EventLog,
    stop: StopEvent,
    *,
    load: Callable[[Path | None], SweeperConfig],
    prune: Sequence[Housekeeping],
    contexts: Sequence[Kind] = (),
    alive: Callable[[int], bool] = process_alive,
) -> Callable[[], None]:
    """Take the lease and start the pass loop over `log`, ending when `stop` is set; return its reload. `prune` is the
    event-log prune as housekeeping steps and `contexts` the kinds of the contexts (`runs`), which the runtime builds as no
    context imports another. Raises `LeaseHeld` while
    another live process holds the lease."""
    lease = acquire(log.engine, LEASE, alive=alive)
    declared = config.sweeper
    kinds: list[Kind] = [
        Readers(log, wake=log.committed),
        *contexts,
        *(CommandKind(k.name, k.command, base, k.timeout_s) for k in declared.kinds),
    ]
    housekeeping: list[Housekeeping] = [
        *prune,
        *(CommandHousekeeping(h.name, h.command, base, h.timeout_s) for h in declared.housekeeping),
    ]
    args = (log, lease, kinds, housekeeping, declared.interval_s, stop)
    threading.Thread(target=_loop, args=args, name="sweeper", daemon=True).start()
    return lambda: reload(path, config, load)


def main(
    argv: list[str] | None,
    parser: argparse.ArgumentParser,
    *,
    discover: Callable[[Path | None], Path | None],
    load: Callable[[Path | None], SweeperConfig],
    prune: Callable[[EventLog, SweeperConfig, Path], Sequence[Housekeeping]],
    contexts: Callable[[EventLog, argparse.ArgumentParser, SweeperConfig], Sequence[Kind]],
    hold: Callable[[threading.Event, Callable[[], None]], None],
) -> None:
    """Run the sweeper; `runtime` passes the collaborators it builds, as no context imports it. Exits 1 naming the
    holder when another sweeper holds the lease."""
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    log = EventLog(database_url(config.database_url, base))
    stop = StopEvent()
    try:
        reload_config = start(
            config,
            path,
            base,
            log,
            stop,
            load=load,
            prune=prune(log, config, base),
            contexts=contexts(log, parser, config),
        )
    except LeaseHeld as exc:
        parser.exit(1, f"{exc}\n")
    hold(stop, reload_config)
