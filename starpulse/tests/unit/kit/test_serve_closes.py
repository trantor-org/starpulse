"""`serve` leaves nothing open behind it: no listening socket, no settings database, no request worker."""

import gc
import os
import threading
import time
import urllib.request
from pathlib import Path

from starpulse._internal.kit.adapter_kit import serve, url


def _fds() -> int:
    gc.collect()  # unclosed sockets from earlier tests in this worker die lazily
    return len(os.listdir("/proc/self/fd"))


def test_twenty_serves_leave_the_fd_and_thread_count_where_they_started(tmp_path: Path) -> None:
    def once(n: int) -> None:
        with serve(tmp_path / str(n)) as server:
            urllib.request.urlopen(url(server, "/api/history-window")).close()

    for n in range(20):
        (tmp_path / str(n)).mkdir()
    once(0)  # warm one-time imports and pools
    time.sleep(0.2)
    fds, threads = _fds(), threading.active_count()
    for n in range(1, 20):
        once(n)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (_fds() > fds or threading.active_count() > threads):
        time.sleep(0.05)
    assert _fds() <= fds
    assert threading.active_count() <= threads
