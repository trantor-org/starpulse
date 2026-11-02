"""The statements that read the Task tables: each is one index seek or one bounded index range, never a table scan.

`ReadModel` runs them; the tests EXPLAIN them. Archived Tasks stay out of every live query by the `archived = 0`
predicate the partial indexes carry, so the cost of a read follows the live board, not the whole History.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, Select, and_, column, exists, false, func, or_, select, true

from starpulse.event_log.lane_events import done_lanes
from starpulse.event_log.readmodel.tables import criteria, tasks

SUMMARY = (
    tasks.c.id,
    tasks.c.seq,
    tasks.c.version,
    tasks.c.title,
    tasks.c.type,
    tasks.c.state,
    tasks.c.priority,
    tasks.c.milestone,
    tasks.c.assignee,
    tasks.c.released,
    tasks.c.archived,
    tasks.c.labels,
    tasks.c.updated_at,
)


#: What a card on the page draws that a delta summary leaves out; `meta` carries the Task's profile.
CARD = (*SUMMARY, tasks.c.description, tasks.c.dependencies, tasks.c.references, tasks.c.meta)


def live(done: str, since: float) -> ColumnElement[bool]:
    """The live Tasks: unarchived, and either outside the done lanes or changed at or after `since` (local midnight).

    The partial index `ix_starpulse_tasks_live_set` on `(archived, state, updated_at)` serves it, so a Done Task
    changed before `since` costs the read nothing.
    """
    lane = func.lower(func.replace(tasks.c.state, " ", "_"))
    return and_(tasks.c.archived == false(), or_(lane.not_in(done_lanes(done)), tasks.c.updated_at >= since))


def held_states() -> Select[Any]:
    """The states unarchived Tasks hold, Done ones of any age included."""
    return select(tasks.c.state).where(tasks.c.archived == false()).distinct()


def milestone_done(done: str, since: float) -> Select[Any]:
    """How many Done Tasks each milestone holds that `live` leaves out: unarchived and last changed before `since`."""
    lane = func.lower(func.replace(tasks.c.state, " ", "_"))
    return (
        select(tasks.c.milestone, func.count())
        .where(
            tasks.c.archived == false(),
            lane.in_(done_lanes(done)),
            tasks.c.updated_at < since,
            tasks.c.milestone != "",
        )
        .group_by(tasks.c.milestone)
    )


def snapshot(done: str, since: float) -> Select[Any]:
    """The live Tasks (`live`), in id order."""
    return select(*CARD).where(live(done, since)).order_by(tasks.c.id)


def live_criteria(done: str, since: float) -> Select[Any]:
    """The live Tasks' Acceptance Criteria, in task and number order."""
    return (
        select(criteria.c.task_id, criteria.c.kind, criteria.c.text, criteria.c.checked)
        .join(tasks, tasks.c.id == criteria.c.task_id)
        .where(live(done, since), criteria.c.kind == "ac")
        .order_by(criteria.c.task_id, criteria.c.n)
    )


def with_field(field_column: str, value: object) -> Select[Any]:
    """The ids of unarchived Tasks whose declared, queried field's generated column equals `value`."""
    return select(tasks.c.id).where(tasks.c.archived == false(), column(field_column) == value).order_by(tasks.c.id)


def ready(state: str, done: str) -> Select[Any]:
    """The ids of unarchived Tasks in `state` none of whose dependencies is outside `done_lanes(done)`.

    `state` is a stored status (`Ready`) and `done` a lane id (`done`), as `lane_id` makes one; a dependency with no
    row blocks too: it is a Task the board has not imported yet.
    """
    dependency = func.json_each(tasks.c.dependencies).table_valued("value").alias("dependency")
    target = tasks.alias("target")
    blocked = (
        select(1)
        .select_from(dependency.outerjoin(target, target.c.id == dependency.c.value))
        .where(or_(target.c.id.is_(None), func.lower(func.replace(target.c.state, " ", "_")).not_in(done_lanes(done))))
    )
    return (
        select(tasks.c.id)
        .where(tasks.c.archived == false(), tasks.c.state == state, ~exists(blocked.correlate(tasks)))
        .order_by(tasks.c.id)
    )


def since(seq: int, limit: int) -> Select[Any]:
    """The Tasks changed after stream position `seq`, archived ones included, oldest change first."""
    return select(*SUMMARY).where(tasks.c.seq > seq).order_by(tasks.c.seq).limit(limit)


def archived(before: float | None, limit: int) -> Select[Any]:
    """The archived Tasks changed before `before` (None: any time), newest first: one range of the archive index."""
    query = select(*SUMMARY).where(tasks.c.archived == true()).order_by(tasks.c.updated_at.desc(), tasks.c.id)
    return (query if before is None else query.where(tasks.c.updated_at < before)).limit(limit)


def position() -> Select[Any]:
    """The stream position of the newest change: one seek on the `seq` index."""
    return select(func.max(tasks.c.seq))
