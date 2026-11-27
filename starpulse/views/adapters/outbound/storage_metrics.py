"""The disk the server's own store, archive and Board hold, as a Prometheus metric."""

import os
import stat
import threading
import time
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine

from starpulse.board.adapters import native_docs
from starpulse.board.adapters.native_doc_index import DocIndex

#: A walk of the Board is thousands of stats; a scrape past this span reads the last one while the next walk runs.
CACHE_S = 60.0


#: The span of a gauge that is read from the log: under the 15 s scrape interval, so a scrape reads the last scrape's text.
SCRAPE_CACHE_S = 10.0


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


def cached(read: Callable[[], str], span: float = CACHE_S) -> Callable[[], str]:
    """`read`, asked at most once in `span` seconds (`CACHE_S` by default). The first caller waits for the first read,
    and so do callers arriving during it; a later one past the span gets the last text at once while one thread reads
    the next."""
    held: tuple[float, str] | None = None
    lock = threading.Lock()
    refreshing = False

    def refresh() -> None:
        nonlocal held, refreshing
        try:
            text = read()
            with lock:
                held = (time.monotonic(), text)  # stamped when the read ends
        finally:
            with lock:
                refreshing = False

    def get() -> str:
        nonlocal held, refreshing
        with lock:
            if held is None:
                text = read()
                held = (time.monotonic(), text)  # stamped when the read ends
            elif time.monotonic() - held[0] >= span and not refreshing:
                refreshing = True
                threading.Thread(target=refresh, name="storage-metrics", daemon=True).start()
            return held[1]

    return get


def docs_exposition(board: Path, engine: Engine) -> str:
    """`starpulse_docs` per doc type: the open docs on the Board."""
    return "\n".join(
        [
            "# HELP starpulse_docs Open docs on the Board by type.",
            "# TYPE starpulse_docs gauge",
            *(f'starpulse_docs{{type="{kind}"}} {count}' for kind, count in sorted(native_docs.counts(DocIndex(board, engine)).items())),
            "",
        ]
    )
