"""The followers the Board writer starts on its feed for the producers above the Board: `board_worker` imports none of them."""

from collections.abc import Sequence
from types import ModuleType

from starpulse.board.bin.board_worker import Followers
from starpulse.board.model.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.pulls.adapters.inbound.delivery import Projected as PullsProjected
from starpulse.runs.application.queries.projection import Projected as RunsProjected
from starpulse.runs.model import opt_in
from starpulse.runs.model.config import RunsInstance
from starpulse.scheduler.adapters.remote import follow_status


def feed_followers(adapters: Sequence[tuple[RunsInstance, ModuleType]]) -> Followers:
    """The pulls, runs and scheduler followers; the runs one watches the liveness of each opt-in worker in `adapters`."""
    opted_in = [instance.name for instance, adapter in adapters if opt_in.worker_of(adapter)]

    def pulls(feed: BoardFeed, log: EventLog, stop: StopEvent) -> None:
        PullsProjected(log, feed).follow(stop)

    def runs(feed: BoardFeed, log: EventLog, stop: StopEvent) -> None:
        RunsProjected(log, feed, {name: opt_in.Liveness(log, name) for name in opted_in}).follow(stop)

    return Followers(pulls=pulls, runs=runs, scheduler=lambda feed, log, stop: follow_status(log, feed, stop))
