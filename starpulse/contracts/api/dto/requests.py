"""The body each write route takes."""

from __future__ import annotations

from typing import Any

from starpulse.contracts.api._base import _Api
from starpulse.contracts.api.dto.forwarding import QuietHours


class _Writer(_Api):
    """The writer a board write names: `actor` is `operator` from the page and `agent` from a session; a write naming
    neither is `anonymous`. The `session` and `harness` it names land on the change's `board:lanes` row."""

    actor: str | None = None
    session: str | None = None
    harness: str | None = None


class MoveRequest(_Writer):
    """`POST /api/move`: move `task` to the column `to`."""

    task: str
    to: str


class StartRequest(_Api):
    """`POST /api/start`: start a session for `task` on `profile`; `harness` defaults to `claude`.

    `assignee` is the legacy name of `profile` and is read when `profile` is absent.
    """

    task: str
    profile: str | None = None
    assignee: str | None = None
    harness: str | None = None
    mode: str | None = None


class EditRequest(_Writer):
    """`POST /api/edit`: change fields of `task`; `base` holds the value each changed field had when the page read it."""

    task: str
    base: dict[str, Any]
    changes: dict[str, Any]
    comment: str | None = None


class ArchiveRequest(_Writer):
    """`POST /api/archive`: archive `task`, recording `reason` when it is not blank."""

    task: str
    reason: str | None = None


class RestoreRequest(_Api):
    """`POST /api/restore`: return the archived task `task` to the board's tasks, unchanged."""

    task: str


class RetireRequest(_Api):
    """`POST /api/retire`: take the finished task `task` off the board into the history store's retired tasks."""

    task: str


class RetiredImportRequest(_Api):
    """`POST /api/retired/import`: keep the retired task file `name`, holding `text`, in the history store."""

    name: str
    text: str


class CompleteRequest(_Api):
    """`POST /api/complete`: move the Done task `task` into the board's completed tasks."""

    task: str


class ClaimRequest(_Writer):
    """`POST /api/claim`: move `task` to In Progress and record `session` as its holder, an opaque string; the same
    holder claiming again changes nothing, and a holder already on another open claim is refused."""

    task: str


class ParkRequest(_Writer):
    """`POST /api/park`: pause `task` on exactly one reason, which picks the lane: `untilTask` (tasks that must reach
    Done) and `until` (criteria a check can observe) wait; `operator` (what only the operator can do) needs attention."""

    task: str
    untilTask: list[str] | None = None
    until: list[dict[str, Any]] | None = None
    operator: str | None = None
    comment: str | None = None


class ReviewRequest(_Writer):
    """`POST /api/review`: move `task` to Review, adding `references` and `summary` first so the configured rules judge
    the record the move would leave."""

    task: str
    references: list[str] | None = None
    summary: str | None = None
    comment: str | None = None


class CreateRequest(_Writer):
    """`POST /api/tasks`: create a task in the board's starting lane, stamped `created_by: <harness>:<session>`."""

    title: str
    description: str | None = None
    priority: str | None = None
    milestone: str | None = None
    profile: str | None = None
    assignee: str | None = None
    labels: list[str] | None = None
    dependencies: list[str] | None = None
    acceptanceCriteria: list[str] | None = None


class VerdictRequest(_Writer):
    """`POST /api/verdict`: record `verdict` (`pass` or `miss`) for `check` of `task`'s `## Post-merge Checks`.

    A `miss` names the task `fix` that repairs it; `evidence` is kept in the verdict's comment.
    """

    task: str
    check: str
    verdict: str
    evidence: str | None = None
    fix: str | None = None


class MissRequest(_Writer):
    """`POST /api/miss`: file the task `fix` and record `check` of `task` as missed, naming it, in one write."""

    task: str
    check: str
    fix: CreateRequest
    evidence: str | None = None


class MilestoneCreateRequest(_Api):
    """`POST /api/milestones`: open a milestone; only the title is required."""

    title: str
    outcome: str | None = None
    specs: list[str] | None = None
    adrs: list[str] | None = None
    retro: str | None = None


class MilestoneEditRequest(_Api):
    """`POST /api/milestones/edit`: replace the `title`, `outcome`, `specs`, `adrs` or `retro` `changes` names."""

    milestone: str
    changes: dict[str, Any]


class MilestoneArchiveRequest(_Api):
    """`POST /api/milestones/archive`: archive `milestone`."""

    milestone: str


class DocCreateRequest(_Api):
    """`POST /api/docs`: file a doc; only the title is required. `type` is `specification`, `guide`, `readme` or `other`."""

    title: str
    type: str | None = None
    folder: str | None = None
    body: str | None = None


class DocEditRequest(_Api):
    """`POST /api/docs/edit`: replace the `title`, `type` or `body` `changes` names."""

    doc: str
    changes: dict[str, Any]


class DocArchiveRequest(_Api):
    """`POST /api/docs/archive`: archive `doc`."""

    doc: str


class DocRestoreRequest(_Api):
    """`POST /api/docs/restore`: return the archived doc `doc` to `folder` under the board's docs (the docs folder
    itself when absent), unchanged."""

    doc: str
    folder: str | None = None


class WindowRequest(_Api):
    """`PUT /api/history-window`: set the shared history window."""

    hours: float


class ForwardingRequest(_Api):
    """`PUT /api/forwarding`: whether a person's name may leave the instance."""

    opt_in: bool


class AutopilotRequest(_Api):
    """`PUT /api/autopilot`: whether the autopilot admits tasks, which harness it starts on, and/or its quiet hours."""

    enabled: bool | None = None
    harness: str | None = None
    quietHours: QuietHours | None = None


class RunEventRequest(_Api):
    """`POST /api/runs/events`: one workflow or step event a producer reports."""

    event: str
    workflow: str
    run_id: str
    status: str
    time: float | None = None
    step: str | None = None
    depends: list[str] | None = None


class ForwardedEvent(_Api):
    event_id: str
    stream: str
    fields: dict[str, Any]


class ForwardRequest(_Api):
    """`POST /api/forward`: a batch of events an instance's forwarder sends a hub."""

    opt_in: bool
    instance: str
    events: list[ForwardedEvent]
