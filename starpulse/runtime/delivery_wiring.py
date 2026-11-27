"""The Delivery context's start, from the collaborators `starpulse worker pulls` and `contexts` hand it."""

import os
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from starpulse.board.adapters.holder_idle import follow_holder_idle, started
from starpulse.board.adapters.task_links import TaskLinks, hold_by_link
from starpulse.board.adapters.until_events import follow_until_events
from starpulse.board.model.seam import (
    Board,
)
from starpulse.bridge.last_event import last_event_is, last_event_sha
from starpulse.bridge.subjects import subject_for
from starpulse.event_log import events as machine_events
from starpulse.event_log import lane_events
from starpulse.event_log.readmodel.read_model import ReadModel
from starpulse.event_log.start_requests import follow_admitted, follow_failed
from starpulse.event_log.wake import StopEvent
from starpulse.github.adapters.outbound.head_reader import GitHubReader
from starpulse.github.adapters.outbound.rest import connect, pull_mergeable
from starpulse.pulls.adapters.inbound.task_actor import ACTOR, TaskActor, moves_of
from starpulse.pulls.adapters.outbound.main_green import MainGreen
from starpulse.pulls.adapters.outbound.pin_reader import GitHub
from starpulse.pulls.adapters.outbound.pull_reads import settle_checks
from starpulse.pulls.adapters.outbound.pull_requests import PullRequests, coalesced
from starpulse.pulls.adapters.outbound.unfinished import submodule_paths
from starpulse.pulls.model.pins import LiveBuild, running_commit
from starpulse.runtime.config import Config

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.model.board_feed import BoardFeed
    from starpulse.event_log.event_log import EventLog
    from starpulse.pulls.adapters.outbound.pulls import PullStore
lazy from starpulse.pulls.application.commands.ci_trail import CiTrail

_MERGEABLE_TIMEOUT = 10.0


def _then(first: Callable[[], None], second: Callable[[], None]) -> Callable[[], None]:
    """One callback that runs `first` and then `second`."""

    def both() -> None:
        first()
        second()

    return both


def _main_green(config: Config, pins: GitHub) -> MainGreen | None:
    if not (config.owner_source and config.board_repo):
        return None
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return MainGreen(config.board_repo, pins.head, GitHubReader(connect(token, caller="delivery_wiring")))


def _stranded_checks(pulls: PullStore) -> Callable[[dict[str, Any]], None] | None:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return None
    reader = GitHubReader(connect(token, caller="delivery_wiring"))
    return lambda record: settle_checks(pulls, reader, record, time.time())


def archiving(board: Board) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """`board.edit` and `board.judge`, but a status write of `archived` goes through the board's archiver, which the field
    edit refuses, and is judged as no field change."""

    def edit(name: str, changes: Any, comment: str = "", /, actor: str = "", over: str = "") -> Any:
        if changes.get("status") == "archived":
            return board.archive(name, comment, actor)
        return board.edit(name, changes, comment, actor=actor, over=over)

    def judge(name: str, changes: Any, comment: str = "", /, *args: Any, **kwargs: Any) -> Any:
        return board.judge(name, {} if changes.get("status") == "archived" else changes, comment, *args, **kwargs)

    return edit, judge


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
) -> tuple[TaskActor | None, Callable[[], None] | None]:
    """Start the Delivery context: the task actor, the projection of the pull store to the Board, and the unblock of
    dependents, as `config` asks. Returns the actor and the projection's ask (call it when the store changed), each None
    when not started.

    The actor records the lane of each write it makes on `feed` (`BoardFeed.record_written`); `after_project` runs
    after each set of pull request rows reaches the feed. Raises `ValueError` naming a table the board cannot serve.
    """
    # a config can turn the store off, and a task then carries no PR state
    release = config.release
    live = LiveBuild(release.repo, running_commit) if release and release.settle == "release" else None
    actor = None
    if config.task_actor:
        if config.board_type != "native":
            raise ValueError("[board.actor] needs a board that edits tasks")
        edit, judge = archiving(board)
        actor = TaskActor(
            feed,
            pulls,
            edit,
            board.waits,
            moves_of(feed.machines["board"]),
            judge,
            config.repos,
            config.release.settle if config.release else None,
            pins,
            config.board_repo,
            latest=lambda subject, since: last_event_is(log.engine, subject, since),
            started=lambda task: started(log.engine, task),
            hold=lambda task, session: hold_by_link(TaskLinks(log.engine), ReadModel(log.engine))(task, session),
            latest_sha=lambda subject: last_event_sha(log.engine, subject),
            holds=board.holds,
            read=board.read,
            unfinished=board.unfinished,
            submodules=(lambda: submodule_paths(config.gitmodules)) if config.gitmodules else None,
            unpublished=board.unpublished,
            parked=board.parked,
            released=board.released,
            idle=board.idle,
            end=config.session_harness().end_with(config.bridge.end),
            end_lanes=frozenset(config.bridge.end_lanes),
            returned=board.returned,
            alive=board.alive,
            enqueued=board.enqueued,
            closed=board.closed,
            archived=board.archived,
            frozen=board.frozen,
            halted=board.halted,
            live=live,
            main_green=_main_green(config, pins),
            owner_source=config.owner_source,
            mergeable=lambda repo, number: pull_mergeable(repo, number, _MERGEABLE_TIMEOUT),
            checks=_stranded_checks(pulls),
            advance=lambda machine, task, event: machine_events.publish(
                machine, event, actor=ACTOR, task=task, log=log
            ),
            sequences=config.sequences,
            awaits=config.awaits,
            log=log,
        )
        # the follower takes its cursor first: an event after the actor's gate lookups is then heard, never missed
        follow_until_events(actor.event_seen, lambda entry: subject_for(config.bridge.board, entry), log, stop)
        actor.start(stop)
        follow_holder_idle(
            actor.holder_settled,
            log,
            stop,
            actor.indexed,
            actor.working,
            actor.holder_ended,
            actor.holder_entered,
            actor.lane_entered,
            dispatched=actor.dispatched,
            lease_ended=actor.session_ended,
            unstarted=actor.unstarted,
            closed=actor.closed,
            covered=actor.nudged_since,
        )
        follow_admitted(actor.admitted, log, stop)
        follow_failed(actor.start_failed, log, stop)
    lane_events.follow_entered(board.entered, log, stop)
    projected = None
    if config.pull_requests:
        pull_requests = PullRequests(
            feed,
            pulls,
            repos=config.repos,
            pins=pins,
            trail=CiTrail(log) if config.ci else None,
            published=after_project,
        )
        pulls.subscribe(pull_requests.rebuild_soon(stop))  # a save reaches the snapshot soon, behind no lock
        project = pull_requests.refresh
        if actor:  # the actor reads each save at once and the pins after each projection
            pulls.subscribe(actor.store_changed)
            project = _then(actor.timed_projection(project), actor.pulls_changed)
        # one projection once the Board replay is done, so it sees every task, then one for each event that changed a
        # record: the pin walk behind it can take minutes, so it runs on a thread of its own
        projected = coalesced(stop, project, "pull-project", after=feed.wait_replayed)
        feed.on_relinked(lambda _: projected())  # a link written or removed changes which pull requests a task reads
    if config.release is not None:
        if not (feed.roles.waiting and feed.roles.ready):
            raise ValueError("[release] needs a board that edits tasks and draws waiting and ready lanes")
    return actor, projected
