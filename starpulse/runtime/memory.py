"""The memory a worker is judged on, per OS, read through psutil.

Linux reads the proportional set size, which divides each page processes share among the processes that map it; macOS
reads the child's own resident size.
"""

import sys
from collections.abc import Callable

import psutil


def _pss(pid: int) -> int:
    """Proportional bytes of `pid`; psutil falls back to `smaps` on a kernel without the rollup."""
    return psutil.Process(pid).memory_full_info().pss


def _rss(pid: int) -> int:
    """Resident bytes of `pid`."""
    return psutil.Process(pid).memory_info().rss


def memory_reader() -> Callable[[int], int] | None:
    """The memory reader (pid to bytes) for this platform, or None where there is none (Windows)."""
    if sys.platform.startswith("linux"):
        return _pss
    if sys.platform == "darwin":
        return _rss
    return None
