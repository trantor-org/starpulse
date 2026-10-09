"""The autopilot served against a native board: a task entering the eligible lane starts a session within a sampler
period by an event alone, and a board with no `[autopilot]` block and no `session_start_url` starts it in tmux."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from starpulse._internal.autopilot.runtime import Runtime
from starpulse._internal.autopilot.sampler import PERIOD
from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.server.server import assemble, history_store, start_autopilot

#: How long a test waits for the loop: far under the sampler's period, which is the bound the spec names.
DEADLINE_S = 10.0
IDLE_HOST = {"cpu": 1.0, "memory": 1.0}


@contextmanager
def _start_service() -> Iterator[tuple[str, list[str]]]:
    """A session-start service on an ephemeral port that answers every start with a session URL."""
    asked: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            asked.append(self.path)
            body = json.dumps({"task": self.path.rsplit("/", 1)[-1], "url": "https://claude.ai/code/session_stub"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", asked
    finally:
        server.shutdown()
        server.server_close()


def _until(condition: Callable[[], object], what: str, deadline_s: float = DEADLINE_S) -> None:
    end = time.monotonic() + deadline_s
    while not condition():
        if time.monotonic() > end:
            pytest.fail(f"{what} did not happen within {deadline_s:g}s")
        time.sleep(0.02)


def _task(base: Path, status: str) -> None:
    """`task-1`'s file on the native board, in `status` (written whole, so a poll never reads half of it)."""
    root = base / ".starpulse" / "board"
    path = root / "tasks" / "task-1 - Title.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    (root / "config.yml").write_text('project_name: demo\nstatuses: ["To Do", "In Progress", "Done"]\ntask_prefix: task\n')
    scratch = path.with_suffix(".tmp")
    scratch.write_text(
        f"---\nid: task-1\ntitle: Title\nstatus: {status}\nlabels:\n  - size-3\n---\n\n"
        "<!-- SECTION:DESCRIPTION:BEGIN -->\nWhy\n<!-- SECTION:DESCRIPTION:END -->\n"
    )
    os.replace(scratch, path)


@contextmanager
def _served(base: Path, config_text: str = "") -> Iterator[tuple[BoardFeed, Runtime]]:
    """The native board polled every 0.1 s with the autopilot built and running over it, and its switch on."""
    path = base / "starpulse.toml"
    path.write_text(config_text + "[board]\ninterval = 0.1\n")
    config = load(path)
    board, feed = assemble(config, base, None, ())
    history = history_store(config, base, feed.machines)
    board.start(feed, "test", EventLog(f"sqlite:///{base / 'events.sqlite'}"))
    stop = threading.Event()
    runtime = start_autopilot(config, base, feed, board, history, None, stop, probe=lambda: IDLE_HOST)
    try:
        runtime.set_enabled(True)
        yield feed, runtime
    finally:
        stop.set()
        if runtime.loop is not None:
            runtime.loop.wake()  # the loop looks at `stop` between events
        for thread in threading.enumerate():
            if thread.name.startswith("autopilot-"):
                thread.join(DEADLINE_S)


def test_a_task_moved_into_the_eligible_lane_is_started_within_one_sampler_period(tmp_path: Path) -> None:
    with _start_service() as (url, asked):
        _task(tmp_path, "Done")
        with _served(tmp_path, f'session_start_url = "{url}"\n') as (feed, _):
            _until(lambda: feed.task("task-1"), "the board's read of task-1")
            assert asked == []  # a Done task is not eligible

            moved = time.monotonic()
            _task(tmp_path, "To Do")  # the eligible lane is the board's initial lane

            _until(lambda: asked, "the start")
            assert time.monotonic() - moved < PERIOD  # by the move's event: the loop's timer is the sampler period
            assert asked == ["/start/task-1"]


def test_a_board_with_no_autopilot_block_and_no_start_service_starts_the_task_in_tmux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir, record = tmp_path / "bin", tmp_path / "ran.txt"
    bin_dir.mkdir()
    for name in ("tmux", "claude"):  # the two binaries the built-in starter needs; tmux records what it was asked to run
        script = bin_dir / name
        script.write_text(f'#!/bin/sh\necho "$@" >> {record}\n' if name == "tmux" else "#!/bin/sh\n")
        script.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    _task(tmp_path, "To Do")

    with _served(tmp_path):
        _until(record.exists, "the tmux start")

    assert re.fullmatch(
        rf"new-session -d -s starpulse-task-1 -c {re.escape(str(tmp_path))} claude --remote-control task-1 Start task-1\n",
        record.read_text(),
    )
