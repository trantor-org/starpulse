"""The page build the server refuses to start without, stubbed for as long as any test or worker needs it.

Tests in one checkout share its `static` directory. A stub one holder removes while another's server still reads it
breaks that server, so a holder registers a marker named for its process, and the last one out removes the stub.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_USERS = ".stub-users"
_STUB = "<!doctype html>"


@contextmanager
def _locked(static: Path) -> Iterator[None]:
    """Serialize holders on the checkout itself, so shards that do not share a `/tmp` still queue."""
    fd = os.open(static.parent, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _alive(marker: Path) -> bool:
    """A holder keeps an exclusive lock on its marker, which a process in another PID namespace can still see."""
    try:
        with open(marker) as handle:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except FileNotFoundError:
        return False
    return False


def _prune(users: Path) -> list[Path]:
    """The markers of holders still running; a holder that died without leaving loses its marker."""
    alive = []
    for marker in users.iterdir() if users.is_dir() else ():
        if _alive(marker):
            alive.append(marker)
        else:
            marker.unlink(missing_ok=True)
    return alive


def _clear(static: Path, users: Path) -> None:
    """Remove the stub; a build that replaced it while held (a release build in the same clone) stays."""
    index = static / "index.html"
    if index.is_file() and index.read_text() != _STUB:
        shutil.rmtree(users, ignore_errors=True)
    else:
        shutil.rmtree(static, ignore_errors=True)


@contextmanager
def held(static: Path) -> Iterator[None]:
    """Stub `static/index.html` for the block unless the checkout has a real build; remove it with the last holder."""
    users = static / _USERS
    marker = users / uuid.uuid4().hex
    with _locked(static):
        real = (static / "index.html").is_file() and not users.is_dir()
        if not real:
            _prune(users)
            users.mkdir(parents=True, exist_ok=True)
            handle = open(marker, "w")
            fcntl.flock(handle, fcntl.LOCK_EX)
            if not (static / "index.html").is_file():
                (static / "index.html").write_text(_STUB)
    try:
        yield
    finally:
        if not real:
            with _locked(static):
                marker.unlink(missing_ok=True)
                handle.close()
                if not _prune(users):
                    _clear(static, users)
