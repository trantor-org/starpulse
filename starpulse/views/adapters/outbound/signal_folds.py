"""The analytics views' per-session folds, read from `starpulse_signal_folds`, and the worker that counts them into the
skill-cost series.

Ingest writes the folds (`flow_metrics.adapters.outbound.session_ledger`), so nothing here folds a signal: `window` and
`changed` read the stored results, and `catch_up` follows the sessions whose `cost` fold was rewritten past its cursor
(`CURSOR`, a revision of the folds' counter). It adds what each cost fold grew since the last one counted
(the session's `counted` row) to the `skill_cost` series.
"""

import logging
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from sqlalchemy import bindparam, func, select, text
from sqlalchemy.dialects import sqlite

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import signal_folds
from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.adapters.outbound.session_ledger import REVISION, VIEWS
from starpulse.flow_metrics.model import cells
from starpulse.views.adapters.outbound import skill_cost

__all__ = ["CURSOR", "VIEWS", "SignalFolds", "changed"]

log = logging.getLogger(__name__)

#: The settings key holding the revision every fold at or below it has been counted into the skill-cost series.
CURSOR = "skill_cost_cursor"
_COUNTED = "counted"

_WINDOW = text(
    "SELECT view, harness, session, first_at, result FROM starpulse_signal_folds"
    " INDEXED BY ix_starpulse_signal_folds_last_at"  # SQLAlchemy's SQLite dialect renders no table hint
    " WHERE view IN :views AND last_at >= :floor ORDER BY first_at, harness, session"
).bindparams(bindparam("views", expanding=True)).columns(
    signal_folds.c.view, signal_folds.c.harness, signal_folds.c.session, signal_folds.c.first_at, signal_folds.c.result
)


def changed(events: EventLog, after: int, views: Iterable[str], since: float = 0.0) -> tuple[int, dict[str, list[Any]]]:
    """The per-session results of the `views` for each session an export advanced past the revision `after` (and with a
    signal at or after `since`), oldest first, with the revision to pass as `after` next time.

    A revision is taken and committed with its fold under one write lock, so a mark taken from this never skips a
    session; a session an export advanced again comes back."""
    through = events.setting(REVISION) or 0
    wanted = tuple(views)
    query = (
        select(signal_folds.c.view, signal_folds.c.result)
        .where(
            signal_folds.c.view.in_(wanted),
            signal_folds.c.folded_through > after,
            signal_folds.c.folded_through <= through,
            signal_folds.c.last_at >= since,
        )
        .order_by(signal_folds.c.first_at, signal_folds.c.harness, signal_folds.c.session)
    )
    with events.engine.connect() as db:
        rows = db.execute(query).all()
    answer: dict[str, list[Any]] = {view: [] for view in wanted}
    for view, result in rows:
        answer[view].append(result)
    return through, answer


def _inside(view: str, result: Any, since: float) -> Any:
    """`result` of a session that began before `since`, its steps cut to those at or after it; the other views' results
    hold no step, so they are whole."""
    if view == "steps":
        return [step for step in result if step["at"] >= since]
    if view == "spend":
        return {**result, "steps": [step for step in result["steps"] if step["at"] >= since]}
    return result


class SignalFolds:
    """Reads the sessions' stored folds by window, and counts their cost into the skill-cost series."""

    def __init__(
        self, events: EventLog, titled: Callable[[set[str]], Mapping[str, Mapping[str, Any]]] | None = None
    ) -> None:
        self._titled = titled  # the board's tasks, by id; without it nothing is counted
        self._events = events
        self._engine = events.engine

    def window(self, since: float, views: Iterable[str] = VIEWS) -> dict[str, list[Any]]:
        """The per-session results of the `views` for the sessions that have a signal at or after `since`, oldest
        first, to combine; no other view's rows are read. A session that began before `since` keeps the steps of its
        folds from `since` on, and the cost of all its steps. The read names the `last_at` index: left to itself SQLite
        walks the whole primary-key range of each view (every session ever folded) to test `last_at`."""
        wanted = tuple(views)
        with self._engine.connect() as db:
            rows = db.execute(_WINDOW, {"views": wanted, "floor": since}).all()
        answer: dict[str, list[Any]] = {view: [] for view in wanted}
        for row in rows:
            answer[row.view].append(_inside(row.view, row.result, since) if row.first_at < since else row.result)
        return answer

    def oldest(self) -> float | None:
        """The time of the oldest folded signal, None when nothing is folded: the history the views can answer."""
        with self._engine.connect() as db:
            return db.execute(select(func.min(signal_folds.c.first_at))).scalar_one()

    def catch_up(self) -> int:
        """Count the cost of each session an export advanced past the cursor, and return how many sessions that was.

        Each adds the growth of its `cost` fold over the one counted before it to the skill series, and keeps the fold
        it counted. The cursor moves to the revision read before the sessions, so a session an export advanced during
        the pass is the next pass's. Raises when the database does."""
        if self._titled is None:
            return 0
        cursor = self._events.setting(CURSOR) or 0
        through = self._events.setting(REVISION) or 0
        if through <= cursor:
            return 0
        with self._engine.connect() as db:
            rows = db.execute(
                select(
                    signal_folds.c.harness,
                    signal_folds.c.session,
                    signal_folds.c.first_at,
                    signal_folds.c.last_at,
                    signal_folds.c.folded_through,
                    signal_folds.c.result,
                )
                .where(
                    signal_folds.c.view == "cost",
                    signal_folds.c.folded_through > cursor,
                    signal_folds.c.folded_through <= through,
                )
                .order_by(signal_folds.c.folded_through)
            ).all()
        tasks = self._titled({cost["task"] for row in rows for cost in row.result}) if rows else {}
        for row in rows:
            with self._engine.begin() as db:
                before = db.execute(
                    select(signal_folds.c.result).where(
                        signal_folds.c.view == _COUNTED,
                        signal_folds.c.harness == row.harness,
                        signal_folds.c.session == row.session,
                    )
                ).scalar()
                skill_cost.add(cells.cost_increase(before or [], row.result, tasks))
                kept = sqlite.insert(signal_folds).values(
                    view=_COUNTED,
                    harness=row.harness,
                    session=row.session,
                    first_at=row.first_at,
                    last_at=row.last_at,
                    folded_through=row.folded_through,
                    result=row.result,
                )
                db.execute(
                    kept.on_conflict_do_update(
                        index_elements=["view", "harness", "session"],
                        set_={"folded_through": kept.excluded.folded_through, "result": kept.excluded.result},
                    )
                )
        self._events.set_setting(CURSOR, through)
        if rows:
            self._events.put_state(skill_cost.STATE, skill_cost.exposition())
        return len(rows)

    def follow(self, stop: StopEvent) -> None:
        """Run `catch_up` after each append or another process's commit until `stop` is set."""
        self._events.run_on_wake(stop, self.catch_up, "skill cost catch-up failed")
