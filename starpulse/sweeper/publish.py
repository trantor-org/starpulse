"""The sweeper's metrics across the event log: the worker keeps its exposition, the Page API relays it on `/metrics`."""

import logging
from collections.abc import Callable

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.kept_text import kept_text

logger = logging.getLogger(__name__)

METRICS = "sweeper.metrics"


def publish_metrics(log: EventLog, text: str) -> None:
    """Keep the worker's exposition `text` for the Page API to relay; a log that cannot be written is logged."""
    try:
        log.put_state(METRICS, text)
    except Exception:
        logger.warning("sweeper: the metrics were not kept", exc_info=True)


def metrics_of(log: EventLog) -> Callable[[], str]:
    """The worker's metrics text as last kept; empty before it kept any or when the log cannot be read."""
    return kept_text(log, METRICS)
