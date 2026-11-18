"""The Board's snapshot as the Board writer stored it, and the deltas the writer stored after it.

The API builds no snapshot (the StarPulse API Worker Only Serves ADR): a request serves the stored body, and a stream
attaches at the sequence the body reflects and takes the rows past it. One thread wakes with the event log, reads the
rows the writer added, and puts them on the streams open. An event stream that sends its snapshot by reference
(`ref /api/events/body/<key>`) holds the body only until the page fetches it or the stream ends.
"""

import hashlib
import itertools
import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from starpulse.event_log.event_log import EventLog
from starpulse.event_log.readmodel.snapshot_store import SnapshotStore
from starpulse.event_log.wake import StopEvent
from starpulse.views.adapters.inbound.compression import Encoded
from starpulse.views.model.encoding import encode

logger = logging.getLogger(__name__)


class NotStored(Exception):
    """The Board writer has stored no snapshot yet."""


#: The snapshot's fields `/api/flows` keeps: what the agent CLI reads of the board, the runs and the cues.
FLOW_KEYS = ("flows", "roles", "settled", "cold_done", "pulls", "interactive", "ratings", "cues", "dags", "error")


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
        #: The bodies event streams sent by reference and pages have not fetched yet, by key.
        self._refs: dict[str, Encoded] = {}
        #: The `/api/flows` body and gzip made from one `take`, under `_flowing`.
        self._flows: tuple[Served, Encoded] | None = None
        self._flowing = threading.Lock()
        self._keys = itertools.count()
        #: The body last read of each view, with the stamp and sequence it was stored at; a newer stamp replaces it.
        self._bodies: dict[str, tuple[tuple[int, float], int, Encoded]] = {}
        #: The full body `take` last decoded and what it decoded to, under `_taking`; a body stored again at an unmoved
        #: sequence is another `Encoded`.
        self._taken: tuple[Encoded, Served] | None = None
        self._taking = threading.Lock()
        #: The newest delta put on the streams, and the queue of each stream open.
        self._head = store.head()
        self._streams: list[queue.Queue] = []
        #: The threads that read the log until `stop`, for an owner that closes the log to join first.
        self.readers = [
            threading.Thread(
                target=log.run_on_wake,
                args=(stop, self._advance, "StarPulse: the stored deltas could not be read"),
                name="snapshot-deltas",
                daemon=True,
            )
        ]
        self.readers[0].start()

    def stored(self, view: str = "slim") -> tuple[int, Encoded]:
        """The sequence and body the writer stored for `view` (`slim` is the page's, `full` is `?view=full`'s); the body
        is read from the store only when it was stored again."""
        stamp = self._store.stamp(view)
        if stamp is None:
            raise NotStored(view)
        with self._lock:
            held = self._bodies.get(view)
        if held is not None and held[0] == stamp:
            return held[1], held[2]
        if (row := self._store.body(view)) is None:
            raise NotStored(view)
        encoded = Encoded.of(row[1])
        with self._lock:
            self._bodies[view] = (stamp, row[0], encoded)
        return row[0], encoded

    def flows(self) -> Encoded:
        """The `/api/flows` body of the snapshot `take` returns, encoded and gzipped once however many requests ask: the
        agent CLI reads it about once a second."""
        served = self.take()
        with self._flowing:
            if self._flows is None or self._flows[0] is not served:
                body = encode("flows", {key: served.snapshot[key] for key in FLOW_KEYS if key in served.snapshot})
                self._flows = (served, Encoded.of(body))
            return self._flows[1]

    def take(self) -> Served:
        """The stored full snapshot as a dict, decoded once per stored body however many streams and requests read it."""
        seq, encoded = self.stored("full")
        with self._taking:
            if self._taken is None or self._taken[0] is not encoded:
                self._taken = encoded, Served(seq, json.loads(encoded.body))
            return self._taken[1]

    def _advance(self) -> None:
        with self._lock:
            self._put()

    def _put(self) -> None:
        """Put the deltas the writer stored since the last on every stream open; under `_lock`."""
        for seq, kind, data in self._store.since(self._head):
            self._head = seq
            for stream in self._streams:
                stream.put((kind, data))

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

    def hold(self, encoded: Encoded) -> str:
        """Hold `encoded` for one fetch at `/api/events/body/<key>`, and return the key."""
        key = hashlib.sha1(encoded.body + str(next(self._keys)).encode()).hexdigest()  # one per stream: bodies repeat
        with self._lock:
            self._refs[key] = encoded
        return key

    def body(self, key: str) -> Encoded | None:
        """The body held under `key`, released as it is read; None once read, released or never held."""
        with self._lock:
            return self._refs.pop(key, None)

    def release(self, key: str) -> None:
        """Drop the body held under `key`, when the stream that sent it ends before the page fetched it."""
        with self._lock:
            self._refs.pop(key, None)

    def metrics(self) -> str:
        """`starpulse_snapshot_build_seconds`, the count and total time of the builds so far, as Prometheus text: the API
        builds none, and the series stays so the bench and its dashboards read 0."""
        name = "starpulse_snapshot_build_seconds"
        return f"# HELP {name} Seconds spent taking and encoding the snapshot.\n# TYPE {name} summary\n{name}_count 0\n{name}_sum 0\n"
