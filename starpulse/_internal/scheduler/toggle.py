"""The scheduler's on/off switch: a row in the history store, so a restart keeps it and flipping it needs no config edit."""

from pathlib import Path

from starpulse.event_log import operator_settings
from starpulse.event_log.event_log import EventLog

#: The switch's file before it moved into the store; a file by this name in `state_dir` is imported once.
TOGGLE_FILE = "starpulse-scheduler.json"
KEY = "scheduler.enabled"


class Toggle:
    """Whether the scheduler admits tasks: the flag in the store, off unless it says `true`.

    A missing or unreadable setting leaves it off, so a fresh install admits nothing until the operator turns it on.
    `legacy` is the switch's old file, imported when the store holds no row.
    """

    def __init__(self, log: EventLog, legacy: Path) -> None:
        self.log = log
        self.legacy = legacy

    def get(self) -> bool:
        return operator_settings.read(self.log, KEY, self.legacy, "enabled") is True

    def set(self, value: bool) -> None:
        operator_settings.write(self.log, KEY, value, self.legacy)
