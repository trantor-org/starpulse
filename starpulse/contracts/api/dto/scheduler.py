"""`/api/scheduler`."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from starpulse.contracts.api._base import _Api


class SchedulerDimension(_Api):
    """One capacity dimension's use against its limit: percent for `cpu` and `memory`, a count for `sessions`, points for `review`."""

    name: Literal["cpu", "memory", "sessions", "review"]
    use: float
    limit: float


class SchedulerSession(_Api):
    """A session the scheduler started whose task is still running: the strip's Sessions menu draws one row of it."""

    task: str
    title: str
    model: str = Field(description="The task's agent profile, empty when it has none.")
    started: float = Field(description="When the loop started the session, in epoch seconds.")
    url: str = Field(description="The session's address, as `start` answered it.")


class SchedulerNext(_Api):
    """The task the loop would admit next, or, when none fits, the top-ranked one and what it waits on."""

    task: str
    title: str
    verdict: Literal["starting", "waits"]
    reason: str = Field(
        description="`goes next`, `quiet hours` while the quiet hours hold admission, `<harness> usage limit` while "
        "that harness is paused, or the first dimension the task overfits, which the strip shows after `waits:`."
    )
    priority: str = Field(
        description="The Priority matrix cell the task ranked by, `<impact>/<urgency>`, or `default` when it has no Impact or Urgency."
    )


class SchedulerPause(_Api):
    """A harness whose admission is paused until `until` after a usage or credit limit."""

    harness: str
    until: float = Field(description="When admission for this harness may resume, in epoch seconds.")
    reason: str


class QuietHours(_Api):
    """A daily window in which the scheduler admits nothing: `start` up to `end`, `HH:MM` in `timezone`; an `end` before
    `start` runs past midnight."""

    start: str
    end: str
    timezone: str = Field(description="The IANA zone the window's times are read in, such as America/Phoenix.")


class SchedulerHarnessSessions(_Api):
    """One harness's scheduler sessions in flight against its own session cap."""

    use: float
    limit: float


class SchedulerOperatorTask(_Api):
    """A task in the eligible lane that waits on the operator's decision rather than on capacity."""

    task: str
    title: str


class SchedulerStatus(_Api):
    """Whether the scheduler admits tasks, and the capacity strip's readings; no dimensions before the first sample.

    `inFlight`, `next`, `sessionsByHarness` and `needsOperator` are served only by a server that runs a dispatch loop; without one they
    are absent.
    """

    enabled: bool
    harness: str = Field(description="The harness the loop starts sessions on; defaults to claude.")
    quietHours: QuietHours | None = Field(default=None, description="Null when no window holds admission back.")
    sampledAt: float | None
    dimensions: list[SchedulerDimension]
    inFlight: list[SchedulerSession] = Field(
        default_factory=list, description="Every live session holding an In Progress task, oldest first; `url` is empty for one the loop did not start."
    )
    next: SchedulerNext | None = Field(default=None, description="Null when no task in the eligible lane is workable.")
    pauses: list[SchedulerPause] = Field(
        default_factory=list,
        description="Harnesses whose admission is paused until `until`. Absent when none are paused.",
    )
    sessionsByHarness: dict[str, SchedulerHarnessSessions] = Field(
        default_factory=dict,
        description="Each harness's in-flight count against its session cap; the Sessions meter follows `harness`.",
    )
    needsOperator: list[SchedulerOperatorTask] = Field(
        default_factory=list,
        description="The `kind-decide` tasks in the eligible lane, which the scheduler never starts: the operator decides.",
    )
