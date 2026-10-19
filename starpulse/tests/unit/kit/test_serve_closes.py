"""`serve` leaves nothing open behind it: no listening socket, no settings database, no request worker.

The count runs in a fresh interpreter: fds and threads are process-wide, so
sockets other tests left in a shared xdist worker would move the baseline.
"""

import os
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from starpulse._internal.kit.adapter_kit import serve, url


def _fds() -> int:
    return len(os.listdir("/proc/self/fd"))


def _check_twenty_serves(root: Path) -> None:
    def once(n: int) -> None:
        with serve(root / str(n)) as server:
            urllib.request.urlopen(url(server, "/api/history-window")).close()

    for n in range(20):
        (root / str(n)).mkdir()
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


# waits out a 5 s settle, so a loaded host takes it past the gate's bound
@pytest.mark.slow
def test_twenty_serves_leave_the_fd_and_thread_count_where_they_started(tmp_path: Path) -> None:
    run = subprocess.run([sys.executable, __file__, str(tmp_path)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stderr


if __name__ == "__main__":
    _check_twenty_serves(Path(sys.argv[1]))
