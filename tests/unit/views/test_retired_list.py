"""`GET /api/retired?fields=dependencies` answers the edges of every retired task without holding their texts."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from starlette.testclient import TestClient
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.views.adapters.inbound.api import metrics
from starpulse.views.adapters.inbound.api.routing import Api, api_routes
from starpulse.views.adapters.inbound.asgi_app import PageApp
from starpulse.views.adapters.inbound.snapshots import Snapshots
from starpulse.views.application.commands.tasks import retired_list
from starpulse.views.ports.services import Services

from tests.fake_board import bare_board

_TEXT = "---\nid: TASK-2\ndependencies:\n  - TASK-1\n---\nbody\n"


def test_the_dependencies_projection_reads_through_the_boards_projecting_reader() -> None:
    def refuse_whole_rows(task: str, milestone: str) -> list:
        raise AssertionError("the texts of every retired task were read at once")

    board = bare_board(
        retired=refuse_whole_rows,
        retired_projected=lambda project, task, milestone: [("TASK-2", project(_TEXT))],
    )

    assert retired_list(board, "", "", "dependencies") == (200, {"tasks": [{"task": "TASK-2", "dependencies": ["TASK-1"]}]})


def test_the_dependencies_projection_of_a_board_that_cannot_project_reads_its_rows() -> None:
    rows = [{"task": "TASK-2", "name": "task-2.md", "text": _TEXT}]
    board = bare_board(retired=lambda task, milestone: rows)

    assert retired_list(board, "", "", "dependencies") == (200, {"tasks": [{"task": "TASK-2", "dependencies": ["TASK-1"]}]})


def test_whole_dumps_of_the_retired_tasks_are_built_one_at_a_time_on_one_thread(tmp_path: Path) -> None:
    """Each request thread keeps the heap pages of the dump it built (free-threaded mimalloc), so concurrent dumps
    multiply the process's memory by their number; built on one thread they reuse the same few pages."""
    feed = BoardFeed()
    log = EventLog(f"sqlite:///{tmp_path / 'settings.sqlite'}")
    running, overlap, lock = 0, 0, threading.Lock()
    builders: set[str] = set()

    def dump(task: str, milestone: str) -> list:
        nonlocal running, overlap
        with lock:
            running += 1
            overlap = max(overlap, running)
            builders.add(threading.current_thread().name)
        time.sleep(0.05)
        with lock:
            running -= 1
        return []

    routes = Api(
        feed=feed,
        history=HistoryStore(f"sqlite:///{tmp_path / 'history.sqlite'}", feed.machines),
        snapshots=Snapshots(feed),
        window=HistoryWindow(feed, 6, log),
        board=bare_board(retired=dump),
        services=Services(slow_read_s=0.0),
    )
    app = PageApp(api_routes(routes), metrics.routes, tmp_path, (), seams=routes)
    with TestClient(app, client=("127.0.0.1", 50000)) as client, ThreadPoolExecutor(6) as pool:
        statuses = list(pool.map(lambda _: client.get("/api/retired").status_code, range(6)))

    assert statuses == [200] * 6
    assert overlap == 1
    assert len(builders) == 1
