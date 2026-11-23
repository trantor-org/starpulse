"""How long each log follower has trailed the log, for `/metrics`: `starpulse_follower_lag_seconds{follower}`.

The history recorder has its own gauge (`recorder_lag`). The bridge saves a cursor after each batch of acknowledged entries, so its
lag is read like the recorder's. The bridge's delivery and the holder-idle follower keep no cursor: each marks in the log's
state the moment it began to trail and clears the mark when it caught up, and the Page API reads the age of the mark. A
mark is written on a change only, never per entry.
"""

import logging
import time
from collections.abc import Callable, Sequence

from prometheus_client import CollectorRegistry, Gauge, generate_latest
from sqlalchemy import func, select

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.kept_text import kept_state
from starpulse.event_log.tables import events as log_entries

STATE = "follower.lag"
BRIDGE = "bridge"
DELIVERY = "bridge_delivery"
HOLDER_IDLE = "holder_idle"
MARKED = (DELIVERY, HOLDER_IDLE)

#: How old an entry is when a follower handles it for the follower to count as trailing.
GRACE = 60.0

logger = logging.getLogger(__name__)


class Behind:
    """One follower's mark: since when it has trailed the log, kept in the log's state while it does."""

    def __init__(self, log: EventLog, follower: str, clock: Callable[[], float] = time.time) -> None:
        self._log, self._follower, self._clock = log, follower, clock
        self._since: float | None = None
        self._kept = False  # whether this process wrote the mark: one a stopped process left is still in the log

    def since(self, at: float) -> None:
        """Mark the follower as trailing since `at`, unless it already is."""
        if self._since is None:
            self._keep(at)

    def caught_up(self) -> None:
        if self._since is not None or not self._kept:
            self._keep(None)

    def handled(self, appended: float) -> None:
        """Note an entry appended at `appended` that the follower now handles: an old one means it trails."""
        if self._clock() - appended > GRACE:
            self.since(appended)
        else:
            self.caught_up()

    def _keep(self, since: float | None) -> None:
        try:
            self._log.put_state_entry(STATE, self._follower, since)
        except Exception:
            logger.warning("follower lag: the mark of %s was not kept", self._follower, exc_info=True)
        else:
            self._since, self._kept = since, True


def metrics_of(
    log: EventLog, checkpoint: str, streams: Sequence[str], clock: Callable[[], float] = time.time
) -> Callable[[], str]:
    """`starpulse_follower_lag_seconds{follower}`: seconds the bridge's oldest entry in `streams` past its
    `checkpoint` has waited, and the age of each marked follower's mark; 0 when caught up. Empty text when the log
    cannot be read."""
    marks = kept_state(log, STATE)

    def read() -> str:
        registry = CollectorRegistry()
        lag = Gauge(
            "starpulse_follower_lag_seconds",
            "Seconds a log follower has trailed the log, by follower",
            ["follower"],
            registry=registry,
        )
        now = clock()
        try:
            after = log.checkpoints.load(checkpoint)[0] or 0
            with log.engine.connect() as db:
                oldest = db.execute(
                    select(func.min(log_entries.c.at)).where(
                        log_entries.c.stream.in_(streams), log_entries.c.id > after
                    )
                ).scalar()
            lag.labels(BRIDGE).set(0.0 if oldest is None else max(now - oldest, 0.0))
        except Exception:
            logger.warning("follower lag was not read", exc_info=True)
            return ""
        kept = marks()
        for follower in MARKED:
            since = kept.get(follower)
            lag.labels(follower).set(0.0 if since is None else max(now - since, 0.0))
        return generate_latest(registry).decode()

    return read
