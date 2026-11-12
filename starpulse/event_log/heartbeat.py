"""Loop heartbeats: a worker touches a file in the directory `serve` names, and `/metrics` reads each file's time.

The tick is a file touch, never a database write: a loop stalled behind the writer's lock goes stale instead of
queuing its own beat behind the lock it is watched for."""

import logging
import os
import tempfile
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

ENV = "STARPULSE_HEARTBEAT_DIR"
METRIC = "starpulse_worker_heartbeat_timestamp_seconds"
INTERVAL_S = 5.0


def make_directory() -> None:
    """Name this `serve`'s directory in the environment its workers inherit, keeping the one a re-exec inherited."""
    if not os.environ.get(ENV):
        os.environ[ENV] = tempfile.mkdtemp(prefix="starpulse-heartbeat-")


def beat(worker: str) -> None:
    """Record that `worker`'s loop ticked now. Nothing without a directory; a failed touch is logged, never raised."""
    directory = os.environ.get(ENV)
    if not directory:
        return
    try:
        (Path(directory) / worker).touch()
    except OSError:
        logger.warning("heartbeat: %s was not recorded", worker, exc_info=True)


def keep(worker: str, stop: threading.Event, interval: float = INTERVAL_S) -> threading.Thread:
    """Start the daemon thread that beats `worker` now and every `interval` seconds until `stop` is set."""

    def tick() -> None:
        while not stop.wait(interval):
            beat(worker)

    beat(worker)
    ticker = threading.Thread(target=tick, name=f"heartbeat-{worker}", daemon=True)
    ticker.start()
    return ticker


def exposition() -> str:
    """The Prometheus text of each worker's last beat; empty without a directory or any beat."""
    directory = os.environ.get(ENV)
    try:
        beats = sorted((path.name, path.stat().st_mtime) for path in Path(directory).iterdir()) if directory else []
    except OSError:
        return ""
    if not beats:
        return ""
    samples = "".join(f'{METRIC}{{worker="{name}"}} {mtime}\n' for name, mtime in beats)
    return f"# HELP {METRIC} Unix time of the worker's last loop tick.\n# TYPE {METRIC} gauge\n{samples}"
