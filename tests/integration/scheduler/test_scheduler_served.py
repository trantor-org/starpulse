"""The scheduler served against a native board: a task entering the eligible lane starts a session within a sampler
period by an event alone, and a board with no `[scheduler]` block and no `session_start_url` starts it in tmux."""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import traceback
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.event_log.event_log import EventLog
from starpulse.runtime import server
from starpulse.runtime.assembly import assemble, history_store
from starpulse.runtime.config import load
from starpulse.scheduler.adapters.runtime import Runtime
from starpulse.scheduler.bin.scheduler_service import start_scheduler
from starpulse.scheduler.model.ledger import LEDGER_FILE, Ledger
from starpulse.scheduler.model.sampler import PERIOD
from starpulse.sessions.session_start import starter

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
            body = json.dumps(
                {"task": self.path.rsplit("/", 1)[-1], "url": "https://claude.ai/code/session_stub"}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", asked
    finally:
        server.shutdown()
        server.server_close()


def _loop_state(feed: BoardFeed, runtime: Runtime) -> str:
    """What a start miss needs to name its cause: the switch, the tasks the loop can see, whether it runs, its status,
    the feed's read of task-1 (still `done` is a move the board's poll never placed) and where that poll thread is."""
    loop = runtime.loop
    alive = loop is not None and any(t.name == "scheduler-loop" and t.is_alive() for t in threading.enumerate())
    agent = feed.task("task-1") or {}
    read = {key: agent.get(key) for key in ("state", "workable", "workable_since")}
    frames = sys._current_frames()
    polls = [t for t in threading.enumerate() if t.name == "upstream-backlog"]
    at = [traceback.format_stack(frames[t.ident])[-3:] if t.ident in frames else "exited" for t in polls]
    return (
        f"toggle={runtime.toggle.get()} open_tasks={[t.get('id') for t in feed.open_tasks()]} "
        f"loop_thread_alive={alive} status={runtime.status()} task-1={read} poll_threads={at}"
    )


def _until(
    condition: Callable[[], object],
    what: str,
    deadline_s: float = DEADLINE_S,
    state: Callable[[], str] | None = None,
) -> None:
    end = time.monotonic() + deadline_s
    while not condition():
        if time.monotonic() > end:
            detail = f"; {state()}" if state is not None else ""
            pytest.fail(f"{what} did not happen within {deadline_s:g}s{detail}")
        time.sleep(0.02)


def _task(base: Path, status: str) -> None:
    """`task-1`'s file on the native board, in `status` and on a profile (written whole, so a poll never reads half of it)."""
    root = base / ".starpulse" / "board"
    path = root / "tasks" / "task-1 - Title.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    (root / "config.yml").write_text(
        'project_name: demo\nstatuses: ["To Do", "In Progress", "Done"]\ntask_prefix: task\n'
    )
    scratch = path.with_suffix(".tmp")
    scratch.write_text(
        f"---\nid: task-1\ntitle: Title\nstatus: {status}\nprofile: '@agent-standard-high'\nlabels:\n  - size-3\n---\n\n"
        "<!-- SECTION:DESCRIPTION:BEGIN -->\nWhy\n<!-- SECTION:DESCRIPTION:END -->\n"
    )
    os.replace(scratch, path)


@contextmanager
def _served(base: Path, config_text: str = "") -> Iterator[tuple[BoardFeed, Runtime]]:
    """The native board polled every 0.1 s with the scheduler built and running over it, and its switch on."""
    path = base / "starpulse.toml"
    path.write_text(config_text + "[board]\ninterval = 0.1\n")
    config = load(path)
    board, feed = assemble(config, base, None, ())
    history = history_store(config, base, feed.machines)
    log = EventLog(f"sqlite:///{base / 'events.sqlite'}")
    board.start(feed, "test", log)
    stop = threading.Event()
    before = set(threading.enumerate())
    runtime = start_scheduler(
        config,
        base,
        feed,
        board,
        history,
        log,
        None,
        stop,
        probe=lambda: IDLE_HOST,
        trajectories_response=server.trajectories_response,
        cached=server._cached,
        starter=starter,
    )
    started = [t for t in threading.enumerate() if t not in before and t.name.startswith("scheduler-")]
    try:
        runtime.set_enabled(True)
        yield feed, runtime
    finally:
        stop.set()
        if runtime.loop is not None:
            runtime.loop.wake()  # the loop looks at `stop` between events
        for thread in started:  # only its own: other tests' threads in this worker are not its to wait for
            thread.join(DEADLINE_S)


