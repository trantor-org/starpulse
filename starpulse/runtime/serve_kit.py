"""The helpers that drive an adapter through StarPulse's own server and feed, which `adapter_kit` exports."""

import json
import time
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.client import HTTPResponse
from pathlib import Path
from typing import Any

from starpulse.board.adapters.display_settings import DisplaySettings
from starpulse.board.adapters.history_window import HistoryWindow
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.seam import Board, Written
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.machine_engine.model.transitions import DEFAULT_STATUSES
from starpulse.runtime.config import Config
from starpulse.runtime.placed import Placed
from starpulse.runtime.placed import assembled as placed_assembled
from starpulse.runtime.store_migrate import maintain
from starpulse.runtime.stored_snapshot import stored_snapshots
from starpulse.views.adapters.inbound.asgi_app import page_app
from starpulse.views.adapters.inbound.page_server import PageServer
from starpulse.views.ports.services import Services

#: How long a settle or a served page waits for the Board writer to fold what was published.
FOLDED_WITHIN_S = 30.0


def _nothing(*_: Any) -> None:
    pass


def _refused(*_: Any, **__: Any) -> Written:
    return Written(False, "this board holds no tasks", unavailable=True)


def _absent(*_: Any) -> None:
    return None


def refusing(**fields: Any) -> Board:
    """A Board that holds no tasks: every write refuses and every read finds nothing; `fields` replace its parts."""
    return Board(
        **{
            "machines": lambda qualify, workflows: {},
            "start": _nothing,
            "keys": None,
            "cues": lambda _qualify: (),
            "waits": {},
            "roles": StateRoles.of_statuses(DEFAULT_STATUSES),
            "writer": _refused,
            "assign": _refused,
            "source": "the events instances forward",
            "read": _absent,
            "read_archived": _absent,
            "edit": _refused,
            "judge": _refused,
            "archive": _refused,
            "restore": _refused,
            "standing": _absent,
            "readable": lambda *_: "",
            "complete": _refused,
            "reopen": _refused,
            "retire": _refused,
            "retired": lambda *_: (),
            "retired_projected": lambda *_: [],
            "retired_page": lambda *_: ([], None),
            "create": _refused,
            "milestones": lambda: [],
            "read_milestone": _absent,
            "create_milestone": _refused,
            "edit_milestone": _refused,
            "archive_milestone": _refused,
            "read_doc": _absent,
            "create_doc": _refused,
            "edit_doc": _refused,
            "archive_doc": _refused,
            "restore_doc": _refused,
            "move_doc": _refused,
            "holds": lambda *_: (),
            "unfinished": lambda *_: (),
            "unpublished": lambda *_: None,
            "parked": _nothing,
            "released": _nothing,
            "idle": None,
            "returned": _nothing,
            "alive": lambda *_: False,
            "enqueued": _nothing,
            "closed": _nothing,
            "archived": _nothing,
            "frozen": _nothing,
            "halted": _nothing,
            "faulted": None,
            "entered": _nothing,
            "attach": _nothing,
            **fields,
        }
    )


@contextmanager
def serve(
    tmp_path: Path,
    feed: BoardFeed | None = None,
    board: Board | None = None,
    *,
    history: HistoryStore | None = None,
    window: HistoryWindow | None = None,
    clock: Callable[[], float] = time.time,
    port: int = 0,
    tls: tuple[Path, Path] | None = None,
    migrated: bool = False,
    **services: Any,
) -> Iterator[PageServer]:
    """Serve a stub build in `tmp_path` until the `with` block ends. `board` is the Board the routes write through (a
    refusing one when None); `services` are the `Services` fields.
    `migrated` says the stores in `tmp_path` are already migrated, so the serve skips the pass that migrates them."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<!doctype html>")
    (static / "assets" / "index-abc123.js").write_text("")
    (tmp_path / "secret.txt").write_text("")
    drawn = None if feed else Placed()
    served = feed or drawn.draw()
    machines = feed.machines if feed else {}
    settings, kept = f"sqlite:///{tmp_path / 'settings.sqlite'}", f"sqlite:///{tmp_path / 'history.sqlite'}"
    for store in () if migrated else (settings, kept):
        maintain(store, machines)
    log = EventLog(settings)
    board = board or refusing()
    stop = StopEvent()
    snapshots = server = None
    try:
        # it publishes a snapshot change: before the writer starts, it builds with it
        window = window or HistoryWindow(served, 6, log)
        snapshots = stored_snapshots(served, log, stop)
        app = page_app(
            served,
            snapshots,
            static,
            history or HistoryStore(kept, machines),
            window,
            board,
            Services(display=DisplaySettings(log), **services),
            clock,
        )
        server = PageServer(
            app, ("127.0.0.1", port), tls=tls, stopping=lambda: snapshots.announce("restarting", {"at": time.time()})
        )
        server.caught_up = snapshots.caught_up
        if not snapshots.caught_up(FOLDED_WITHIN_S):  # the window `page_app` drew is folded, or a stream sends it late
            raise TimeoutError(f"the Board writer folded no change in {FOLDED_WITHIN_S} s")
        server.start()
        yield server
    finally:
        if server is not None:
            server.close()
        stop.set()
        # a reader of the log still mid-step reopens it after the close, and a thread starved under load has not begun
        readers = snapshots.readers if snapshots is not None else []
        for reader in readers:
            reader.join(30)
        if running := [reader.name for reader in readers if reader.is_alive()]:
            raise RuntimeError(f"a reader still runs 30 s after the stop, so the log stays open: {running}")
        log.close()
        if drawn:
            drawn.close()


def url(server: PageServer, path: str) -> str:
    return f"http://127.0.0.1:{server.server_port}{path}"


def subscribe(server: PageServer, query: str, variables: dict[str, Any] | None = None) -> HTTPResponse:
    """The open `/graphql` stream of the subscription `query`, whose first `next` event `next_event` reads."""
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    request = urllib.request.Request(url(server, "/graphql"), data=body, headers={"content-type": "application/json"})
    return urllib.request.urlopen(request, timeout=5)


def next_event(resp: HTTPResponse) -> tuple[str, dict]:
    """The next named event on the stream, skipping its keep-alive comments."""
    name = ""
    while line := resp.readline().decode():
        if line.startswith("event: "):
            name = line.removeprefix("event: ").strip()
        elif line.startswith("data: "):
            return name, json.loads(line.removeprefix("data: "))
    raise AssertionError("the stream ended")


def assembled(config: Config, base: Path) -> tuple[Board, BoardFeed]:
    """The board the config's `[board]` adapter builds and the feed that draws it, as `starpulse serve` assembles them.

    `base` is the directory the config's relative paths are read from.
    """
    board, feed, _ = placed_assembled(config, base)
    return board, feed
