"""`starpulse worker board`: the Board context's writer (the lane dating) as its own process, beside
`serve`.

`board-release` is not here: the release of dependents runs in the Delivery worker (`starpulse worker pulls`).

It reads the config and the database `serve` does and meets `serve` only in the history there: this worker writes each
lane date, and `serve` rereads it at a request after a push (`CaughtUp`).
`SIGTERM` stops it; `SIGHUP` re-reads the config and, as
the board and the writer are built once, only says whether a restart is needed.
"""

import argparse
import logging
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple, Protocol

from starpulse.board.adapters.search import SearchIndex
from starpulse.board.application.queries.machine_tasks import MachineDeltas
from starpulse.board.application.queries.verdicts import Verdicts
from starpulse.board.bin.blocks import BoardConfig, board_built_blocks
from starpulse.board.model.board_feed import BoardFeed, LaneRecorder
from starpulse.board.model.board_feed import follow as follow_stream
from starpulse.board.model.feed.held import HeldSnapshot
from starpulse.board.model.feed.shared import LIVE_WINDOW_S
from starpulse.board.model.seam import Board
from starpulse.event_log import verdict_events
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.opening import database_url
from starpulse.event_log.readmodel.declared import declared_fields
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.readmodel.snapshot_store import SnapshotStore
from starpulse.event_log.store import EventStore
from starpulse.event_log.wake import StopEvent

logger = logging.getLogger(__name__)


class WriterStore(LaneRecorder, Protocol):
    """What the writer keeps its dating in (`HistoryStore`)."""

    def lane_path(self, task: str) -> list[dict]: ...


class Followers(NamedTuple):
    """What the producers above the Board announce to the feed, each a start `(feed, log, stop)` that `runtime` passes in as
    no context imports the others: the pull request projection, the runs projection with each opt-in worker's liveness,
    and the scheduler's status."""

    pulls: Callable[[BoardFeed, EventLog, StopEvent], object]
    runs: Callable[[BoardFeed, EventLog, StopEvent], object]
    scheduler: Callable[[BoardFeed, EventLog, StopEvent], object]


def reload(path: Path, config: BoardConfig, load: Callable[[Path | None], BoardConfig]) -> None:
    """Re-read `path`; an invalid config is logged, and a change to what the worker was built from asks for a restart."""
    try:
        new = load(path)
    except (OSError, ValueError) as exc:
        logger.error("reload: %s: %s; keeping the running config", path, exc)
        return
    if board_built_blocks(new) != board_built_blocks(config):
        logger.warning("reload: a database or board setting changed; restart the worker to apply it")
    else:
        logger.info("reload: no Board setting changed")


def start(
    config: BoardConfig,
    path: Path | None,
    base: Path,
    log: EventLog,
    stop: StopEvent,
    *,
    load: Callable[[Path | None], BoardConfig],
    assemble: Callable[..., tuple[Board, BoardFeed]],
    history_store: Callable[[BoardConfig, Path, Mapping[str, dict]], WriterStore],
    follow: Callable[..., object],
    followers: Followers,
    ready: Callable[[Board, BoardFeed], None] | None = None,
    snapshots: SnapshotStore | None = None,
    go: threading.Event | None = None,
) -> Callable[[], None]:
    """Start the Board writer's threads over `log`, each ending when `stop` is set, and return its reload. Its feed hears
    every change the snapshot draws: the read model's folds, the machine rows, the dates, the claim refusals, the verdicts,
    and what `followers` start. The read model's fold starts last; `ready` is then told the board and feed it folds, which another context in the process
    may share. With `snapshots`, the held snapshot stores its bodies and deltas there each fold. Raises `ValueError` as `assemble` does.

    With `go`, the writer starts as a standby beside the writer it replaces: it builds the feed and the held snapshot from
    the read model and follows what the old writer folds, folding and storing nothing itself. When `go` is set, which is
    once the old writer ended, it stores its snapshot as the first delta and folds the log from there, so there is one
    writer at any instant and no rebuild between the two."""
    model = ReadModel(log.engine, declared_fields(config.board))
    board, feed = assemble(config, base, None, model)
    feed.cap_lanes(
        LIVE_WINDOW_S
    )  # the live set: an older lane stays only for an open task, and decoding the rest is the worker's heap
    store = history_store(config, base, feed.machines)
    feed.ready.set()
    feed.record_lanes(store, log)  # the lane each write makes is recorded by `serve`; the Board child places none
    board.attach(log)
    held = HeldSnapshot(feed, store=None if go else snapshots)
    stop.listen(held.retire)  # a stream open tells its page the Board is stale from here until a writer stores again
    threading.Thread(
        target=held.run, args=(stop,), name="held-snapshot", daemon=True
    ).start()  # built whole, then folded
    MachineDeltas(feed, model).follow(stop, log)  # a context sharing this feed hears each machine row as a `move`

    def fold() -> None:
        search = SearchIndex.open(
            log.engine, config.search
        )  # the one fold indexes search, as the API's second fold once did
        projector = Projector(log.engine, EventStore(log.engine), search, log=log, drawn=feed.machines, keys=board.keys)
        follow(projector, feed, stop, log)

    if go is None:
        fold()
    else:
        standing = StopEvent()
        stop.listen(standing.set)
        following = follow(None, feed, standing, log)  # what the old writer folds, drawn without folding it

        def take_over() -> None:
            go.wait()
            standing.set()
            following.join()
            if stop.is_set() or snapshots is None:
                return
            held.take_over(snapshots)
            fold()

        threading.Thread(target=take_over, name="board-take-over", daemon=True).start()
    verdicts = Verdicts(feed)
    follow_stream(verdicts, log, verdict_events.STREAM, verdicts.handle_entry, stop=stop)  # the verdicts
    followers.pulls(feed, log, stop)  # the pull requests, which the ledgers draw
    followers.runs(feed, log, stop)  # the runs, the ledgers and each opt-in worker's liveness
    followers.scheduler(feed, log, stop)  # the scheduler status
    if ready is not None:
        ready(board, feed)
    return lambda: reload(path, config, load)


def main(
    argv: list[str] | None,
    parser: argparse.ArgumentParser,
    *,
    discover: Callable[[Path | None], Path | None],
    load: Callable[[Path | None], BoardConfig],
    assemble: Callable[..., tuple[Board, BoardFeed]],
    history_store: Callable[[BoardConfig, Path, Mapping[str, dict]], WriterStore],
    follow: Callable[..., object],
    followers: Callable[[argparse.ArgumentParser, BoardConfig], Followers],
    hold: Callable[[threading.Event, Callable[[], None]], None],
) -> None:
    """Run the Board writer; `runtime` passes the collaborators it builds (`assemble`, `history_store`, the read model's
    `follow`, `followers` and `hold`), as no context imports it."""
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
            config, path, base, log, stop, load=load, assemble=assemble, history_store=history_store, follow=follow,
            followers=followers(parser, config),
        )  # fmt: skip
    except ValueError as exc:
        stop.set()  # `worker_board` may have started its read model follower before the start refused
        parser.exit(1, f"{exc}\n")
    hold(stop, reload_config)
    stop.set()  # a hold that returns ends the process; a test's no-op hold leaves the loops to stop here
