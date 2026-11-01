"""`starpulse worker board`: the Board context's writer (the thread that dates when each Waiting task's Start Criteria
were met) as its own process, beside `serve`.

`board-release` is not here: the release of dependents runs in the Delivery worker (`starpulse worker pulls`).

It reads the config and the database `serve` does and meets `serve` only in the history there: this worker writes when
each task's criteria were met (`HistoryStore.save_criteria_met`), and `serve` rereads it on a timer
(`BoardFeed.follow_criteria`). The writer is resumable by construction: the dates are read back from the history at
start, so a task whose criteria stay met keeps the moment it was first seen so, and it waits for the Board to be read
before it evaluates, so a replay in progress forgets no date. `SIGTERM` stops it; `SIGHUP` re-reads the config and, as
the board and the writer are built once, only says whether a restart is needed.
"""

from __future__ import annotations

import argparse
import logging
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol

from starpulse.board.bin.blocks import BoardConfig, board_built_blocks
from starpulse.board.board_feed import BoardFeed, CriteriaStore, ExpiriesStore, LaneRecorder
from starpulse.board.criteria import Evaluator
from starpulse.board.model.seam import Board
from starpulse.event_log.event_log import Entry, EventLog, Tail
from starpulse.event_log.events import STREAM as MACHINE_STREAM
from starpulse.event_log.opening import database_url
from starpulse.event_log.readmodel.declared import declared_fields
from starpulse.event_log.readmodel.projector import Projector
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.store import EventStore

logger = logging.getLogger(__name__)


class WriterStore(LaneRecorder, CriteriaStore, ExpiriesStore, Protocol):
    """What the criteria thread keeps its dating in (`HistoryStore`)."""

    def lane_path(self, task: str) -> list[dict]: ...


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


def start_writers(
    feed: BoardFeed,
    store: WriterStore,
    evaluate: Callable[[str, str], list[dict]] | None,
    stop: threading.Event,
    live: bool = True,
    log: EventLog | None = None,
) -> threading.Thread:
    """Start the criteria thread, which runs until `stop` is set; it waits for `feed` to have read the Board. A `live`
    feed also records each lane a task enters as it places it; the Board child places none live, as `serve` records the
    ones its writes make. `log` carries each lane change's actor to the `board:lanes`
    entry."""
    feed.date_lanes(store.lane_path)
    feed.record_lanes(store, log, live=live)
    feed.track_criteria(evaluate, store)

    def keep() -> None:
        feed.ready.wait()
        feed.keep_criteria(stop)

    criteria = threading.Thread(target=keep, name="board-criteria", daemon=True)
    criteria.start()
    return criteria


#: The runs adapter's stream (`runs.run_events.STREAM`), named here because the Board imports no other context.
RUNS_STREAM = "runs:events"
ENDED = frozenset({"succeeded", "failed", "aborted", "skipped"})
PULL_REQUEST_MACHINE = "github-pull-request"
EVENT_POLL_S = 0.5


def criteria_topic(entry: Entry) -> str | None:
    """The topic a criterion's `refresh.on` names that `entry` announces: `run:<dag>` for a run that ended, `merge` for a
    merged pull request, else None."""
    fields = entry.fields
    if entry.stream == RUNS_STREAM:
        ended = "step" not in fields and fields.get("status") in ENDED
        return f"run:{fields.get('workflow')}" if ended else None
    merged = fields.get("machine") == PULL_REQUEST_MACHINE and fields.get("event") == "PR_MERGED"
    return "merge" if entry.stream == MACHINE_STREAM and merged else None


def follow_criteria_events(
    feed: BoardFeed,
    evaluate: Callable[[str, str], list[dict]] | None,
    log: EventLog,
    stop: threading.Event,
) -> threading.Thread | None:
    """Evaluate the Start Criteria again within seconds of the event they await, so they poll only as a net. Each run
    that ends or pull request that merges after this call invalidates the results that name it and wakes `feed`'s
    criteria pass. None when `evaluate` keeps no hints to invalidate."""
    if not isinstance(evaluate, Evaluator):
        return None

    def handle(entry: Entry) -> None:
        if (topic := criteria_topic(entry)) and evaluate.invalidate(topic):
            feed.evaluate_criteria()

    tail = Tail.live(log, RUNS_STREAM, streams=[RUNS_STREAM, MACHINE_STREAM], interval=EVENT_POLL_S)
    thread = threading.Thread(target=tail.run, args=(handle, stop), name="board-criteria-events", daemon=True)
    thread.start()
    return thread


def start(
    config: BoardConfig,
    path: Path | None,
    base: Path,
    log: EventLog,
    stop: threading.Event,
    *,
    load: Callable[[Path | None], BoardConfig],
    assemble: Callable[..., tuple[Board, BoardFeed]],
    history_store: Callable[[BoardConfig, Path, Mapping[str, dict]], WriterStore],
    follow: Callable[..., object],
    ready: Callable[[Board, BoardFeed], None] | None = None,
) -> Callable[[], None]:
    """Start the Board writer's threads over `log`, each ending when `stop` is set, and return its reload. The read
    model's fold starts last; `ready` is then told the board and feed it folds, which another context in the process
    may share. Raises `ValueError` as `assemble` does."""
    model = ReadModel(log.engine, declared_fields(config.board))
    board, feed = assemble(config, base, None, [], model)
    store = history_store(config, base, feed.machines)
    feed.ready.set()
    start_writers(feed, store, board.evaluate, stop, live=False, log=log)
    follow_criteria_events(feed, board.evaluate, log, stop)
    if board.attach is not None:
        board.attach(log)  # the sweep's releases append the History events the read model folds
    if board.sweep is not None:
        board.sweep(feed, log, store.save_claim_expiries)
    follow(Projector(log.engine, EventStore(log.engine)), feed, stop)
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
    hold: Callable[[threading.Event, Callable[[], None]], None],
) -> None:
    """Run the Board writer; `runtime` passes the collaborators it builds (`assemble`, `history_store`, the read model's
    `follow` and `hold`), as no context imports it."""
    args = parser.parse_args(argv)
    path = discover(args.config)
    try:
        config = load(path)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{path}: {exc}\n")
    base = args.config.parent if args.config else Path.cwd()
    log = EventLog(database_url(config.database_url, base))
    stop = threading.Event()
    try:
        reload_config = start(
            config, path, base, log, stop, load=load, assemble=assemble, history_store=history_store, follow=follow
        )
    except ValueError as exc:
        parser.exit(1, f"{exc}\n")
    hold(stop, reload_config)
