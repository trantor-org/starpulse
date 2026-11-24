"""The start a task actor wants sent and the scheduler's admission gate lets through, and the start the scheduler could not make:
three states in the event log.

The task actor (Delivery) keeps a `want` for a resume or a nudge it has to send; the scheduler loop decides each wanted
start against the room left and keeps the `admitted` ones. The two contexts meet only here, so a refused start waits on the
log's write that admits it, never on a clock.
"""

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # annotation only: the event log opens the database stack, which the pulls worker loads late
    from starpulse.event_log.event_log import EventLog
    from starpulse.event_log.wake import StopEvent

WANTED = "starts.wanted"
ADMITTED = "starts.admitted"
FAILED = "starts.failed"


def wanted(log: EventLog) -> dict[str, dict[str, Any]]:
    """Each task whose start waits for the gate: its `verb` (`resume` or `nudge`) and the `at` it was wanted."""
    _, kept = log.state(WANTED)
    return {task: row for task, row in kept.items() if isinstance(row, dict)} if isinstance(kept, dict) else {}


def admitted(log: EventLog) -> dict[str, float]:
    """Each task the gate admitted, with the `at` of the want it admitted: a later want of the same task is a new ask."""
    _, kept = log.state(ADMITTED)
    return {str(task): float(at) for task, at in kept.items()} if isinstance(kept, dict) else {}


def want(log: EventLog, task: str, verb: str) -> None:
    """Ask the gate for `task`'s `verb` start; a want already kept is left as it is, so the loop is not woken again."""
    if (kept := wanted(log).get(task)) is None or kept["verb"] != verb:
        log.put_state_entry(WANTED, task, {"verb": verb, "at": time.time()})


def is_admitted(log: EventLog, task: str, verb: str) -> bool:
    """Whether the gate admitted the `verb` start now wanted for `task`."""
    kept = wanted(log).get(task)
    return kept is not None and kept["verb"] == verb and admitted(log).get(task) == kept["at"]


def withdraw(log: EventLog, task: str) -> None:
    """Take `task`'s want back: its start was sent, or no longer needed."""
    if task in wanted(log):
        log.put_state_entry(WANTED, task, None)


def admit(log: EventLog, grants: dict[str, float]) -> None:
    """Keep `grants` as the admitted starts, writing only a change, since each write wakes the task actor."""
    if admitted(log) != grants:
        log.put_state(ADMITTED, grants)


def follow_admitted(admitted: Callable[[], None], log: EventLog, stop: StopEvent) -> None:
    """Call `admitted` at each admission and once now, for a start admitted while the actor was down."""
    log.follow_state(ADMITTED, admitted, stop, thread_name="task-actor-admitted", catch_up=True)


def failed(log: EventLog) -> dict[str, str]:
    """Each task whose start the scheduler could not make, with the reason; the task actor parks it and takes it back."""
    _, kept = log.state(FAILED)
    return {task: reason for task, reason in kept.items() if isinstance(reason, str)} if isinstance(kept, dict) else {}


def fail(log: EventLog, task: str, reason: str) -> None:
    """Hand the task actor a start that failed, so the task parks in Needs attention with `reason`."""
    log.put_state_entry(FAILED, task, reason)


def forgive(log: EventLog, task: str) -> None:
    """Take a failed start back: the task actor parked the task, or it no longer needs one."""
    if task in failed(log):
        log.put_state_entry(FAILED, task, None)


def follow_failed(failed: Callable[[], None], log: EventLog, stop: StopEvent) -> None:
    """Call `failed` at each failed start and once now, for a start that failed while the actor was down."""
    log.follow_state(FAILED, failed, stop, thread_name="task-actor-failed", catch_up=True)
