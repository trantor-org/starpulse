"""The resident size of a process, per OS, with the standard library only."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable


def _rss_proc(pid: int) -> int:
    """Resident bytes of `pid` from Linux `/proc/<pid>/statm`."""
    with open(f"/proc/{pid}/statm") as statm:
        return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def _rss_ps(pid: int) -> int:
    """Resident bytes of `pid` from `ps`, which macOS and the BSDs provide."""
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=True)
    return int(out.stdout.split()[0]) * 1024


def rss_reader() -> Callable[[int], int] | None:
    """The resident-size reader (pid to bytes) for this platform, or None where there is none (Windows)."""
    if sys.platform.startswith("linux"):
        return _rss_proc
    if sys.platform == "darwin":
        return _rss_ps
    return None
