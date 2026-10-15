"""Autopilot rows in the history store that a restart restores: in-flight runs, start times, last sample."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from starpulse._internal.eventlog.event_log import EventLog

logger = logging.getLogger(__name__)

INFLIGHT_KEY = "autopilot.inflight"
STARTS_KEY = "autopilot.starts"
SAMPLE_KEY = "autopilot.sample"
#: Seconds a start record blocks another admission when in-flight restore missed.
START_COOLDOWN = 15 * 60


class AutopilotState:
    """JSON blobs under the settings keys; a store that cannot be read or written is skipped, never raised."""

    def __init__(self, log: EventLog) -> None:
        self.log = log

    def load(self, key: str) -> Any | None:
        try:
            return self.log.setting(key)
        except Exception as exc:
            logger.warning("autopilot state: reading %s failed: %s", key, exc)
            return None

    def save(self, key: str, value: Any) -> None:
        try:
            self.log.set_setting(key, value)
        except Exception:
            logger.exception("autopilot state: cannot write %s", key)

    def inflight(self) -> dict[str, dict[str, Any]]:
        raw = self.load(INFLIGHT_KEY)
        return raw if isinstance(raw, dict) else {}

    def save_inflight(self, rows: Mapping[str, Mapping[str, Any]]) -> None:
        self.save(INFLIGHT_KEY, dict(rows))

    def starts(self) -> dict[str, float]:
        raw = self.load(STARTS_KEY)
        if not isinstance(raw, dict):
            return {}
        try:
            return {task: float(at) for task, at in raw.items()}
        except TypeError, ValueError:
            return {}

    def save_starts(self, rows: Mapping[str, float]) -> None:
        self.save(STARTS_KEY, dict(rows))

    def sample(self) -> tuple[list[dict[str, Any]], float] | None:
        raw = self.load(SAMPLE_KEY)
        if not isinstance(raw, dict) or "readings" not in raw or "at" not in raw:
            return None
        readings, at = raw["readings"], raw["at"]
        if not isinstance(readings, list):
            return None
        try:
            return readings, float(at)
        except TypeError, ValueError:
            return None

    def save_sample(self, readings: list[dict[str, Any]], at: float) -> None:
        self.save(SAMPLE_KEY, {"readings": readings, "at": at})
