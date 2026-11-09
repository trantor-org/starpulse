"""Opening the event log a config names, and the latest machine event of a run, for every context that produces.

`database_url` in the config names the SQLite database; without one it is a file beside the config.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, func, or_, select

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import machine_events

#: The file a config without `database_url` keeps its history in, beside the config.
DEFAULT_FILE = "starpulse-history.sqlite"


def database_url(configured: str | None, directory: Path) -> str:
    """The configured URL, else a SQLite file `DEFAULT_FILE` in `directory`."""
    return configured or f"sqlite:///{(directory / DEFAULT_FILE).resolve()}"


def open_event_log(configured: str | None, path: Path | None) -> EventLog:
    """The event log in the store `serve --config path` keeps its history in, so a producer and the view share it.

    `configured` is the `database_url` of the config at `path`, which the runtime discovers and loads as `serve` does
    (`path`, else `starpulse.toml` in the working directory, else the defaults); with no file, the working directory
    holds the default database.
    """
    return EventLog(database_url(configured, path.parent if path else Path.cwd()))


def last_run_event(engine: Engine, run: str, task: str | None = None) -> float | None:
    """Epoch of the latest machine event of run `run`, or of task `task` when given, on `engine`; None when there is
    none: the harness keys a taskless session's telemetry by its session id and a task-branch session's by its task, so
    this is when that session last acted."""
    c = machine_events.c
    match = (c.run == run) if task is None else or_(c.run == run, c.task == task)
    with engine.connect() as db:
        return db.execute(select(func.max(c.occurred_at)).where(match)).scalar()
