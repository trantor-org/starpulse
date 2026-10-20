"""The page build the server refuses to start without, stubbed for as long as any test or worker needs it.

Tests in one checkout share its `static` directory. A stub one holder removes while another's server still reads it
breaks that server, so a holder registers a marker named for its process, and the last one out removes the stub.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_USERS = ".stub-users"


@contextmanager
def _locked(static: Path) -> Iterator[None]:
    name = f"starpulse-page-stub-{hashlib.sha1(str(static).encode()).hexdigest()[:16]}.lock"
    with open(Path(tempfile.gettempdir()) / name, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def _alive(marker: Path) -> bool:
    try:
        os.kill(int(marker.name.split("-")[0]), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _prune(users: Path) -> list[Path]:
    """The markers of holders still running; a holder that died without leaving loses its marker."""
    alive = []
    for marker in users.iterdir() if users.is_dir() else ():
        if _alive(marker):
            alive.append(marker)
        else:
            marker.unlink(missing_ok=True)
    return alive


@contextmanager
def held(static: Path) -> Iterator[None]:
    """Stub `static/index.html` for the block unless the checkout has a real build; remove it with the last holder."""
    users = static / _USERS
    with _locked(static):
        real = (static / "index.html").is_file() and not users.is_dir()
        if not real:
            _prune(users)
            users.mkdir(parents=True, exist_ok=True)
            marker = users / f"{os.getpid()}-{uuid.uuid4().hex}"
            marker.touch()
            if not (static / "index.html").is_file():
                (static / "index.html").write_text("<!doctype html>")
    try:
        yield
    finally:
        if not real:
            with _locked(static):
                marker.unlink(missing_ok=True)
                if not _prune(users):
                    shutil.rmtree(static, ignore_errors=True)
