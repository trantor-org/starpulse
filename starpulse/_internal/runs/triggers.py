"""Start a declared run for each board event a `[[triggers]]` table matches.

One reader tails the streams the triggers name under one cursor, which the history store keeps (`CURSOR`), so a
restart resumes after the last entry handled and a trigger first started reads only what arrives after it. Each
entry is matched against every trigger of its stream and starts that trigger's workflow through the runs adapter's
`start`, at most once per entry id.

Delivery is at-least-once: a start whose cursor save then fails is read again, which the seen ids absorb, but a crash
between a start and its cursor save repeats that one start after the restart. A start the adapter refuses
(`StartFailedError`) is logged and dropped, not retried: an unreachable adapter would otherwise hold every later event.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from sqlalchemy.exc import OperationalError

from starpulse._internal.config.triggers import Trigger
from starpulse._internal.eventlog import events as machine_events
from starpulse._internal.eventlog import lane_events
from starpulse._internal.eventlog.event_log import DEFAULT_POLL_INTERVAL, Entry, Tail
from starpulse._internal.machines.machine_definition import field_matches
from starpulse.contracts.adapters import StartFailedError

if TYPE_CHECKING:
    from starpulse._internal.eventlog.event_log import EventLog
    from starpulse._internal.eventlog.history import HistoryStore

__all__ = ["CURSOR", "STREAMS", "run_triggers"]

logger = logging.getLogger(__name__)

#: The log stream each event a trigger names (`on`) is read from.
STREAMS = {"lane": lane_events.STREAM, "machine": machine_events.STREAM}

#: The name the reader's cursor is kept under in the history store.
CURSOR = "triggers"

#: How many (trigger, entry id) pairs are remembered to absorb an entry read twice.
_SEEN = 4096


def run_triggers(
    triggers: Sequence[Trigger],
    starts: Mapping[str, Callable[[str], str]],
    store: HistoryStore,
    log: EventLog,
    stop: threading.Event,
    *,
    interval: float = DEFAULT_POLL_INTERVAL,
) -> None:
    """Start the workflow of each trigger an entry of the log matches, until `stop`.

    `starts` maps a runs instance's name to its adapter's `start`. A store with no cursor takes its place at the
    log's head, so what the log retains from before is not replayed into runs.
    """
    while not stop.is_set():
        try:
            if (after := store.cursor(CURSOR)) is None:
                after = log.head() or 0
                store.save_cursor(CURSOR, after)
            break
        except OperationalError as exc:
            logger.warning("triggers: cannot read the %s cursor, retrying in %ss: %s", CURSOR, interval, exc)
            stop.wait(interval)
    else:
        return
    seen: dict[tuple[int, str], None] = {}

    def handle(entry: Entry) -> None:
        for at, trigger in enumerate(triggers):
            key = (at, entry.event_id)
            if STREAMS[trigger.on] != entry.stream or key in seen or not field_matches(trigger.when, entry.fields):
                continue
            seen[key] = None
            if len(seen) > _SEEN:
                del seen[next(iter(seen))]
            instance, _, workflow = trigger.start.partition("/")
            try:
                run = starts[instance](workflow)
            except StartFailedError as exc:
                logger.warning("triggers: %s was not started for %s: %s", trigger.start, entry.event_id, exc)
            else:
                logger.info("triggers: started %s (run %s) for %s", trigger.start, run, entry.event_id)
        store.save_cursor(CURSOR, entry.id)

    streams = sorted({STREAMS[trigger.on] for trigger in triggers})
    Tail(log, CURSOR, after=after, interval=interval, streams=streams).run(handle, stop, transient=(OperationalError,))
