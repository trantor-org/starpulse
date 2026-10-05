"""The settings StarPulse Admin writes to the server: a declared default, an override kept beside the config, and Reset."""

import json
import os
import threading
from pathlib import Path
from typing import Any, TypeGuard

from starpulse.board_feed import BoardFeed

#: The history window Admin may set, in hours.
MIN_HOURS, MAX_HOURS = 1, 72
#: Where the override lives, in the directory of the `--config` file (the working directory without one).
SETTINGS_FILE = "starpulse-settings.json"


def _valid(hours: object) -> TypeGuard[float]:
    return isinstance(hours, int | float) and not isinstance(hours, bool) and MIN_HOURS <= hours <= MAX_HOURS


class HistoryWindow:
    """How far back a task's latest move counts: the declared `--hours`, or the override Admin wrote over it.

    The override is read from `path` at construction, so it survives a restart; a file that is missing, unreadable
    or holds a value outside the range leaves the declared hours. Every change reaches `feed` at once.
    """

    def __init__(self, feed: BoardFeed, declared_hours: float, path: Path) -> None:
        self._feed = feed
        self._declared = declared_hours
        self._path = path
        self._lock = threading.Lock()
        self._override = self._read()
        self._apply()

    def _read(self) -> float | None:
        try:
            hours = json.loads(self._path.read_text())["history_hours"]
        except OSError, ValueError, KeyError, TypeError:
            return None
        return hours if _valid(hours) else None

    def _apply(self) -> None:
        self._feed.set_window(self.hours * 3600)

    @property
    def hours(self) -> float:
        override = self._override
        return self._declared if override is None else override

    def state(self) -> dict[str, Any]:
        """The effective window, the declared default, and whether Admin's override is what is in effect."""
        return {"hours": self.hours, "default": self._declared, "overridden": self._override is not None}

    def set(self, hours: object) -> None:
        """Keep `hours` as the override and draw with it; a value outside 1-72 raises ValueError and changes nothing."""
        if not _valid(hours):
            raise ValueError(f"history window must be between {MIN_HOURS} and {MAX_HOURS} hours; got {hours}")
        with self._lock:
            scratch = self._path.with_name(f"{self._path.name}.tmp")
            scratch.write_text(json.dumps({"history_hours": hours}))
            os.replace(scratch, self._path)  # a restart reads the old file or the new one, never half of one
            self._override = hours
            self._apply()

    def reset(self) -> None:
        """Delete the override: the window returns to the declared hours."""
        with self._lock:
            self._path.unlink(missing_ok=True)
            self._override = None
            self._apply()
