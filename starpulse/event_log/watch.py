"""The file-watch port the event log wakes on a commit by another process, with an inotify adapter (Linux, through
ctypes) and a kqueue adapter (macOS and the BSDs), both standard library. A watch is a descriptor that turns readable
when the store's database or `-wal` file changes; whether the change was a commit is the reader's to find out."""

from __future__ import annotations

import ctypes
import os
import select
import struct
import sys
from pathlib import Path
from typing import Protocol

_IN_MODIFY, _IN_MOVED_FROM, _IN_MOVED_TO, _IN_CREATE, _IN_DELETE = 0x2, 0x40, 0x80, 0x100, 0x200
_IN_NONBLOCK, _IN_CLOEXEC = os.O_NONBLOCK, os.O_CLOEXEC
_INOTIFY_EVENTS = _IN_MODIFY | _IN_MOVED_FROM | _IN_MOVED_TO | _IN_CREATE | _IN_DELETE
_INOTIFY_HEADER = struct.Struct("iIII")
_KQUEUE_EVENTS_PER_READ = 64


class FileWatch(Protocol):
    def fileno(self) -> int:
        """A descriptor that is readable while a change to the store has not been drained."""

    def drain(self) -> bool:
        """Consume the pending changes and say whether one touched the database or its `-wal` file."""

    def close(self) -> None: ...


class _Inotify:
    """Watches the store's directory, not its files, so the `-wal` file's deletion and recreation never loses the watch;
    the events are filtered to the database and `-wal` file by name."""

    def __init__(self, fd: int, names: frozenset[bytes]) -> None:
        self._fd = fd
        self._names = names

    def fileno(self) -> int:
        return self._fd

    def drain(self) -> bool:
        touched = False
        while True:
            try:
                data = os.read(self._fd, 65536)
            except BlockingIOError:
                return touched
            offset = 0
            while offset < len(data):
                _, _, _, length = _INOTIFY_HEADER.unpack_from(data, offset)
                start = offset + _INOTIFY_HEADER.size
                touched = touched or data[start : start + length].rstrip(b"\0") in self._names
                offset = start + length

    def close(self) -> None:
        os.close(self._fd)


def _inotify(database: str) -> FileWatch | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        fd = libc.inotify_init1(_IN_NONBLOCK | _IN_CLOEXEC)
        if fd < 0:
            return None
        path = Path(database).absolute()
        if libc.inotify_add_watch(fd, os.fsencode(path.parent), _INOTIFY_EVENTS) < 0:
            os.close(fd)
            return None
    except (OSError, AttributeError):
        return None
    return _Inotify(fd, frozenset({os.fsencode(path.name), os.fsencode(path.name + "-wal")}))


class _Kqueue:
    """Watches the database, its `-wal` file and their directory; a directory write means a file came or went, so the
    files are opened again."""

    def __init__(self, database: str) -> None:
        path = Path(database).absolute()
        self._paths = (path.parent, path, path.with_name(path.name + "-wal"))
        self._queue = select.kqueue()
        self._open: dict[Path, int] = {}
        self._notes = select.KQ_NOTE_WRITE | select.KQ_NOTE_EXTEND | select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME
        self._sync()

    def _sync(self) -> None:
        for path in self._paths:
            if path in self._open:
                continue
            try:
                fd = os.open(path, os.O_RDONLY)
            except OSError:
                continue  # not created yet: the directory's write event brings it back here
            self._open[path] = fd
            add = select.kevent(fd, select.KQ_FILTER_VNODE, select.KQ_EV_ADD | select.KQ_EV_CLEAR, self._notes)
            self._queue.control([add], 0)

    def fileno(self) -> int:
        return self._queue.fileno()

    def drain(self) -> bool:
        changes = self._queue.control(None, _KQUEUE_EVENTS_PER_READ, 0)
        gone = {change.ident for change in changes if change.fflags & (select.KQ_NOTE_DELETE | select.KQ_NOTE_RENAME)}
        for path, fd in list(self._open.items()):
            if fd in gone:
                os.close(fd)
                del self._open[path]
        self._sync()
        return bool(changes)

    def close(self) -> None:
        for fd in self._open.values():
            os.close(fd)
        self._queue.close()


def _kqueue(database: str) -> FileWatch | None:
    if not hasattr(select, "kqueue"):
        return None
    try:
        return _Kqueue(database)
    except OSError:
        return None


def open_watch(database: str) -> FileWatch | None:
    """A watch on the SQLite file `database`, or None on a platform with neither inotify nor kqueue."""
    return _inotify(database) or _kqueue(database)
