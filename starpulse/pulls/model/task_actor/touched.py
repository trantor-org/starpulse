"""The domain event every trigger of the task actor emits: a task was touched."""

from dataclasses import dataclass
from enum import StrEnum


class Trigger(StrEnum):
    """The standard triggers a task state re-derives on (ADR Every Task State Re-Derives on One Trigger Set)."""

    ON_ENTRY = "on-entry"
    ON_EXIT = "on-exit"
    ON_IDLE = "on-idle"
    ON_SUBSTATE_CHANGE = "on-substate-change"
    ON_WEBHOOK = "on-webhook"
    ON_ALERT = "on-alert"


@dataclass(frozen=True, slots=True)
class TaskTouched:
    """A source touched `task`: the actor derives it, whatever the `trigger`, and `cause` says what the source saw."""

    task: str
    trigger: Trigger
    cause: str
