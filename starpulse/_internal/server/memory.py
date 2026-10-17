"""The memory a worker is judged on, per OS, with the standard library only.

Workers forked from one preloaded process share the pages of what it imported, so a limit on the resident size would charge
every child for the whole shared floor. Linux reads the proportional set size, which divides each shared page among the
processes that map it; macOS starts its children with `subprocess`, so its resident size is the child's own.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable


def _pss_proc(pid: int) -> int:
    """Proportional bytes of `pid` from Linux `/proc/<pid>/smaps_rollup`, else its resident size from `statm`."""
    try:
        with open(f"/proc/{pid}/smaps_rollup") as rollup:
            for line in rollup:
                if line.startswith("Pss:"):
                    return int(line.split()[1]) * 1024
    except OSError:  # a kernel without the rollup; `statm` raises in turn for a process that is gone
        pass
    with open(f"/proc/{pid}/statm") as statm:
        return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def _rss_ps(pid: int) -> int:
    """Resident bytes of `pid` from `ps`, which macOS and the BSDs provide."""
    out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=True)
    return int(out.stdout.split()[0]) * 1024


def memory_reader() -> Callable[[int], int] | None:
    """The memory reader (pid to bytes) for this platform, or None where there is none (Windows)."""
    if sys.platform.startswith("linux"):
        return _pss_proc
    if sys.platform == "darwin":
        return _rss_ps
    return None
