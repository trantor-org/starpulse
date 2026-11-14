"""The Delivery context's start, from the collaborators `starpulse worker pulls` and `contexts` hand it."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from starpulse.board.criteria_events import follow_criteria_events
from starpulse.board.holder_idle import follow_holder_idle
from starpulse.board.model.seam import (
    Board,
)
from starpulse.event_log import events as machine_events
from starpulse.event_log import lane_events
from starpulse.event_log.wake import StopEvent
from starpulse.pulls.adapters.inbound.delivery import (
    keep_beating,
)
from starpulse.pulls.adapters.inbound.task_actor import ACTOR, TaskActor, moves_of
from starpulse.pulls.adapters.outbound.pin_reader import GitHub
from starpulse.pulls.adapters.outbound.pull_requests import PullRequests
from starpulse.pulls.adapters.outbound.pull_store import PullSync
from starpulse.pulls.model.pins import LiveBuild, running_commit
from starpulse.runtime.config import Config

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog
    from starpulse.pulls.adapters.outbound.pulls import PullStore

logger = logging.getLogger(__name__)


def _then(first: Callable[[], None], second: Callable[[], None]) -> Callable[[], None]:
    """One callback that runs `first` and then `second`."""

    def both() -> None:
        first()
        second()

    return both


POLL_RESTART_S = (1.0, 60.0)  # the pull reader's first restart delay after a crash and the longest it backs off to


def keep_polling(
    sync: PullSync, stop: StopEvent, running: threading.Event, delay_s: tuple[float, float] = POLL_RESTART_S
) -> None:
    """Run the pull reader until `stop`, with `running` set while it runs, starting it again after a crash with a delay
    that doubles from `delay_s[0]` to `delay_s[1]`, and logging each crash. A run that lasts the longest delay starts
    the backoff over."""
    delay, longest = delay_s
    while not stop.is_set():
        started = time.monotonic()
        running.set()
        try:
            sync.serve_forever()
            return
        except Exception:
            logger.exception("pull requests: the poller crashed; restarting in %.0fs", delay)
        finally:
            running.clear()
        ran = time.monotonic() - started
        stop.wait(delay)
        delay = delay_s[0] if ran >= longest else min(delay * 2, longest)


def start_delivery(
    config: Config,
    board: Board,
    feed: BoardFeed,
    log: EventLog,
    pulls: PullStore,
    pins: GitHub,
    stop: StopEvent,
    *,
    after_project: Callable[[], None] | None = None,
) -> tuple[TaskActor | None, PullSync | None]:
    """Start the Delivery context: the task actor, the pull store's sync with the projection it feeds, and the
    unblock of dependents, as `config` asks. Returns the actor and the sync, each None when not started.

    The actor records the lane of each write it makes on `feed` (`BoardFeed.record_written`); `after_project` runs
    after each set of pull request rows reaches the feed. Raises `ValueError` naming a table the board cannot serve.
    """
    from starpulse.pulls.application.commands.ci_trail import CiTrail  # noqa: PLC0415 - the database stack loads when a store does

    # without the GitHub CLI there is no source, and a task simply carries no PR state; a config can turn the store off
    release = config.release
    live = LiveBuild(release.repo, running_commit) if release and release.settle == "release" else None
    actor = None
    if config.task_actor:
        if board.edit is None:
            raise ValueError("[board.actor] needs a board that edits tasks")
        actor = TaskActor(
            feed,
            pulls,
            board.edit,
            board.waits,
            moves_of(feed.machines["board"]),
            config.repos,
            config.release.settle if config.release else None,
            pins,
            config.board_repo,
            evaluate=board.evaluate,
            holds=board.holds,
            read=board.read,
            unfinished=board.unfinished,
            create=board.create,
            parked=board.parked,
            released=board.released,
            idle=board.idle,
            release=board.release,
            delivered=board.delivered,
            returned=board.returned,
            alive=board.alive,
            enqueued=board.enqueued,
            verifying=board.verifying,
            closed=board.closed,
            live=live,
            advance=lambda machine, task, event: machine_events.publish(
                machine, event, actor=ACTOR, task=task, log=log
            ),
            sequences=config.sequences,
            log=log,
        )
        actor.start(stop)
        follow_criteria_events(actor.criteria_changed, board.evaluate, log, stop)
        follow_holder_idle(actor.holder_settled, log, stop)
    if board.entered:
        lane_events.follow_entered(board.entered, log, stop)
    sync = None
    if config.pull_requests and shutil.which("gh"):
        pull_requests = PullRequests(
            feed,
            pulls,
            repos=config.repos,
            pins=pins,
            trail=CiTrail(log) if config.ci else None,
            published=after_project,
        )
        pulls.subscribe(pull_requests.rebuild)  # each save reaches the snapshot at once, not behind a pin walk
        project = pull_requests.refresh
        if actor:  # the actor reads each save at once and the pins after each projection
            pulls.subscribe(actor.store_changed)
            project = _then(actor.timed_projection(project), actor.pulls_changed)
        sync = PullSync(pulls, feed, config.repos, project=project, stop=stop)
        running = threading.Event()
        keep_beating(log, running, stop)
        threading.Thread(target=keep_polling, args=(sync, stop, running), name="pull-reader", daemon=True).start()
    if config.release is not None:
        if board.edit is None or not (feed.roles.waiting and feed.roles.ready):
            raise ValueError("[release] needs a board that edits tasks and draws waiting and ready lanes")
    return actor, sync

