"""A poll of a few folders, which says which Markdown files in them changed.

Each tick lists the folders and compares every `.md` file's modification time and size with the last listing, so it
needs no operating-system file-event API and runs the same everywhere. A folder that does not exist yet counts as empty.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterable
from pathlib import Path

#: Seconds between listings while `wait` has nothing to report.
_TICK = 0.25


class DirWatch:
    """Watches `folders` for Markdown files that land, change or go."""

    def __init__(self, folders: Iterable[Path]) -> None:
        self._folders = list(folders)
        self._woken = threading.Event()
        self._seen = self._listing()

    def _listing(self) -> dict[Path, tuple[int, int]]:
        found: dict[Path, tuple[int, int]] = {}
        for folder in self._folders:
            try:
                entries = list(os.scandir(folder))
            except OSError:  # not there yet, or gone
                continue
            for entry in entries:
                if entry.name.endswith(".md"):
                    try:
                        stat = entry.stat()
                    except OSError:  # renamed or deleted since the listing
                        continue
                    found[folder / entry.name] = (stat.st_mtime_ns, stat.st_size)
        return found

    def wait(self, timeout: float) -> set[Path] | None:
        """The Markdown files that landed, changed or went since the last call, once any have, or None after `timeout`
        seconds. A `wake()` ends the wait early with no files."""
        deadline = time.monotonic() + timeout
        while True:
            if self._woken.wait(max(0.0, min(_TICK, deadline - time.monotonic()))):
                return set()
            listing = self._listing()
            changed = {path for path in listing.keys() | self._seen.keys() if listing.get(path) != self._seen.get(path)}
            if changed:
                self._seen = listing
                return changed
            if time.monotonic() >= deadline:
                return None

    def wake(self) -> None:
        """End the current and every later `wait` at once, so a stopped caller need not wait out its timeout."""
        self._woken.set()
