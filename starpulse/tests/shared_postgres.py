"""One Postgres server for a whole pytest-xdist run, and a database in it for each worker.

The controller starts the container and publishes its address in a directory every worker is told about; a worker waits for
the URL and creates a database of its own, so the tables one worker drops are not another's.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, text


def _publish(root: Path, name: str, content: str) -> None:
    pending = root / f".{name}.{os.getpid()}"
    pending.write_text(content)
    pending.replace(root / name)  # a worker never reads half a file


def publish_url(root: Path, url: str) -> None:
    _publish(root, "postgres.url", url)


def publish_error(root: Path, reason: str) -> None:
    _publish(root, "postgres.error", reason)


def wait_for_url(root: Path, timeout: float) -> str:
    """The controller's address for the shared Postgres; raises when its start failed or did not finish in `timeout` seconds."""
    deadline = time.monotonic() + timeout
    while True:
        if (root / "postgres.error").is_file():
            raise RuntimeError(f"the shared Postgres did not start: {(root / 'postgres.error').read_text()}")
        if (root / "postgres.url").is_file():
            return (root / "postgres.url").read_text()
        if time.monotonic() > deadline:
            raise TimeoutError(f"the shared Postgres published no address in {timeout} s")
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


def request_service(root: Path, service: str) -> None:
    """Ask the controller to start `service`: a worker whose tests need it requests it as it collects them."""
    _publish(root, f"{service}.wanted", "")


def serve_requests(root: Path, start: Callable[[str], object], stop: threading.Event, poll: float = 0.05) -> None:
    """Call `start` once for each service a worker requests in `root`, until `stop` is set.

    The controller starts nothing up front: a run whose tests need neither container pays for neither.
    """
    started: set[str] = set()
    while not stop.wait(poll):
        for service in sorted({path.stem for path in root.glob("*.wanted")} - started):
            started.add(service)
            start(service)
