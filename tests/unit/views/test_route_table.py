"""The page app's route table: every path, its methods and the order a request is matched in."""

from __future__ import annotations

from pathlib import Path

from starlette.routing import BaseRoute, Mount, Route
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.adapters.inbound.asgi_app import PageApp, page_app

from tests.fake_board import bare_board

_READ = ("GET", "HEAD")

# In match order, a mount's children in place of the mount: `/api` holds every resource's routes, a resource at a time,
# then `/metrics`, the page and the static files.
_TABLE = [
    # the snapshot and the event streams
    ("/api/events", _READ),
    ("/api/held", _READ),
    ("/api/lanes", _READ),
    ("/api/events/body/{key:path}", _READ),
    ("/api/snapshot", _READ),
    # a ledger: its stream, then its read
    ("/api/ledger/{rest:path}/events", _READ),
    ("/api/ledger/{rest:path}", _READ),
    # the board's reads
    ("/api/doctor", _READ),
    ("/api/machines", _READ),
    ("/api/done", _READ),
    ("/api/search", _READ),
    ("/api/harnesses", _READ),
    # the history and its window
    ("/api/history", _READ),
    ("/api/history-window", _READ),
    ("/api/history-window", ("DELETE", "PUT")),
    # analytics
    ("/api/analytics/health", _READ),
    ("/api/analytics/sessions", _READ),
    ("/api/analytics/steps", _READ),
    ("/api/analytics/transitions", _READ),
    ("/api/analytics/cells", _READ),
    ("/api/analytics/graph", _READ),
    ("/api/analytics/stages", _READ),
    ("/api/analytics/cost-to-go", _READ),
    ("/api/analytics/diff", _READ),
    ("/api/analytics/missed-loads", _READ),
    ("/api/analytics/trace-clusters", _READ),
    # tasks
    ("/api/task/{id:path}", _READ),
    ("/api/retired", _READ),
    ("/api/move", ("POST",)),
    ("/api/start", ("POST",)),
    ("/api/edit", ("POST",)),
    ("/api/archive", ("POST",)),
    ("/api/verdict", ("POST",)),
    ("/api/rating", ("POST",)),
    ("/api/miss", ("POST",)),
    ("/api/restore", ("POST",)),
    ("/api/take-over", ("POST",)),
    ("/api/retire", ("POST",)),
    ("/api/retired/import", ("POST",)),
    ("/api/claim", ("POST",)),
    ("/api/park", ("POST",)),
    ("/api/review", ("POST",)),
    ("/api/complete", ("POST",)),
    ("/api/tasks", ("POST",)),
    # milestones
    ("/api/milestones/{id:path}", _READ),
    ("/api/milestones", _READ),
    ("/api/milestones", ("POST",)),
    ("/api/milestones/edit", ("POST",)),
    ("/api/milestones/archive", ("POST",)),
    # docs
    ("/api/docs/{id:path}", _READ),
    ("/api/docs", _READ),
    ("/api/docs", ("POST",)),
    ("/api/docs/edit", ("POST",)),
    ("/api/docs/archive", ("POST",)),
    ("/api/docs/restore", ("POST",)),
    # runs
    ("/api/run/{name:path}", ("POST",)),
    ("/api/runs/{instance}/{workflow}/rerun", ("POST",)),
    ("/api/machine-events", ("POST",)),
    # the scheduler
    ("/api/scheduler", _READ),
    ("/api/scheduler", ("PUT",)),
    # pulls
    ("/api/pulls", _READ),
    ("/api/pulls/refresh", ("POST",)),
    # metrics, beside `/api`
    ("/metrics", _READ),
    # the page and the static files
    ("/", _READ),
    ("/board", _READ),
    ("/runs", _READ),
    ("/flow/{flow}", _READ),
    ("/{path:served}", _READ),
]


def _flat(routes: list[BaseRoute]) -> list[Route]:
    """The routes in match order, each mount's children in place of the mount with the mount's path in front of theirs."""
    flat: list[Route] = []
    for route in routes:
        if isinstance(route, Mount):
            flat.extend(
                Route(route.path + child.path, child.endpoint, methods=child.methods) for child in _flat(route.routes)
            )
        elif isinstance(route, Route):
            flat.append(route)
    return flat


def _app(tmp_path: Path) -> PageApp:
    feed = BoardFeed()
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    return page_app(feed, tmp_path, HistoryStore("sqlite://", feed.machines), HistoryWindow(feed, 6, log), bare_board())


def test_the_route_table_holds_every_path_method_and_order(tmp_path: Path) -> None:
    app = _app(tmp_path)

    assert [(route.path, tuple(sorted(route.methods or ()))) for route in _flat(app._app.routes)] == _TABLE


def test_every_api_route_is_one_mount_of_resource_modules(tmp_path: Path) -> None:
    mounts = [route for route in _app(tmp_path)._app.routes if isinstance(route, Mount)]

    assert [mount.path for mount in mounts] == ["/api"]
    modules = {child.endpoint.__module__ for child in mounts[0].routes if isinstance(child, Route)}
    assert modules
    assert all(module.startswith("starpulse.views.adapters.inbound.api.") for module in modules)
