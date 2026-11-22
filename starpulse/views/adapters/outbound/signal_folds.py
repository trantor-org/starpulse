"""The analytics views' per-session folds, kept in `starpulse_signal_folds` and advanced from a rowid cursor.

A fold of one harness session is a plain-JSON result (`fold_health` and its siblings). `catch_up` folds only the
sessions with `starpulse_signals` rows above the stored cursor (`CURSOR` in the settings), so a restart reads no row
the cursor already passed, and `window` answers a read from the stored results with no signal read for a session that
lies inside the window. The folds and the analytics answers are one derived family, `FAMILY`, folded under one `stamp`: a change to the
fold code, the task-key claims or the analytics config leaves the stored stamp unequal, and the next `catch_up` drops
the family's rows and folds every session again, outside any request.
"""

import bisect
import dataclasses
import json
import logging
import math
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, bindparam, delete, func, insert, literal_column, select, text

import starpulse.contracts.signals as signal_contract
import starpulse.flow_metrics.model as model
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import Signal
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.table_registry import clear_stamp, definition, is_stamped, stamp_of, write_stamp
from starpulse.event_log.tables import analytics_answers, settings, signal_folds, signals
from starpulse.event_log.wake import StopEvent
from starpulse.flow_metrics.model import cells, flow, session_health, spend, steps, traces
from starpulse.harness_telemetry.adapters.inbound.telemetry import stored_signal
from starpulse.views.adapters.outbound import skill_cost

__all__ = ["CURSOR", "FAMILY", "VIEWS", "SignalFolds", "changed", "stamp"]

log = logging.getLogger(__name__)

#: The family of `starpulse.event_log.table_registry` the folds and the answers belong to.
FAMILY = "signals"

#: The settings key holding the highest `starpulse_signals` rowid every session at or below it has been folded past.
CURSOR = "signal_folds_cursor"

Fold = Callable[[list[Signal], TaskKeys | None, Analytics | None], Any]
#: Each stored view and the fold that makes its result. Read at call time, so a test can swap one.
VIEWS: dict[str, Fold] = {
    "health": session_health.fold_health,
    "steps": steps.fold_steps,
    "cost": cells.fold_cost,
    "runs": flow.fold_runs,
    "cases": traces.fold_cases,
    "trace_cases": traces.fold_trace_cases,
    "spend": spend.fold_spend,
}


def canonical(value: Any) -> Any:
    """`value` as JSON data that is the same for equal config: sets sorted, patterns as their source and flags."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: canonical(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, re.Pattern):
        return [value.pattern, value.flags]
    if isinstance(value, Mapping):
        return {str(k): canonical(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (set, frozenset)):
        return sorted((canonical(item) for item in value), key=json.dumps)
    if isinstance(value, (list, tuple)):
        return [canonical(item) for item in value]
    return value


def stamp(keys: TaskKeys | None, analytics: Analytics | None) -> str:
    """The stamp the signal folds and answers are valid under: their table definitions, the model sources and the
    signal contract, the task keys, the analytics config and the views kept."""
    sources = sorted(Path(model.__file__).parent.glob("*.py")) + [Path(signal_contract.__file__)]
    return stamp_of(
        definition([signal_folds, analytics_answers]),
        *(path.name + path.read_text() for path in sources),
        json.dumps([canonical(keys), canonical(analytics)], sort_keys=True, default=str),
        json.dumps(sorted(VIEWS)),  # a view added or dropped refolds every session for it
    )


_WINDOW = text(
    "SELECT view, harness, session, first_at, result FROM starpulse_signal_folds"
    " INDEXED BY ix_starpulse_signal_folds_last_at"  # SQLAlchemy's SQLite dialect renders no table hint
    " WHERE view IN :views AND last_at >= :floor ORDER BY first_at, harness, session"
).bindparams(bindparam("views", expanding=True)).columns(
    signal_folds.c.view, signal_folds.c.harness, signal_folds.c.session, signal_folds.c.first_at, signal_folds.c.result
)


def changed(events: EventLog, after: int, views: Iterable[str], since: float = 0.0) -> tuple[int, dict[str, list[Any]]]:
    """The per-session results of the `views` for each session folded past the rowid `after` and through the cursor
    (and with a signal at or after `since`), oldest first, with the cursor to pass as `after` next time.

    A session counts once its fold's rowid is at or below the cursor, which only moves past sessions that folded, so a
    mark taken from this never skips a session that a pass is still folding; a session that grew is folded again at a
    higher rowid and comes back. A refold under a new `stamp` lands at the same rowid, so a changed fold waits for the
    session's next signal."""
    through = events.setting(CURSOR) or 0
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


