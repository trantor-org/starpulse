"""The disk the server's own store, archive and Board hold, as a Prometheus metric."""

import os
import stat
import threading
import time
from collections.abc import Callable
from pathlib import Path

#: A walk of the Board is thousands of stats; a scrape inside this span reads the last one.
CACHE_S = 60.0


def _size(path: Path, follow_symlinks: bool) -> int:
    """The bytes of a regular file, 0 for anything else or a file gone or unreadable since it was listed."""
    try:
        info = path.stat(follow_symlinks=follow_symlinks)
    except OSError:
        return 0
    return info.st_size if stat.S_ISREG(info.st_mode) else 0


def _tree_bytes(root: Path) -> int:
    return sum(_size(Path(base, name), False) for base, _, names in os.walk(root) for name in names)


def storage_exposition(*, database: Path | None, archive: Path, board: Path) -> str:
    """`starpulse_storage_bytes` per store: the database file with its WAL and shared memory, the archive and the Board."""
    files = (Path(f"{database}{suffix}") for suffix in ("", "-wal", "-shm")) if database else ()
    sizes = {
        "database": sum(_size(path, True) for path in files),
        "archive": _tree_bytes(archive),
        "board": _tree_bytes(board),
    }
    return "\n".join(
        [
            "# HELP starpulse_storage_bytes Bytes on disk under the server's own database, event archive and Board.",
            "# TYPE starpulse_storage_bytes gauge",
            *(f'starpulse_storage_bytes{{store="{store}"}} {size}' for store, size in sizes.items()),
            "",
        ]
    )


def cached(read: Callable[[], str]) -> Callable[[], str]:
    """`read`, asked at most once in `CACHE_S` seconds; callers arriving during a read wait for it."""
    held: tuple[float, str] | None = None
    lock = threading.Lock()

    def get() -> str:
        nonlocal held
        with lock:
            if held is None or time.monotonic() - held[0] >= CACHE_S:
                held = (time.monotonic(), read())
            return held[1]

    return get
