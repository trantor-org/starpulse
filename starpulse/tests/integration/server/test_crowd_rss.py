"""A crowd of gzip snapshot reads must reuse request threads so RSS does not step once per request.

The live server is CPython 3.14t. ThreadingHTTPServer starts a new 8 MiB-stack thread per request; a 5 min
starpulse-load run creates thousands of them, they exit, FDs and `process_threads` return, and RSS does not (object
counts fall). Request threads are pooled at 256 KiB; the first crowd may step RSS, a second crowd must reuse those
workers and hold near that step.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.kit.adapter_kit import serve, task, url
from starpulse._internal.server.server import REQUEST_STACK
from starpulse.tests.machines import MACHINES

VIEWERS = 40
FETCHES = 4
#: KiB the first gzip-snapshot crowd may keep in its pooled workers (40 threads writing ~800 KB gzip).
_FIRST_SLACK_KB = 131_072
#: KiB a second crowd may add on top of the first step (mimalloc noise on reused workers).
_HOLD_SLACK_KB = 16_384


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
    feed.put(task("PROJ-0", title="crowd", description=os.urandom(400_000).hex()))
    return feed


def _serve_crowd(directory: str, conn: Connection) -> None:
    import starpulse._internal.server.server as server_mod

    server_mod._PING_S = 0.05
    with serve(Path(directory), _feed()) as server:
        conn.send((server.server_port, os.getpid()))
        conn.recv()


def _snapshot_crowd(port: int) -> None:
    snapshot = f"http://127.0.0.1:{port}/api/snapshot"
    headers = {"Accept-Encoding": "gzip"}

    def read() -> None:
        for _ in range(FETCHES):
            urllib.request.urlopen(urllib.request.Request(snapshot, headers=headers), timeout=30).read()

    with ThreadPoolExecutor(max_workers=VIEWERS) as pool:
        list(pool.map(lambda _: read(), range(VIEWERS)))


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
def test_a_second_gzip_snapshot_crowd_reuses_request_threads_and_holds_rss(tmp_path: Path) -> None:
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe()
    proc = ctx.Process(target=_serve_crowd, args=(str(tmp_path), child), daemon=True)
    proc.start()
    try:
        assert parent.poll(30), "the crowd server did not start"
        port, pid = parent.recv()
        urllib.request.urlopen(
            urllib.request.Request(f"http://127.0.0.1:{port}/api/snapshot", headers={"Accept-Encoding": "gzip"}),
            timeout=30,
        ).read()
        time.sleep(0.2)
        idle = _threads(pid)
        warm = _rss_kb(pid)
        _snapshot_crowd(port)
        time.sleep(0.3)
        workers = _threads(pid)
        first = _rss_kb(pid) - warm
        _snapshot_crowd(port)
        time.sleep(0.3)
        held = _rss_kb(pid) - warm - first
    finally:
        parent.send(None)
        proc.join(timeout=10)

    assert workers >= idle + VIEWERS // 2, f"request workers exited after the crowd (idle {idle}, now {workers})"
    assert first < _FIRST_SLACK_KB, f"first crowd kept {first} kB RSS (warm {warm} kB)"
    assert held < _HOLD_SLACK_KB, f"second crowd added {held} kB RSS on top of the first step of {first} kB"