def test_a_task_moved_into_the_eligible_lane_is_started_within_one_sampler_period(tmp_path: Path) -> None:
    with _start_service() as (url, asked):
        _task(tmp_path, "Done")
        with _served(tmp_path, f'session_start_url = "{url}"\n') as (feed, runtime):
            _until(lambda: feed.task("task-1"), "the board's read of task-1")
            assert asked == []  # a Done task is not eligible

            moved = time.monotonic()
            _task(tmp_path, "To Do")  # the eligible lane is the board's initial lane

            _until(lambda: asked, "the start", state=lambda: _loop_state(feed, runtime))
            assert time.monotonic() - moved < PERIOD  # by the move's event: the loop's timer is the sampler period
            assert asked == ["/start/task-1?harness=claude&mode=interactive&by=scheduler"]


def test_a_start_miss_fails_with_the_loops_state(tmp_path: Path) -> None:
    _task(tmp_path, "Done")
    with _served(tmp_path) as (feed, runtime):
        _until(lambda: feed.task("task-1"), "the board's read of task-1")
        with pytest.raises(pytest.fail.Exception) as miss:
            _until(lambda: False, "the start", deadline_s=0.05, state=lambda: _loop_state(feed, runtime))

    assert re.search(r"toggle=True open_tasks=\[.*\] loop_thread_alive=True status=\{", str(miss.value))
    assert re.search(r"task-1=\{'state': 'done', .*\} poll_threads=\[\[' +File ", str(miss.value))


def test_a_board_with_no_scheduler_block_and_no_start_service_starts_the_task_in_tmux(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir, record = tmp_path / "bin", tmp_path / "ran.txt"
    bin_dir.mkdir()
    for name in (
        "tmux",
        "claude",
    ):  # the two binaries the built-in starter needs; tmux records what it was asked to run
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


def test_the_switch_and_the_run_ledger_are_kept_in_the_store_not_in_files_beside_the_config(tmp_path: Path) -> None:
    state = tmp_path / "starpulse-state"  # not created beforehand: the server makes it
    with _start_service() as (url, asked):
        _task(tmp_path, "Done")
        config = f'session_start_url = "{url}"\n[scheduler]\nstate_dir = "starpulse-state"\n'
        with _served(tmp_path, config) as (feed, runtime):
            _until(lambda: feed.task("task-1"), "the board's read of task-1")
            _task(tmp_path, "To Do")
            _until(lambda: asked, "the start", state=lambda: _loop_state(feed, runtime))
            # The start's claim comment rewrites the task file; a move written before it lands is overwritten.
            task_file = tmp_path / ".starpulse" / "board" / "tasks" / "task-1 - Title.md"
            _until(lambda: "Scheduler started task-1" in task_file.read_text(), "the start's claim comment")
            _task(tmp_path, "Done")  # the run's task leaves the lane: its run is recorded
            store = EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}")
            ledger = Ledger(store, state / LEDGER_FILE)
            _until(lambda: ledger.runs("task-1"), "the run's row in the store")

    assert EventLog(f"sqlite:///{tmp_path / 'events.sqlite'}").setting("scheduler.enabled") is True
    assert not (state / LEDGER_FILE).exists()  # the ledger is a table in the store, not a file
    assert not (state / "starpulse-scheduler.json").exists()  # the switch is a row in the store, not a file
    assert sorted(path.name for path in tmp_path.glob("starpulse-scheduler*")) == []  # nothing beside the config
