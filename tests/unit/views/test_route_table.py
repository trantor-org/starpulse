"""The page app's route table: every path, its methods and the order a request is matched in."""

from __future__ import annotations

from pathlib import Path

from starlette.routing import Route
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.adapters.inbound.asgi_app import page_app

from tests.fake_board import bare_board

_READ = ("GET", "HEAD")

# In match order: the streams, the reads, the writes, the page and the static files.
_TABLE = [
    ("/api/events", _READ),
    ("/api/held", _READ),
    ("/api/lanes", _READ),
    ("/api/ledger/{rest:path}/events", _READ),
    ("/api/events/body/{key:path}", _READ),
    ("/api/ledger/{rest:path}", _READ),
    ("/api/task/{id:path}", _READ),
    ("/api/milestones/{id:path}", _READ),
    ("/api/docs/{id:path}", _READ),
    ("/api/snapshot", _READ),
    ("/api/doctor", _READ),
    ("/api/machines", _READ),
    ("/api/done", _READ),
    ("/api/history", _READ),
    ("/api/pulls", _READ),
    ("/api/search", _READ),
    ("/metrics", _READ),
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
    ("/api/milestones", _READ),
    ("/api/docs", _READ),
    ("/api/retired", _READ),
    ("/api/harnesses", _READ),
    ("/api/history-window", _READ),
    ("/api/scheduler", _READ),
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
    ("/api/milestones", ("POST",)),
    ("/api/milestones/edit", ("POST",)),
    ("/api/milestones/archive", ("POST",)),
    ("/api/docs", ("POST",)),
    ("/api/docs/edit", ("POST",)),
    ("/api/docs/archive", ("POST",)),
    ("/api/docs/restore", ("POST",)),
    ("/api/run/{name:path}", ("POST",)),
    ("/api/runs/{instance}/{workflow}/rerun", ("POST",)),
    ("/api/pulls/refresh", ("POST",)),
    ("/api/machine-events", ("POST",)),
    ("/api/scheduler", ("PUT",)),
    ("/api/history-window", ("DELETE", "PUT")),
    ("/", _READ),
    ("/board", _READ),
    ("/runs", _READ),
    ("/flow/{flow}", _READ),
    ("/{path:served}", _READ),
]


def test_the_route_table_holds_every_path_method_and_order(tmp_path: Path) -> None:
    feed = BoardFeed()
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    app = page_app(feed, tmp_path, HistoryStore("sqlite://", feed.machines), HistoryWindow(feed, 6, log), bare_board())

    routes = [route for route in app._app.routes if isinstance(route, Route)]

    assert [(route.path, tuple(sorted(route.methods or ()))) for route in routes] == _TABLE
