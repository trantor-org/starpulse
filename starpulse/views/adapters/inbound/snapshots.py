"""The Board's snapshot, taken and encoded for the request that asks for it.

Nothing of it is held between requests (the StarPulse Answers Board Reads From SQLite per Request ADR): the feed queries
the read model's live set for each snapshot, and `/api/snapshot` encodes and gzips it per request. An event stream
that sends its snapshot by reference (`ref /api/events/body/<key>`) holds the body only until the page fetches it or
the stream ends.
"""

import hashlib
import threading
import time
from typing import Any, NamedTuple

from starpulse.board.board_feed import BoardFeed
from starpulse.views.adapters.inbound.compression import Encoded
from starpulse.views.model.encoding import encode_snapshot


class Served(NamedTuple):
    #: The feed revision the snapshot was taken at.
    rev: int
    #: The publish count the snapshot was taken at.
    sent: int
    snapshot: dict[str, Any]


class Snapshots:
    def __init__(self, feed: BoardFeed) -> None:
        self._feed = feed
        self._lock = threading.Lock()
        #: The bodies event streams sent by reference and pages have not fetched yet, by key.
        self._refs: dict[str, Encoded] = {}
        #: How many snapshots were encoded and the seconds taking and encoding them took, for `metrics`.
        self._builds = 0
        self._build_s = 0.0

    @property
    def rev(self) -> int:
        return self._feed.rev

    def take(self) -> Served:
        """The snapshot as of now, unencoded."""
        return Served(*self._feed.snapshot_at())

    def build(self) -> tuple[Served, Encoded]:
        """The snapshot as of now with its body and gzip."""
        started = time.perf_counter()
        served = self.take()
        encoded = Encoded.of(encode_snapshot(served.snapshot, {}))
        with self._lock:
            self._builds += 1
            self._build_s += time.perf_counter() - started
        return served, encoded

    def hold(self, encoded: Encoded) -> str:
        """Hold `encoded` for one fetch at `/api/events/body/<key>`, and return the key."""
        key = hashlib.sha1(encoded.body).hexdigest()
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
        """`starpulse_snapshot_build_seconds`, the count and total time of the builds so far, as Prometheus text."""
        name = "starpulse_snapshot_build_seconds"
        return (
            f"# HELP {name} Seconds spent taking and encoding the snapshot.\n# TYPE {name} summary\n"
            f"{name}_count {self._builds}\n{name}_sum {self._build_s}\n"
        )
