"""A crowd of event streams must not keep stepping RSS after its request threads exit.

The live server is CPython 3.14t. ThreadingHTTPServer starts an 8 MiB-stack thread per request; a 50-viewer
starpulse-load run dirties those stacks, then the threads exit, FDs and `process_threads` return, and RSS does not
(object counts fall). Request threads take a 256 KiB stack instead. The first crowd may step RSS (abandoned
free-threaded heaps); a second crowd against the same process must hold near that step.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import threading
import time
import urllib.request
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse._internal.server.server import REQUEST_STACK
from starpulse.tests.machines import MACHINES

VIEWERS = 40
#: KiB the first event-stream crowd may keep after its threads have exited.
_FIRST_SLACK_KB = 32_768
#: KiB a second crowd may add on top of the first step.
_HOLD_SLACK_KB = 8_192


def _rss_kb(pid: int | None = None) -> int:
    path = Path("/proc/self/status" if pid is None else f"/proc/{pid}/status")
    for line in path.read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise RuntimeError("no VmRSS")


def _threads(pid: int) -> int:
    for line in Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("Threads:"):
            return int(line.split()[1])
    raise RuntimeError("no Threads")


def _feed() -> BoardFeed:
    feed = BoardFeed(machines=MACHINES)
    for n in range(400):
        feed.put(task(f"PROJ-{n}", title=f"{'a long title ' * 20}{n}"))
    return feed


def _serve_crowd(directory: str, conn: Connection) -> None:
    import starpulse._internal.server.server as server_mod

    server_mod._PING_S = 0.05
    with serve(Path(directory), _feed()) as server:
        conn.send((server.server_port, os.getpid()))
        conn.recv()


def _wait_idle(pid: int, idle: int) -> None:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and _threads(pid) > idle + 2:
        time.sleep(0.05)


def _stream_crowd(port: int, pid: int, idle: int) -> int:
    events = f"http://127.0.0.1:{port}/api/events?snapshot=ref"
    for _ in range(VIEWERS):
        with urllib.request.urlopen(events, timeout=30) as resp:
            resp.readline()
    _wait_idle(pid, idle)
    return _rss_kb(pid)


def test_a_request_thread_is_started_at_the_request_stack_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[int] = []
    real = threading.Thread

    def wrapped(*args: object, **kwargs: object) -> threading.Thread:
        seen.append(threading.stack_size())
        return real(*args, **kwargs)

    monkeypatch.setattr(threading, "Thread", wrapped)
    with serve(tmp_path, BoardFeed()) as server:
        urllib.request.urlopen(url(server, "/api/snapshot"), timeout=5).read()

    assert REQUEST_STACK in seen


@pytest.mark.skipif(sys._is_gil_enabled(), reason="the live server is 3.14t; GIL heaps return after a crowd")
@pytest.mark.xdist_group("crowd-rss")
def test_a_second_event_stream_crowd_holds_rss_near_the_first(tmp_path: Path) -> None:
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_serve_crowd, args=(str(tmp_path), child), daemon=True)
    proc.start()
    try:
        assert parent.poll(30), "the crowd server did not start"
        port, pid = parent.recv()
        time.sleep(0.2)
        idle = _threads(pid)
        warm = _rss_kb(pid)
        first = _stream_crowd(port, pid, idle) - warm
        held = _stream_crowd(port, pid, idle) - warm - first
    finally:
        parent.send(None)
        proc.join(timeout=10)

    assert first < _FIRST_SLACK_KB, f"first crowd kept {first} kB RSS after its threads exited (warm {warm} kB)"
    assert held < _HOLD_SLACK_KB, f"second crowd added {held} kB RSS on top of the first step of {first} kB"
