"""The Board's snapshot as the Board writer stored it, and the deltas the writer stored after it.

The API builds no snapshot (the StarPulse API Worker Only Serves ADR): a request serves the stored body, and a stream
attaches at the sequence the body reflects and takes the rows past it. One thread wakes with the event log, reads the
rows the writer added, and puts them on the streams open.
"""

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.signals import DELTAS
from starpulse.event_log.readmodel.snapshot_store import LIVE, SnapshotStore
from starpulse.event_log.wake import StopEvent
from starpulse.views.adapters.inbound.compression import Encoded
from starpulse.views.adapters.outbound import request_durations

logger = logging.getLogger(__name__)


class NotStored(Exception):
    """The Board writer has stored no snapshot yet."""


class Served(NamedTuple):
    #: The sequence of the last delta the snapshot reflects.
    seq: int
    snapshot: dict[str, Any]


class Snapshots:
    def __init__(self, store: SnapshotStore, log: EventLog, stop: StopEvent) -> None:
        self._store = store
        #: Whether the writer beside this feed has folded what the feed published, within the seconds given; true when
        #: another process writes the snapshot.
        self.caught_up: Callable[[float], bool] = lambda _timeout: True
        self._lock = threading.Lock()
        #: The body `take` last decoded and what it decoded to, under `_taking`; a body stored again at an unmoved
        #: sequence is another `Encoded`.
        self._taken: tuple[Encoded, Served] | None = None
        self._taking = threading.Lock()
        #: The body last read of each view (`LIVE` is the snapshot's), with the stamp and sequence it was stored at; a
        #: newer stamp replaces it.
        self._bodies: dict[str, tuple[tuple[int, float], int, Encoded]] = {}
        #: The newest delta put on the streams, and the queue of each stream open.
        self._head = store.head()
        self._streams: list[queue.Queue] = []
        #: The threads that read the log until `stop`, for an owner that closes the log to join first.
        self.readers = [
            threading.Thread(
                target=log.run_on_wake,
                args=(stop, self._advance, "StarPulse: the stored deltas could not be read", DELTAS),
                name="snapshot-deltas",
                daemon=True,
            )
        ]
        self.readers[0].start()

    def stored(self, view: str = LIVE) -> tuple[int, Encoded]:
        """The sequence and body, with its gzip, the writer stored for `view`: `LIVE`, the one body the page, `?view=full`,
        `/api/flows` and the agent CLI read, or a body made outside the folds (`pulls`); the body is read from the
        store only when it was stored again."""
        stamp = self._store.stamp(view)
        if stamp is None:
            raise NotStored
        with self._lock:
            held = self._bodies.get(view)
        if held is not None and held[0] == stamp:
            return held[1], held[2]
        if (row := self._store.body(view)) is None:
            raise NotStored(view)
        encoded = Encoded(row[1], row[2])
        with self._lock:
            self._bodies[view] = (stamp, row[0], encoded)
        return row[0], encoded

    def flows(self) -> Encoded:
        """The `/api/flows` body, the one the writer stored, which the agent CLI reads about once a second: no read decodes
        or encodes the snapshot. The seconds the read took are observed by whether it fetched a newly stored body."""
        started = time.monotonic()
        held = self._bodies.get(LIVE)
        body = self.stored()[1]
        source = "cached" if held is not None and held[2] is body else "rebuild"
        request_durations.observe_flows(source, time.monotonic() - started)
        return body

    def take(self) -> Served:
        """The stored snapshot as a dict, decoded once per stored body however many streams and requests read it."""
        seq, encoded = self.stored()
        with self._taking:
            if self._taken is None or self._taken[0] is not encoded:
                self._taken = encoded, Served(seq, json.loads(encoded.body))
            return self._taken[1]

    def _advance(self) -> None:
        with self._lock:
            self._put()

    def _put(self) -> None:
        """Put the deltas the writer stored since the last on every stream open; under `_lock`. A store whose deltas were
        renumbered below this feed's head (a read model rebuilt under a running API) restarts the head at its own, and
        ends every stream open with a `None`: it holds a body the new numbering never reached, so its page reattaches."""
        if not (deltas := self._store.since(self._head)) and (head := self._store.head()) < self._head:
            self._head = head
            for stream in self._streams:
                stream.put(None)
        for seq, kind, data in deltas:
            self._head = seq
            for stream in self._streams:
                stream.put((kind, data))

    def position(self) -> int:
        """The sequence of the newest stored delta: a read made after this call reflects every change up to it."""
        return self._store.head()

    def watch_from(self, seq: int) -> tuple[list[tuple[str, dict]], queue.Queue] | None:
        """The deltas after `seq`, and the queue of every delta after those; None when the store no longer holds them
        all, and the caller reads a fresh snapshot."""
        with self._lock:
            self._put()  # what the thread has not put on the streams yet
            missed = [(kind, data) for number, kind, data in self._store.since(seq) if number <= self._head]
            if seq > self._head or len(missed) != self._head - seq:
                return None
            stream: queue.Queue = queue.Queue()
            self._streams.append(stream)
            return missed, stream

    def unsubscribe(self, stream: queue.Queue) -> None:
        with self._lock:
            self._streams.remove(stream)

    def announce(self, kind: str, data: dict, wait_s: float = 1.0) -> None:
        """Give every open stream one event outside the stored deltas, and wait up to `wait_s` for each stream to have
        written it. A page that connects afterwards never sees it: it is about the process, not the Board.

        A stream marks each item it took off its queue with `task_done`; the wait is for those marks.
        """
        with self._lock:
            streams = list(self._streams)
        for stream in streams:
            stream.put((kind, data))
        deadline = time.monotonic() + wait_s
        for stream in streams:
            while stream.unfinished_tasks and time.monotonic() < deadline:
                # adr-exempt: pending
                time.sleep(0.005)

    def metrics(self) -> str:
        """`starpulse_snapshot_build_seconds`, the count and total time of the builds so far, as Prometheus text: the API
        builds none, and the series stays so the bench and its dashboards read 0."""
        name = "starpulse_snapshot_build_seconds"
        return f"# HELP {name} Seconds spent taking and encoding the snapshot.\n# TYPE {name} summary\n{name}_count 0\n{name}_sum 0\n"
