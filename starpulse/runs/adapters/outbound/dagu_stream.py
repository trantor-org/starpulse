"""Dagu's server-sent event stream: a `message` event each time a run changes, which the Dagu adapter answers by listing.

The stream opens with a `message` carrying every run, so each connection starts with a listing, and Dagu sends a
heartbeat every 10 seconds, so a read that waits `READ_TIMEOUT` seconds is a connection that died.
"""

from __future__ import annotations

import threading
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator

from starpulse.event_log.wake import StopEvent

TOPIC = "dagruns:all"
READ_TIMEOUT = 30.0
#: Seconds to wait before opening a dropped stream again, so a Dagu that is down is not asked in a tight loop.
RETRY = 5.0


def changes(lines: Iterable[str]) -> Iterator[None]:
    """One item for each `message` event of a stream's lines; its control events and heartbeats are not changes."""
    event = None
    for line in lines:
        if line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        elif not line.strip():
            if event == "message":
                yield
            event = None


def _lines(url: str) -> Iterator[str]:  # pragma: no mutate block — HTTP boundary
    with urllib.request.urlopen(url, timeout=READ_TIMEOUT) as response:
        for raw in response:
            yield raw.decode()


def follow_stream(
    url: str,
    on_change: Callable[[], None],
    stop: StopEvent,
    lines: Callable[[str], Iterable[str]] = _lines,
    retry: float = RETRY,
) -> None:
    """Call `on_change` for each change the Dagu at `url` streams, on a thread until `stop`; a dropped stream is opened again."""
    stream_url = f"{url.rstrip('/')}/api/v1/events/stream?{urllib.parse.urlencode({'topics': TOPIC})}"

    def run() -> None:
        while not stop.is_set():
            try:
                for _ in changes(lines(stream_url)):
                    on_change()
                    if stop.is_set():
                        return
            except (OSError, ValueError):
                pass
            stop.wait(retry)

    threading.Thread(target=run, name="dagu-runs-stream", daemon=True).start()
