"""The scheduler's on/off switch: a row in the history store, so a restart keeps it and flipping it needs no config edit."""

import logging

from starpulse.event_log.event_log import EventLog

logger = logging.getLogger(__name__)

#: The switch's file before it moved into the store; `starpulse migrate` imports a file by this name once.
TOGGLE_FILE = "starpulse-scheduler.json"
KEY = "scheduler.enabled"


class Toggle:
    """Whether the scheduler admits tasks: the flag in the store, off unless it says `true`.

    A missing or unreadable setting leaves it off, so a fresh install admits nothing until the operator turns it on.
    """

    def __init__(self, log: EventLog) -> None:
        self.log = log

    def get(self) -> bool:
        try:
            return self.log.setting(KEY) is True
        except Exception as exc:  # fail closed: an unreadable switch is off
            logger.warning("scheduler toggle: reading %s failed: %s", KEY, exc)
            return False

    def set(self, value: bool) -> None:
        self.log.set_setting(KEY, value)
