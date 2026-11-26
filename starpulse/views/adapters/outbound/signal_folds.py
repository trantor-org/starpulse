"""The analytics views' per-session folds, read from `starpulse_signal_folds`, and the worker that counts them into the
skill-cost series.

Ingest writes the folds (`flow_metrics.adapters.outbound.session_ledger`), so nothing here folds a signal: `window` and
`changed` read the stored results, and `catch_up` follows the sessions whose `cost` fold was rewritten past its cursor
(`CURSOR`, a revision of the folds' counter). It adds what each cost fold grew since the last one counted
(the session's `counted` row) to the `skill_cost` series.
"""

import logging
import threading
import time
from collections import ChainMap
from collections.abc import Callable, Iterable, Mapping
from typing import Any, NamedTuple

from sqlalchemy import Connection, and_, bindparam, func, select, text
from sqlalchemy.dialects import sqlite

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.table_registry import is_stamped
from starpulse.event_log.tables import signal_folds, task_phase_spend, task_sessions
from starpulse.event_log.signals import setting
from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.adapters.outbound.session_ledger import REVISION, VIEWS
from starpulse.flow_metrics.model import cells
from starpulse.views.adapters.outbound import skill_cost, task_spend

__all__ = ["CURSOR", "VIEWS", "SignalFolds", "changed"]

log = logging.getLogger(__name__)

#: The settings key holding the revision every fold at or below it has been counted into the skill-cost series.
CURSOR = "skill_cost_cursor"
_COUNTED = "counted"

_OWN = (
    select(signal_folds.c.first_at, signal_folds.c.result)
    .select_from(
        task_sessions.join(
            signal_folds,
            and_(
                signal_folds.c.view == "spend",
                signal_folds.c.harness == task_sessions.c.harness,
                signal_folds.c.session == task_sessions.c.session,
            ),
        )
    )
    .where(task_sessions.c.task == bindparam("task"), signal_folds.c.last_at >= bindparam("floor"))
    .order_by(task_sessions.c.harness, task_sessions.c.session)
)
_PEERS = select(
    task_phase_spend.c.task,
    task_phase_spend.c.phase,
    task_phase_spend.c.profile,
    task_phase_spend.c.wte,
    task_phase_spend.c.last_at,
).where(task_phase_spend.c.last_at >= bindparam("floor"))
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


#: How long a kept peer cell index and oldest signal answer reads, in seconds: a peer's labels or rows a spend read
#: sees can be this old, the asked task's own rows and labels never.
PEER_TTL_S = 30.0


def _norm_cell(tasks: Mapping[str, Mapping[str, Any]], task: str) -> tuple[str, int] | None:
    """The cell `task` is pooled in: none for a `batch-umbrella`, which is in no norm cell."""
    return None if cells.is_umbrella(tasks, task) else cells.cell_of(tasks, task)


class _Peers(NamedTuple):
    floor: float
    built_at: float
    cells: dict[tuple[str, int], list[tuple[str, str, str, float, float]]]
    tasks: Mapping[str, Mapping[str, Any]]


class SignalFolds:
    """Reads the sessions' stored folds by window, and counts their cost into the skill-cost series."""

    def __init__(
        self,
        events: EventLog,
        titled: Callable[[set[str]], Mapping[str, Mapping[str, Any]]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._titled = titled  # the board's tasks, by id; without it nothing is counted
        self._events = events
        self._engine = events.engine
        self._clock = clock
        self._lock = threading.Lock()
        self._peers: _Peers | None = None
        self._oldest: tuple[float, float] | None = None  # (read at, the oldest signal's time)

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

    def task_spend(
        self, task: str, since: float
    ) -> tuple[list[Any], dict[tuple[str, str], tuple[str, float]], Mapping[str, Mapping[str, Any]]] | None:
        """The spend folds of `task`'s sessions with a signal at or after `since`, cut as `window` cuts them and in the
        order `combine_spend` takes them, the phase rows with a step in that window of the tasks in its (kind, size) cell (a batch umbrella's, each member's cell),
        as `spend.task_spend` weighs `task` against them, and the board's labels of those tasks and `task`; None while
        the task_spend family is being refolded. A peer's row is its spend over all its sessions, so a task that began
        before `since` weighs in whole. The cell's rows and labels are kept for `PEER_TTL_S` seconds: only `task`'s own
        rows and labels are read each call. Without a board (`titled`), no task has a cell and no peers."""
        titled = self._titled or (lambda _: {})
        with self._engine.connect() as db:
            if not is_stamped(db, task_spend.FAMILY, task_spend.STAMP):
                return None
            own = db.execute(_OWN, {"task": task, "floor": since}).all()
            held = self._peers_of(db, titled, since)
        mine = titled({task})
        peers = {
            (peer, phase): (profile, wte)
            for cell in set(cells.norm_cells(mine, task))
            for peer, phase, profile, wte, last_at in held.cells.get(cell, ())
            if last_at >= since
        }
        return (
            [_inside("spend", row.result, since) if row.first_at < since else row.result for row in own],
            peers,
            ChainMap(dict(mine), held.tasks),
        )

    def _peers_of(
        self, db: Connection, titled: Callable[[set[str]], Mapping[str, Mapping[str, Any]]], since: float
    ) -> "_Peers":
        held = self._peers
        if held is None or since < held.floor or self._clock() - held.built_at > PEER_TTL_S:
            with self._lock:
                held = self._peers
                if held is None or since < held.floor or self._clock() - held.built_at > PEER_TTL_S:
                    rows = db.execute(_PEERS, {"floor": since}).all()
                    tasks = titled({row.task for row in rows}) if rows else {}
                    grouped: dict[tuple[str, int], list[tuple[str, str, str, float, float]]] = {}
                    for row in rows:
                        cell = _norm_cell(tasks, row.task)
                        if cell is not None:
                            grouped.setdefault(cell, []).append(
                                (row.task, row.phase, row.profile, row.wte, row.last_at)
                            )
                    held = self._peers = _Peers(since, self._clock(), grouped, tasks)
        return held

    def oldest(self) -> float | None:
        """The time of the oldest folded signal, None when nothing is folded: the history the views can answer. A
        signal is found for `PEER_TTL_S` seconds, since a fold only ever moves it earlier."""
        held = self._oldest
        if held is not None and self._clock() - held[0] <= PEER_TTL_S:
            return held[1]
        with self._engine.connect() as db:
            found = db.execute(select(func.min(signal_folds.c.first_at))).scalar_one()
        self._oldest = None if found is None else (self._clock(), found)
        return found

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
        """Run `catch_up` each time another process moves the signal revision, until `stop` is set."""
        self._events.run_on_wake(stop, self.catch_up, "skill cost catch-up failed", setting(REVISION))
