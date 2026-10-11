"""Operator settings kept in the history store: the autopilot switch, the forwarder opt-in and the history window.

Each was once a JSON file beside the config. A setting with no row imports its file's value once, keeping the time the
file was last written, and retires the file by renaming it, so the file is neither read nor written again and an old
one cannot come back after a reset. A store that cannot be read leaves a setting unset, which every caller takes as its
fail-closed default.
"""

import json
import logging
from pathlib import Path
from typing import Any

from starpulse._internal.eventlog.event_log import EventLog

logger = logging.getLogger(__name__)

#: What a retired file is renamed to, so the value it held can still be read by hand.
RETIRED_SUFFIX = ".imported"


def read(log: EventLog, key: str, legacy: Path, field: str) -> Any | None:
    """The value kept under `key`; with no row, `legacy`'s `field` imported into one. None when neither holds one or
    the store cannot be read."""
    try:
        if (value := log.setting(key)) is not None:
            return value
        return _import(log, key, legacy, field)
    except Exception as exc:  # fail closed: an unreadable setting is an unset one
        logger.warning("settings: reading %s failed: %s", key, exc)
        return None


def write(log: EventLog, key: str, value: Any, legacy: Path) -> None:
    """Keep `value` under `key` and retire `legacy`. Raises when the store cannot be written."""
    log.set_setting(key, value)
    _retire(legacy)


def clear(log: EventLog, key: str, legacy: Path) -> None:
    """Drop `key`'s row and retire `legacy`, so the setting reads as unset. Raises when the store cannot be written."""
    log.delete_setting(key)
    _retire(legacy)


def _import(log: EventLog, key: str, legacy: Path, field: str) -> Any | None:
    try:
        text = legacy.read_text()
        written = legacy.stat().st_mtime
    except OSError:
        return None
    try:
        value = json.loads(text)[field]
    except ValueError, KeyError, TypeError:
        value = None
    if value is not None:
        log.set_setting(key, value, updated_at=written)
    _retire(legacy)
    return value


def _retire(legacy: Path) -> None:
    try:
        legacy.replace(legacy.with_name(legacy.name + RETIRED_SUFFIX))
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("settings: retiring %s failed: %s", legacy, exc)
