"""How long the history recorder's oldest unrecorded entry of each stream has waited, for `/metrics`.

The recorder (`record_machine_events` and its two siblings) copies the log into the history store and saves a cursor
with each row. A recorder that stopped leaves its cursor behind the log's newest entry of the stream and every
history-derived answer (`starpulse task trace`, the qa guard) empty, with nothing else failing; this gauge is the
one place the gap shows.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select

from starpulse.event_log import breaking_change_events, events, verdict_events
from starpulse.event_log.checkpoints import Checkpoints
from starpulse.event_log.event_log import EventLog
from starpulse.event_log.tables import events as log_entries

STREAMS = (events.STREAM, verdict_events.STREAM, breaking_change_events.STREAM)

logger = logging.getLogger(__name__)


def metrics_of(log: EventLog, clock: Callable[[], float] = time.time) -> Callable[[], str]:
    """`starpulse_history_recorder_lag_seconds{stream}`: seconds since `stream`'s oldest entry past the recorder's
    cursor was appended, 0 when the recorder is caught up. Empty text when the log cannot be read."""
    checkpoints = Checkpoints(log.engine)

    def read() -> str:
        registry = CollectorRegistry()
        lag = Gauge(
            "starpulse_history_recorder_lag_seconds",
            "Seconds the oldest log entry the history recorder has not yet copied has waited, by stream",
            ["stream"],
            registry=registry,
        )
        now = clock()
        try:
            for stream in STREAMS:
                after = checkpoints.load(stream)[0] or 0
                with log.engine.connect() as db:
                    oldest = db.execute(
                        select(func.min(log_entries.c.at)).where(log_entries.c.stream == stream, log_entries.c.id > after)
                    ).scalar()
                lag.labels(stream).set(0.0 if oldest is None else max(now - oldest, 0.0))
        except Exception:
            logger.warning("history recorder lag was not read", exc_info=True)
            return ""
        return generate_latest(registry).decode()

    return read
