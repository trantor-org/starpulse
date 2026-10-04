"""A flow view server on an ephemeral port, and a reader for its event stream."""

import json
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from http.client import HTTPResponse
from http.server import ThreadingHTTPServer
from pathlib import Path

from starpulse.board import MoveWriter, Written
from starpulse.board_feed import BoardFeed
from starpulse.harnesses import Harnesses
from starpulse.history import History, HistoryStore
from starpulse.server import _handler


def _no_writer(task: str, status: str) -> Written:
    raise AssertionError(f"the test reached the board writer: {task} {status}")


@contextmanager
def serve(
    tmp_path: Path,
    feed: BoardFeed | None = None,
    starts: Mapping[str, Callable[[str], str]] | None = None,
    history: History | None = None,
    run_safe: frozenset[str] = frozenset({"dagu/whole-repo-gate"}),
    writer: MoveWriter | None = None,
    harnesses: Harnesses | None = None,
) -> Iterator[ThreadingHTTPServer]:
    """Serve a stub build in `tmp_path` until the `with` block ends."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True, exist_ok=True)
    (static / "index.html").write_text("<!doctype html>")
    (static / "assets" / "index-abc123.js").write_text("")
    (tmp_path / "secret.txt").write_text("")
    handler = _handler(
        feed or BoardFeed(),
        static,
        starts or {},
        run_safe,
        history or HistoryStore("sqlite://", feed.machines if feed else {}),
        writer or _no_writer,
        harnesses,
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server
    finally:
        server.shutdown()


def url(server: ThreadingHTTPServer, path: str) -> str:
    return f"http://127.0.0.1:{server.server_port}{path}"


def next_event(resp: HTTPResponse) -> tuple[str, dict]:
    """The next named event on the stream, skipping its keep-alive comments."""
    name = ""
    while line := resp.readline().decode():
        if line.startswith("event: "):
            name = line.removeprefix("event: ").strip()
        elif line.startswith("data: "):
            return name, json.loads(line.removeprefix("data: "))
    raise AssertionError("the stream ended")
