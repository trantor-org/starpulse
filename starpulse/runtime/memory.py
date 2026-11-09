"""The memory a worker is judged on, per OS, read through psutil.

Workers forked from one preloaded process share the pages of what it imported, so a limit on the resident size would charge
every child for the whole shared floor. Linux reads the proportional set size, which divides each shared page among the
processes that map it; macOS starts its children with `subprocess`, so its resident size is the child's own.
"""

from __future__ import annotations

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