class SignalFolds:
    """Folds the signal table's sessions under one `keys` and `analytics`, and reads the folds back by window."""

    def __init__(
        self,
        events: EventLog,
        keys: TaskKeys | None,
        analytics: Analytics | None,
        completed: Callable[[list[dict[str, Any]]], None] | None = None,
        titled: Callable[[], Mapping[str, Mapping[str, Any]]] | None = None,
    ) -> None:
        self._completed = completed
        self._titled = titled  # the board's tasks; with it each fold adds its cost to the `skill_cost` series
        self._events = events
        self._engine = events.engine
        self._keys = keys
        self._analytics = analytics
        self.stamp = stamp(keys, analytics)

    def catch_up(self) -> int:
        """Fold what is new, or every session when the family's stamp changed, and return how many were folded.

        A session with a row above the cursor is folded from all its stored signals and replaces its fold rows. A
        stamp that differs from the stored one first drops the answers and rewinds the cursor, the old folds stay until
        each session is folded again, and the new stamp is kept once the pass has folded past every session. The
        cursor moves past every session that folded; a session whose fold raised is logged and left, and the cursor
        stops before its first new row so the next pass tries it again. Raises when the database does."""
        rebuilt = self._drop_changed()
        # a rebuild refolds history, which adds nothing to the skill series; the board is read once for the pass
        counting = None if rebuilt or self._titled is None else self._titled()
        folded = 0
        cursor = self._events.setting(CURSOR) or 0
        with self._engine.connect() as db:
            new = db.execute(
                select(
                    signals.c.harness,
                    signals.c.session,
                    func.min(literal_column("rowid")),
                    func.max(literal_column("rowid")),
                )
                .where(literal_column("rowid") > cursor)
                .group_by(signals.c.harness, signals.c.session)
                .order_by(func.min(literal_column("rowid")))
            ).all()
        reached = cursor
        failed: list[int] = []
        finished: set[str] = set()
        for harness, session, first_row, last_row in new:
            reached = max(reached, last_row)
            if not rebuilt and self._current(harness, session) >= last_row:
                continue
            before = self._completed_tasks(harness, session)
            if self._fold(harness, session, counting):
                folded += 1
                finished |= self._completed_tasks(harness, session) - before
            else:
                failed.append(first_row)
        if new:
            self._events.set_setting(CURSOR, min([reached, *(row - 1 for row in failed)]))
        if rebuilt:
            if not failed:  # a failed session keeps its old fold, so the next pass starts the rebuild again
                with self._engine.begin() as db:
                    write_stamp(db, FAMILY, self.stamp)
        elif finished and self._completed:
            held = session_health.combine_health(self.window(0.0, ("health",))["health"])
            self._completed([s for s in session_health.slice_health(held) if s["task"] in finished])
        if folded and counting is not None:
            self._events.put_state(skill_cost.STATE, skill_cost.exposition())
        return folded

    def _completed_tasks(self, harness: str, session: str) -> set[str]:
        """The tasks the session's stored `health` fold holds as completed; none before it is folded."""
        with self._engine.connect() as db:
            result = db.execute(
                select(signal_folds.c.result).where(
                    signal_folds.c.view == "health", signal_folds.c.harness == harness, signal_folds.c.session == session
                )
            ).scalar()
        return {row["task"] for row in result or () if row["complete"]}

    def window(self, since: float, views: Iterable[str] = tuple(VIEWS)) -> dict[str, list[Any]]:
        """The per-session results of the `views` for the sessions that have a signal at or after `since`, oldest
        first, to combine; no other view's rows are read. A session that began before `since` is folded again from its
        signals inside the window. The read names the `last_at` index: left to itself SQLite walks the whole primary-key
        range of each view (every session ever folded) to test `last_at`, seconds for the `steps` view."""
        wanted = tuple(views)
        with self._engine.connect() as db:
            rows = db.execute(_WINDOW, {"views": wanted, "floor": since}).all()
        answer: dict[str, list[Any]] = {view: [] for view in wanted}
        began = {(row.harness, row.session): row.first_at for row in rows}
        found = {
            key: self._load(*key, since)[1] for key, first_at in began.items() if first_at < since
        }
        for row in rows:
            signals_in_window = found.get((row.harness, row.session))
            if signals_in_window:
                answer[row.view].append(VIEWS[row.view](signals_in_window, self._keys, self._analytics))
            else:
                answer[row.view].append(row.result)
        return answer

    def step_window(self, since: float, after: float | None, wanted: int) -> dict[str, list[Any]]:
        """The `steps` results of the sessions that can hold the `wanted` oldest steps after the time `after` (none: from
        `since`), sessions read by when they began and the read stopped once a step before the next session's start
        is past `wanted` of them, so a page costs its own sessions and not the window's. A session that ended before
        `after` is skipped; one that began before `since` keeps the steps of its stored fold from `since` on."""
        floor = since if after is None else max(since, after)
        times: list[float] = []  # the times, sorted, of the steps read after `after`, to tell when a page is complete
        folds: list[Any] = []
        with self._engine.connect() as db:
            rows = db.execute(_WINDOW, {"views": ("steps",), "floor": floor})
            for row in rows:
                ahead = bisect.bisect_left(times, row.first_at)
                if ahead > wanted and times[wanted] > times[wanted - 1]:
                    break  # every later session's steps come after these, so the page is among them
                result = row.result
                if row.first_at < since:
                    result = [step for step in result if step["at"] >= since]
                folds.append(result)
                for step in result:
                    if after is None or step["at"] > after:
                        bisect.insort(times, step["at"])
        return {"steps": folds}

    def oldest(self) -> float | None:
        """The time of the oldest folded signal, None when nothing is folded: the history the views can answer. It
        reads the fold rows, so it holds with the signals table empty."""
        with self._engine.connect() as db:
            return db.execute(select(func.min(signal_folds.c.first_at))).scalar_one()

    def sessions(self, since: float = 0.0) -> Iterator[list[Signal]]:
        """The signals at or after `since` of each session that has one, a session at a time, oldest first, so a
        caller holds one session's signals at once."""
        with self._engine.connect() as db:
            keys = db.execute(
                select(signals.c.harness, signals.c.session)
                .where(signals.c.time >= since)
                .group_by(signals.c.harness, signals.c.session)
                .order_by(func.min(signals.c.time), signals.c.harness, signals.c.session)
            ).all()
        for harness, session in keys:
            yield self._load(harness, session, since)[1]

    def follow(self, stop: StopEvent) -> None:
        """Run `catch_up` after each append or another process's commit until `stop` is set."""
        self._events.run_on_wake(stop, self.catch_up, "signal fold catch-up failed")

    def _current(self, harness: str, session: str) -> int:
        """The rowid every view of the session is folded through, 0 when one is missing."""
        with self._engine.connect() as db:
            through = db.execute(
                select(func.min(signal_folds.c.folded_through), func.count())
                .where(
                    signal_folds.c.harness == harness,
                    signal_folds.c.session == session,
                )
            ).one()
        return through[0] if through[1] == len(VIEWS) else 0

    def _drop_changed(self) -> bool:
        """Drop the answers and rewind the cursor when the folds were not folded under this stamp; whether it did. The
        folds stay, each replaced as its session is refolded, so a read during the pass still answers every session.
        The stamp goes first, so a pass that stops partway is not taken for a finished one."""
        with self._engine.connect() as db:
            if is_stamped(db, FAMILY, self.stamp):
                return False
        with self._engine.begin() as db:
            clear_stamp(db, FAMILY)
            db.execute(delete(analytics_answers))
            db.execute(delete(settings).where(settings.c.key == CURSOR))
        return True

    def _load(self, harness: str, session: str, since: float = -math.inf) -> tuple[int, list[Signal]]:
        """The highest rowid and the signals of one session at or after `since`, oldest first; a field a row stores as
        null is absent, as the decoder expects."""
        with self._engine.connect() as db:
            rows = db.execute(
                select(literal_column("rowid"), signals.c.fields)
                .where(signals.c.harness == harness, signals.c.session == session, signals.c.time >= since)
                .order_by(signals.c.time)
            ).all()
        found = [stored_signal({k: v for k, v in row[1].items() if v is not None}) for row in rows]
        return max((row[0] for row in rows), default=0), found

    def _fold(
        self,
        harness: str,
        session: str,
        tasks: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> bool:
        """Replace the session's fold rows with a fold of its stored signals; False when a fold raised, and the old
        rows stay. A session with no signal left loses its rows."""
        through, found = self._load(harness, session)
        try:
            results = {view: fold(found, self._keys, self._analytics) for view, fold in VIEWS.items()} if found else {}
            stored = {view: json.loads(json.dumps(result)) for view, result in results.items()}
        except Exception:
            log.exception("fold of %s session %s failed", harness, session)
            return False
        first_at = min((s.time for s in found), default=0.0)
        last_at = max((s.time for s in found), default=0.0)
        rows = [
            {
                "view": view,
                "harness": harness,
                "session": session,
                "first_at": first_at,
                "last_at": last_at,
                "folded_through": through,
                "result": result,
            }
            for view, result in stored.items()
        ]
        with self._engine.begin() as db:
            before = self._stored_cost(db, harness, session) if tasks is not None else []
            db.execute(delete(signal_folds).where(signal_folds.c.harness == harness, signal_folds.c.session == session))
            if rows:
                db.execute(insert(signal_folds), rows)
        if tasks is not None and "cost" in stored:
            skill_cost.add(cells.cost_increase(before, stored["cost"], tasks))
        return bool(rows)

    @staticmethod
    def _stored_cost(db: Connection, harness: str, session: str) -> list[dict[str, Any]]:
        row = db.execute(
            select(signal_folds.c.result).where(
                signal_folds.c.harness == harness, signal_folds.c.session == session, signal_folds.c.view == "cost"
            )
        ).first()
        return row[0] if row else []
