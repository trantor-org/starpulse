"""One Postgres server for a whole pytest-xdist run, and a database in it for each worker.

The controller starts the container and publishes its URL in a directory every worker is told about; a worker waits for
the URL and creates a database of its own, so the tables one worker drops are not another's.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, URL, create_engine, text

_URL = "url"
_ERROR = "error"


def _publish(root: Path, name: str, content: str) -> None:
    pending = root / f".{name}.{os.getpid()}"
    pending.write_text(content)
    pending.replace(root / name)  # a worker never reads half a file


def publish_url(root: Path, url: str) -> None:
    _publish(root, _URL, url)


def publish_error(root: Path, reason: str) -> None:
    _publish(root, _ERROR, reason)


def wait_for_url(root: Path, timeout: float) -> str:
    """The controller's Postgres URL; raises when its start failed or did not finish in `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while True:
        if (root / _ERROR).is_file():
            raise RuntimeError(f"the shared Postgres did not start: {(root / _ERROR).read_text()}")
        if (root / _URL).is_file():
            return (root / _URL).read_text()
        if time.monotonic() > deadline:
            raise TimeoutError(f"the shared Postgres published no URL in {timeout} s")
        time.sleep(0.1)


@contextmanager
def worker_database(server: URL, worker: str) -> Iterator[Engine]:
    """An engine on a new empty database of `server` for `worker`, dropped on exit."""
    name = f"{worker}_{uuid.uuid4().hex[:8]}"
    admin = create_engine(server, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as db:
            db.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_engine(server.set(database=name))
        try:
            yield engine
        finally:
            engine.dispose()
            with admin.connect() as db:
                db.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()
