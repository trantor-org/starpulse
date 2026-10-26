"""A crowd of gzip snapshot reads must reuse request threads so RSS does not step once per request.

The live server is CPython 3.14t. A thread per request, each exiting after it, leaves RSS stepped (a 5 min
starpulse-load run created thousands of them; FDs and `process_threads` returned, RSS did not). The page app runs its
blocking work on a bounded pool of reused worker threads; the first crowd may step RSS, a second crowd must reuse
those workers and hold near that step.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.connection import Connection
from pathlib import Path

import pytest
from starpulse.board.board_feed import BoardFeed
from starpulse.runtime.adapter_kit import serve, task

from tests.machines import MACHINES, ROLES

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
    feed = BoardFeed(roles=ROLES, machines=MACHINES)
    feed.put(task("PROJ-0", title="crowd", description=os.urandom(400_000).hex()))
    return feed


def _serve_crowd(directory: str, conn: Connection) -> None:
    import starpulse.views.streams as streams_mod

    streams_mod._PING_S = 0.05
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


@pytest.mark.skipif(sys._is_gil_enabled(), reason="the live server is 3.14t; GIL heaps return after a crowd")
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

    assert workers > idle, f"request pool did not grow under the crowd (idle {idle}, now {workers})"
    assert first < _FIRST_SLACK_KB, f"first crowd kept {first} kB RSS (warm {warm} kB)"
    assert held < _HOLD_SLACK_KB, f"second crowd added {held} kB RSS on top of the first step of {first} kB"
