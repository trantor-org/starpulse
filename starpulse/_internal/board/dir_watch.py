"""An inotify watch on a few folders, which says which Markdown files in them changed.

The standard library has no inotify binding, so this calls libc's through `ctypes`. It is Linux only: `DirWatch`
raises `OSError` where inotify is missing or out of watches, and the caller falls back to polling.
"""

from __future__ import annotations

import ctypes
import os
import select
import struct
from collections.abc import Iterable
from pathlib import Path

_IN_CLOSE_WRITE, _IN_MOVED_FROM, _IN_MOVED_TO, _IN_CREATE, _IN_DELETE = 0x8, 0x40, 0x80, 0x100, 0x200
_IN_Q_OVERFLOW, _IN_ISDIR = 0x4000, 0x40000000
#: A file is final once its writer closes it or renames it in, and gone once it is renamed away or deleted.
_MASK = _IN_CLOSE_WRITE | _IN_MOVED_FROM | _IN_MOVED_TO | _IN_DELETE
#: A folder that does not exist yet is waited for in its nearest ancestor, where only a new folder matters.
_ANCESTOR_MASK = _IN_CREATE | _IN_MOVED_TO
_FLAGS = os.O_NONBLOCK | os.O_CLOEXEC
_HEADER = struct.Struct("iIII")  # the watch, what happened, a rename's cookie, the length of the padded name


class DirWatch:
    """Watches `folders` for Markdown files that land, change or go; a folder that does not exist yet is watched for in
    its nearest ancestor that does, and watched itself once it appears."""

    def __init__(self, folders: Iterable[Path]) -> None:
        self._libc = ctypes.CDLL(None, use_errno=True)
        self._fd = self._libc.inotify_init1(_FLAGS)
        if self._fd < 0:
            raise OSError(ctypes.get_errno(), "inotify_init1 failed")
        self._wake_read, self._wake_write = os.pipe()
        self._folders = list(folders)
        self._watched: dict[int, Path] = {}
        self._ancestors: dict[int, Path] = {}
        self.refresh()

    def refresh(self) -> None:
        """Watch each folder that exists now and was not watched yet, and the ancestor of each that does not exist."""
        for folder in self._folders:
            if folder.is_dir():
                if folder not in self._watched.values():
                    self._watched[self._add(folder, _MASK)] = folder
            else:
                ancestor = next(parent for parent in folder.parents if parent.is_dir())
                if ancestor not in self._ancestors.values():
                    self._ancestors[self._add(ancestor, _ANCESTOR_MASK)] = ancestor

    def _add(self, folder: Path, mask: int) -> int:
        watch = self._libc.inotify_add_watch(self._fd, os.fsencode(folder), mask)
        if watch < 0:
            raise OSError(ctypes.get_errno(), f"inotify_add_watch failed for {folder}")
        return watch

    def wait(self, timeout: float) -> set[Path] | None:
        """The Markdown files that changed since the last call (none, when only other files did), once anything has, or
        None after `timeout` seconds or after events were lost. A `wake()` ends the wait early with no files.

        None means "rescan everything": a missed event leaves no trace, so only the caller's full scan covers it, and so
        does a new folder, whose files may have landed before it was watched.
        """
        poller = select.poll()
        poller.register(self._fd, select.POLLIN)
        poller.register(self._wake_read, select.POLLIN)
        ready = {fd for fd, _ in poller.poll(timeout * 1000)}
        if not ready:
            return None
        if self._wake_read in ready:
            return set()
        changed: set[Path] = set()
        while True:
            try:
                data = os.read(self._fd, 65536)
            except BlockingIOError:
                return changed
            offset = 0
            while offset < len(data):
                watch, mask, _, length = _HEADER.unpack_from(data, offset)
                name = (
                    data[offset + _HEADER.size : offset + _HEADER.size + length].rstrip(b"\0").decode(errors="replace")
                )
                offset += _HEADER.size + length
                if mask & _IN_Q_OVERFLOW:
                    return None
                if watch in self._ancestors:
                    if mask & _IN_ISDIR:
                        self.refresh()
                        return None
                    continue
                if watch in self._watched and name.endswith(".md"):
                    changed.add(self._watched[watch] / name)

    def wake(self) -> None:
        """End the current and every later `wait` at once, so a stopped caller need not wait out its timeout."""
        os.write(self._wake_write, b"\0")

    def close(self) -> None:
        for fd in (self._fd, self._wake_read, self._wake_write):
            os.close(fd)
