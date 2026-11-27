"""The sessions' folds as the event log keeps them: `starpulse_signal_folds`, advanced one export at a time.

A session has four rows there: its `ledger` (`flow_metrics.model.ledger`'s state, the one the next export reads) and the
`steps`, `cost` and `spend` results the views combine, rewritten together with each export that touches it. Each
rewrite carries a new revision in `folded_through`, taken from one counter in the settings under the same write lock
(`BEGIN IMMEDIATE`, which also orders two receivers that name one session), so a reader holding the revision it last saw
finds every session an export advanced since.

The same write stores the Trace of each case the export ended (`flow_metrics.model.traces`) and keeps the case still
open in the `ledger` row, so `close` writes it, marked unfinished, when its session ends.
"""

import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.dialects import sqlite
from sqlalchemy.exc import SQLAlchemyError

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import Signal
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import settings, signal_folds
from starpulse.flow_metrics.adapters.outbound import traces
from starpulse.flow_metrics.model import ledger
from starpulse.flow_metrics.model.traces import cases_of

__all__ = ["LEDGER", "REVISION", "VIEWS", "SessionLedger"]

log = logging.getLogger(__name__)

#: The settings key counting the writes of `starpulse_signal_folds`; the highest `folded_through` of any row.
REVISION = "signal_folds_revision"
#: The view that holds a session's ledger state, and the views its results are kept under.
LEDGER = "ledger"
VIEWS = ("steps", "cost", "spend")


class SessionLedger:
    """Advances the folds of the sessions an export names, under one `keys` and `analytics`."""

    def __init__(self, events: EventLog, keys: TaskKeys | None, analytics: Analytics | None) -> None:
        self._engine = events.engine
        self._keys = keys
        self._analytics = analytics

    def apply(self, found: Iterable[Signal]) -> None:
        """Fold `found` into the folds of each session it names. A session whose fold raises is logged and keeps its
        stored folds; a database error raises."""
        sessions: dict[tuple[str, str], list[Signal]] = defaultdict(list)
        for signal in found:
            sessions[signal.harness, signal.session].append(signal)
        for (harness, session), batch in sessions.items():
            try:
                self._advance(harness, session, batch)
            except SQLAlchemyError:
                raise
            except Exception:
                log.exception("fold of %s session %s failed", harness, session)

    def last_claim(self, harness: str, session: str) -> tuple[str, float] | None:
        """The task the session last claimed and when, from its stored ledger, or None when it claimed none. Raises
        when the database does."""
        with self._engine.connect() as db:
            state = db.execute(
                select(signal_folds.c.result).where(
                    signal_folds.c.view == LEDGER, signal_folds.c.harness == harness, signal_folds.c.session == session
                )
            ).scalar()
        return ledger.last_claim(state)

    def close(self, harness: str, session: str) -> None:
        """Store the case the session left open as an unfinished Trace. Raises when the database does."""
        with self._engine.connect() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")
            traces.close(db, harness, session)
            db.commit()

    def _advance(self, harness: str, session: str, batch: list[Signal]) -> None:
        with self._engine.connect() as db:
            db.exec_driver_sql("BEGIN IMMEDIATE")  # the read below and the write after it are one step of the session
            held = db.execute(
                select(signal_folds.c.first_at, signal_folds.c.last_at, signal_folds.c.result).where(
                    signal_folds.c.view == LEDGER, signal_folds.c.harness == harness, signal_folds.c.session == session
                )
            ).first()
            folded = ledger.apply(held.result if held else None, batch, self._keys, self._analytics)
            ended = cases_of(folded.rows)
            current = ended.pop() if ended else None
            traces.write(db, harness, session, ended, unfinished=False)
            results: dict[str, Any] = {
                LEDGER: {**folded.state, "open_case": current},
                "steps": ledger.steps_of(folded.rows),
                "cost": ledger.cost_of(folded.rows),
                "spend": ledger.spend_of(folded, harness, session),
            }
            times = [s.time for s in batch]
            first_at = min([*times, held.first_at] if held else times)
            last_at = max([*times, held.last_at] if held else times)
            revision = (db.execute(select(settings.c.value).where(settings.c.key == REVISION)).scalar() or 0) + 1
            counter = sqlite.insert(settings).values(key=REVISION, value=revision, updated_at=time.time())
            db.execute(
                counter.on_conflict_do_update(
                    index_elements=[settings.c.key],
                    set_={"value": counter.excluded.value, "updated_at": counter.excluded.updated_at},
                )
            )
            db.execute(
                delete(signal_folds).where(
                    signal_folds.c.view.in_(results),
                    signal_folds.c.harness == harness,
                    signal_folds.c.session == session,
                )
            )
            db.execute(
                insert(signal_folds),
                [
                    {
                        "view": view,
                        "harness": harness,
                        "session": session,
                        "first_at": first_at,
                        "last_at": last_at,
                        "folded_through": revision,
                        "result": result,
                    }
                    for view, result in results.items()
                ],
            )
            db.commit()
