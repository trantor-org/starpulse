"""The analytics views' per-session folds, kept in `starpulse_signal_folds` and advanced from a rowid cursor.

A fold of one harness session is a plain-JSON result (`fold_health` and its siblings). `catch_up` folds only the
sessions with `starpulse_signals` rows above the stored cursor (`CURSOR` in the settings), so a restart reads no row
the cursor already passed, and `window` answers a read from the stored results with no signal read for a session that
lies inside the window. A row carries the `basis` it was folded under: a change to the fold code, the task-key claims
or the analytics config makes the row stale, and the next `catch_up` folds it again, outside any request.
"""

import dataclasses
import hashlib
import json
import logging
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sqlalchemy import delete, func, insert, literal_column, select

import starpulse.contracts.signals as signal_contract
import starpulse.flow_metrics.model as model
from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import Signal
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import signal_folds, signals
from starpulse.flow_metrics.model import cells, flow, session_health, steps
from starpulse.harness_telemetry.adapters.inbound.telemetry import stored_signal

__all__ = ["CURSOR", "VIEWS", "SignalFolds", "basis"]

log = logging.getLogger(__name__)

#: The settings key holding the highest `starpulse_signals` rowid every session at or below it has been folded past.
CURSOR = "signal_folds_cursor"

Fold = Callable[[list[Signal], TaskKeys | None, Analytics | None], Any]
#: Each stored view and the fold that makes its result. Read at call time, so a test can swap one.
VIEWS: dict[str, Fold] = {
    "health": session_health.fold_health,
    "steps": steps.fold_steps,
    "cost": cells.fold_cost,
    "runs": flow.fold_runs,
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


def basis(keys: TaskKeys | None, analytics: Analytics | None) -> str:
    """The fingerprint a fold row is valid under: the model sources and the signal contract, the task keys and the
    analytics config."""
    digest = hashlib.sha256()
    for path in sorted(Path(model.__file__).parent.glob("*.py")) + [Path(signal_contract.__file__)]:
        digest.update(path.name.encode() + path.read_bytes())
    digest.update(json.dumps([canonical(keys), canonical(analytics)], sort_keys=True, default=str).encode())
    return digest.hexdigest()


class SignalFolds:
    """Folds the signal table's sessions under one `keys` and `analytics`, and reads the folds back by window."""

    def __init__(self, events: EventLog, keys: TaskKeys | None, analytics: Analytics | None) -> None:
        self._events = events
        self._engine = events.engine
        self._keys = keys
        self._analytics = analytics
        self.basis = basis(keys, analytics)

    def catch_up(self) -> int:
        """Fold what is new or stale and return how many sessions were folded.

        A session with a row above the cursor, and one folded under an older basis, is folded from all its stored
        signals and replaces its fold rows. The cursor moves past every session that folded; a session whose fold
        raised is logged and left, and the cursor stops before its first new row so the next pass tries it again.
        Raises when the database does."""
        folded = self._refold_stale()
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
        for harness, session, first_row, last_row in new:
            reached = max(reached, last_row)
            if self._current(harness, session) >= last_row:
                continue
            if self._fold(harness, session):
                folded += 1
            else:
                failed.append(first_row)
        if new:
            self._events.set_setting(CURSOR, min([reached, *(row - 1 for row in failed)]))
        return folded

    def window(self, since: float) -> dict[str, list[Any]]:
        """Each view's per-session results for the sessions that have a signal at or after `since`, oldest first, to
        combine. A session that began before `since` is folded again from its signals inside the window."""
        with self._engine.connect() as db:
            rows = db.execute(
                select(
                    signal_folds.c.view,
                    signal_folds.c.harness,
                    signal_folds.c.session,
                    signal_folds.c.first_at,
                    signal_folds.c.result,
                )
                .where(signal_folds.c.basis == self.basis, signal_folds.c.last_at >= since)
                .order_by(signal_folds.c.first_at, signal_folds.c.harness, signal_folds.c.session)
            ).all()
        answer: dict[str, list[Any]] = {view: [] for view in VIEWS}
        began = {(row.harness, row.session): row.first_at for row in rows}
        partial = [key for key, first_at in began.items() if first_at < since]
        for row in rows:
            if began[row.harness, row.session] >= since:
                answer[row.view].append(row.result)
        for harness, session in partial:
            found = self._load(harness, session, since)[1]
            for view, fold in VIEWS.items():
                answer[view].append(fold(found, self._keys, self._analytics))
        return answer

    def _current(self, harness: str, session: str) -> int:
        """The rowid every view of the session is folded through under the current basis, 0 when one is missing."""
        with self._engine.connect() as db:
            through = db.execute(
                select(func.min(signal_folds.c.folded_through), func.count())
                .where(
                    signal_folds.c.harness == harness,
                    signal_folds.c.session == session,
                    signal_folds.c.basis == self.basis,
                )
            ).one()
        return through[0] if through[1] == len(VIEWS) else 0

    def _refold_stale(self) -> int:
        with self._engine.connect() as db:
            stale = db.execute(
                select(signal_folds.c.harness, signal_folds.c.session)
                .where(signal_folds.c.basis != self.basis)
                .distinct()
            ).all()
        return sum(self._fold(harness, session) for harness, session in stale)

    def _load(self, harness: str, session: str, since: float = 0.0) -> tuple[int, list[Signal]]:
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

    def _fold(self, harness: str, session: str) -> bool:
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
                "basis": self.basis,
                "result": result,
            }
            for view, result in stored.items()
        ]
        with self._engine.begin() as db:
            db.execute(delete(signal_folds).where(signal_folds.c.harness == harness, signal_folds.c.session == session))
            if rows:
                db.execute(insert(signal_folds), rows)
        return bool(rows)
