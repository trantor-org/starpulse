"""What every `/api` module is handed, and the modules in the order their routes match.

`api_routes` is the routes under `/api`; `metrics.routes` is the one route that is not.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cached_property
from typing import TYPE_CHECKING

from starpulse.views.adapters.inbound.api import (
    analytics,
    board,
    docs,
    history,
    ledger,
    milestones,
    pulls,
    runs,
    scheduler,
    snapshot,
    tasks,
)
from starpulse.views.adapters.inbound.api.neutral import ApiRoute
from starpulse.views.adapters.inbound.api.pulls import PullReads
from starpulse.views.adapters.inbound.api.slow_reads import SlowReads
from starpulse.views.adapters.inbound.api.streams import Streams

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.history_window import HistoryWindow
    from starpulse.board.board_feed import BoardFeed
    from starpulse.board.model.seam import Board
    from starpulse.flow_metrics.adapters.outbound.history import History
    from starpulse.views.adapters.inbound.snapshot_cache import SnapshotCache
    from starpulse.views.ports.services import Services


@dataclass
class Api:
    """The seams the routes are made over. `build` is the page build's `build` event, which a stream sends on connect;
    `page_gauge` the page build's gauge for `/metrics`."""

    feed: BoardFeed
    history: History
    snapshots: SnapshotCache
    window: HistoryWindow
    board: Board
    services: Services
    clock: Callable[[], float] = time.time
    build: Callable[[], str | None] = lambda: None
    page_gauge: Callable[[], str] | None = None
    pull_reads: PullReads = field(init=False)  # made with the seams: it hears the store's saves from the start
    slow_reads: SlowReads = field(init=False)

    def __post_init__(self) -> None:
        self.pull_reads = PullReads(self.services.pulls)
        self.slow_reads = SlowReads("/api/pulls", self.services.slow_read_s)

    @cached_property
    def streams(self) -> Streams:
        return Streams(self.feed, self.snapshots, self.build)


def api_routes(api: Api) -> list[ApiRoute]:
    """Every route under `/api`, a resource at a time. Within a resource a more specific path comes before the one
    that also matches it: a ledger's stream before the ledger's read."""
    return [
        *snapshot.routes(api),
        *ledger.routes(api),
        *board.routes,
        *history.routes(api),
        *analytics.routes,
        *tasks.routes(api),
        *milestones.routes(api),
        *docs.routes(api),
        *runs.routes(api),
        *scheduler.routes(api),
        *pulls.routes(api),
    ]
