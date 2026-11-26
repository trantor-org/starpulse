"""What every `/api` module is handed, and the modules in the order their routes match.

`api_routes` is the routes under `/api`; `metrics.routes` and `intake.routes` are the ones that are not.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property, partial
from typing import TYPE_CHECKING

from starpulse.views.adapters.inbound.api import (
    admin,
    board,
    docs,
    history,
    jobs,
    machines,
    milestones,
    openapi,
    snapshot,
    steps,
    tasks,
    view_queries,
)
from starpulse.views.adapters.inbound.api.table import ApiRoute
from starpulse.views.adapters.inbound.api.streams import Streams
from starpulse.views.adapters.outbound.storage_metrics import cached

if TYPE_CHECKING:  # annotation only: a runtime import would put the scheduler in the Delivery worker's import closure
    from starpulse.board.adapters.history_window import HistoryWindow
    from starpulse.board.model.board_feed import BoardFeed
    from starpulse.board.model.seam import Board
    from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
    from starpulse.views.adapters.inbound.snapshots import Snapshots
    from starpulse.views.ports.services import Services


@dataclass
class Api:
    """The seams the routes are made over. `build` is the page build's `build` event, which a stream sends on connect;
    `page_gauge` the page build's gauge for `/metrics`."""

    feed: BoardFeed
    history: HistoryStore
    snapshots: Snapshots
    window: HistoryWindow
    board: Board
    services: Services
    clock: Callable[[], float] = time.time
    build: Callable[[], str | None] = lambda: None
    page_gauge: Callable[[], str] | None = None

    @cached_property
    def exposition(self) -> Callable[[], str]:
        """The `/metrics` page: one render per `scrape_cache_s`, else one per scrape."""
        from starpulse.views.adapters.inbound.api.metrics import render  # metrics imports this module's seams

        read = partial(render, self)
        span = self.services.scrape_cache_s
        return cached(read, span) if span else read

    @cached_property
    def streams(self) -> Streams:
        return Streams(self.feed, self.snapshots, self.build, self.services.ready, self.clock)


def api_routes(api: Api) -> list[ApiRoute]:
    """Every route under `/api`, a resource at a time. Within a resource a more specific path comes before the one
    that also matches it."""
    return [
        *snapshot.routes(api),
        *board.routes(api),
        *history.routes(api),
        *tasks.routes(api),
        *machines.routes(api),
        *milestones.routes(api),
        *docs.routes(api),
        *jobs.routes(api),
        *admin.routes(api),
        *steps.routes,
        *view_queries.routes,
        *openapi.routes,
    ]
