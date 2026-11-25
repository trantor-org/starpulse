"""The events a Waiting task waits on: each machine event, as the subject the bridge publishes it on."""

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

from starpulse.event_log.events import STREAM as MACHINE_STREAM
from starpulse.event_log.wake import StopEvent

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog


def follow_until_events(
    seen: Callable[[str, str | None], None], subject_of: Callable[[Entry], str | None], log: EventLog, stop: StopEvent
) -> threading.Thread:
    """Call `seen` with the subject, and the `sha` its data names, of each machine event recorded after this call, within the event's own latency."""
    from starpulse.event_log.event_log import Tail  # the server imports no database stack until a store opens

    def handle(entry: Entry) -> None:
        if subject := subject_of(entry):
            seen(subject, (entry.fields.get("data") or {}).get("sha"))

    tail = Tail.live(log, MACHINE_STREAM, streams=[MACHINE_STREAM])
    thread = threading.Thread(target=tail.run, args=(handle, stop), name="board-until-events", daemon=True)
    thread.start()
    return thread
