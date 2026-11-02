"""The Board's snapshot, taken and encoded for the request that asks for it.

The read model is queried for each snapshot (the StarPulse Answers Board Reads From SQLite per Request ADR), and a
snapshot costs more than the 50 ms a request may take, so the API child holds the one newest encoded snapshot
(`refresh_s` > 0): a request serves it while it is current, and a warmer thread rebuilds it off the request path. An
event stream that sends its snapshot by reference (`ref /api/events/body/<key>`) holds the body only until the page
fetches it or the stream ends.
"""

import hashlib
import itertools
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from starpulse.board.board_feed import BoardFeed
from starpulse.views.adapters.inbound.compression import Encoded
from starpulse.views.model.encoding import encode_snapshot

logger = logging.getLogger(__name__)

#: The longest (seconds) a warm snapshot is served while the feed has not changed.
IDLE_REFRESH_S = 30.0


class Served(NamedTuple):
    #: The feed revision the snapshot was taken at.
    rev: int
    #: The publish count the snapshot was taken at.
    sent: int
    snapshot: dict[str, Any]


class _Warm(NamedTuple):
    """The newest snapshot built, its body and when (the clock's seconds) it was built."""

    at: float
    served: Served
    encoded: Encoded


class Snapshots:
    def __init__(self, feed: BoardFeed, refresh_s: float = 0.0, clock: Callable[[], float] = time.monotonic) -> None:
        self._feed = feed
        self._lock = threading.Lock()
        #: The bodies event streams sent by reference and pages have not fetched yet, by key.
        self._refs: dict[str, Encoded] = {}
        #: How many snapshots were encoded and the seconds taking and encoding them took, for `metrics`.
        self._builds = 0
        self._build_s = 0.0
        self._refresh_s = refresh_s
        self._clock = clock
        #: The newest snapshot built, when `refresh_s` > 0; builds run one at a time under `_building`.
        self._warm: _Warm | None = None
        self._building = threading.Lock()
        self._keys = itertools.count()

    @property
    def rev(self) -> int:
        return self._feed.rev

    def take(self) -> Served:
        """The snapshot as of now, unencoded."""
        return Served(*self._feed.snapshot_at())

    @property
    def held_rev(self) -> int | None:
        """The feed revision of the warm snapshot, None before the first build."""
        warm = self._warm
        return None if warm is None else warm.served.rev

    def build(self) -> tuple[Served, Encoded]:
        """The snapshot with its body and gzip: the warm one while it is current, else one built now."""
        if self._refresh_s <= 0:
            return self._encode()
        if (warm := self._current()) is None:
            with self._building:  # requests that find it stale wait for one build and share it
                if (warm := self._current()) is None:
                    warm = self._store()
        return warm.served, warm.encoded

    def refresh(self) -> None:
        """Rebuild the warm snapshot unless the feed is unchanged since it and it is younger than `IDLE_REFRESH_S`."""
        with self._building:
            warm = self._warm
            if warm is None or warm.served.rev != self._feed.rev or self._clock() - warm.at >= IDLE_REFRESH_S:
                self._store()

    def keep_warm(self, stop: threading.Event) -> None:
        """Run `refresh` every `refresh_s` until `stop`: the warm snapshot trails the feed by about that long."""
        while not stop.wait(self._refresh_s):
            try:
                self.refresh()
            except Exception:
                logger.exception("StarPulse: the warm snapshot could not be rebuilt")

    def _current(self) -> _Warm | None:
        """The warm snapshot if it is unchanged since the feed's last publish and under `IDLE_REFRESH_S` old, or
        under two refreshes old (the warmer is about to replace it)."""
        warm = self._warm
        if warm is None:
            return None
        age = self._clock() - warm.at
        if age <= 2 * self._refresh_s or (warm.served.rev == self._feed.rev and age < IDLE_REFRESH_S):
            return warm
        return None

    def _store(self) -> _Warm:
        taken = self._clock()
        served, encoded = self._encode()
        self._warm = warm = _Warm(taken, served, encoded)
        return warm

    def _encode(self) -> tuple[Served, Encoded]:
        started = time.perf_counter()
        served = self.take()
        encoded = Encoded.of(encode_snapshot(served.snapshot, {}))
        with self._lock:
            self._builds += 1
            self._build_s += time.perf_counter() - started
        return served, encoded

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
        """`starpulse_snapshot_build_seconds`, the count and total time of the builds so far, as Prometheus text."""
        name = "starpulse_snapshot_build_seconds"
        return (
            f"# HELP {name} Seconds spent taking and encoding the snapshot.\n# TYPE {name} summary\n"
            f"{name}_count {self._builds}\n{name}_sum {self._build_s}\n"
        )
