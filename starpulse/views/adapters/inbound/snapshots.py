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
from starpulse.event_log.wake import StopEvent
from starpulse.views.adapters.inbound.compression import Encoded
from starpulse.views.model.encoding import encode, encode_snapshot, full_snapshot

logger = logging.getLogger(__name__)

#: The longest (seconds) a warm snapshot is served while the feed has not changed.
IDLE_REFRESH_S = 30.0

#: The warmer sleeps this many times as long as its last build took, so it holds at most a fifth of a core: on a host
#: past its CPU a build takes seconds, and rebuilding every `refresh_s` took a quarter of the API worker's CPU.
WARM_IDLE_PER_BUILD = 4.0


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
        #: The seconds between warm builds: `refresh_s`, or longer while a build takes longer than a fifth of it.
        self._interval_s = refresh_s
        self._clock = clock
        #: The newest snapshot built, when `refresh_s` > 0; builds run one at a time under `_building`.
        self._warm: _Warm | None = None
        self._building = threading.Lock()
        #: The newest `take`, when the clock's seconds it was taken, and the full body made from it; both under `_taking`.
        self._taken: tuple[float, Served] | None = None
        self._full: tuple[Served, bytes] | None = None
        #: Set by the first warm `full` read: the warmer then encodes the full body for each snapshot it builds.
        self._full_wanted = False
        #: When (the clock's seconds) the snapshot `_full` was made from was built.
        self._full_at = 0.0
        self._taking = threading.Lock()
        self._keys = itertools.count()

    @property
    def rev(self) -> int:
        return self._feed.rev

    def take(self) -> Served:
        """The snapshot as of now, unencoded: the one taken at this feed revision under `IDLE_REFRESH_S` ago, so
        callers that arrive together share one build rather than queue for the feed lock a build each."""
        if (held := self._held_take()) is not None:
            return held
        with self._taking:
            if (held := self._held_take()) is None:
                held = Served(*self._feed.snapshot_at())
                self._taken = (self._clock(), held)
            return held

    def full(self) -> bytes:
        """The body of `?view=full`, encoded once per snapshot however many requests ask. With a warmer the body is
        encoded off the request path with each warm build, and a request serves the newest one while it is current;
        only the first request, or one after the warmer stalls, encodes inline."""
        if self._refresh_s > 0:
            self._full_wanted = True
            if (held := self._held_full()) is not None:
                return held
            warm = self._current()
            if warm is not None:
                return self._encode_full(warm.served, warm.at)
        return self._encode_full(self.take(), self._clock())

    def _held_full(self) -> bytes | None:
        full = self._full
        if full is None:
            return None
        age = self._clock() - self._full_at
        if age <= 2 * self._interval_s or (full[0].rev == self._feed.rev and age < IDLE_REFRESH_S):
            return full[1]
        return None

    def _encode_full(self, served: Served, at: float) -> bytes:
        full = self._full
        if full is None or full[0] is not served:
            full = (served, encode("snapshot", full_snapshot(served.snapshot)))
            self._full, self._full_at = full, at
        return full[1]

    def _held_take(self) -> Served | None:
        taken = self._taken
        if taken is not None and taken[1].rev == self._feed.rev and self._clock() - taken[0] < IDLE_REFRESH_S:
            return taken[1]
        return None

    def build(self, fresh: bool = False) -> tuple[Served, Encoded]:
        """The snapshot with its body and gzip: the warm one while it is current, else one built now. `fresh` skips the
        warm one: an attach whose snapshot the feed log cannot replay needs a newer one."""
        if self._refresh_s <= 0:
            return self._encode()
        if fresh:
            with self._building:
                warm = self._store()
            return warm.served, warm.encoded
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
                warm = self._store()
            if self._full_wanted:
                self._encode_full(warm.served, warm.at)

    def keep_warm(self, stop: StopEvent) -> None:
        """Run `refresh` every `refresh_s` until `stop`: the warm snapshot trails the feed by about that long."""
        while not stop.wait(self._interval_s):
            try:
                self.refresh()
            except Exception:
                logger.exception("StarPulse: the warm snapshot could not be rebuilt")

    def _current(self) -> _Warm | None:
        """The warm snapshot if it is unchanged since the feed's last publish and under `IDLE_REFRESH_S` old, or
        under two intervals old (the warmer is about to replace it)."""
        warm = self._warm
        if warm is None:
            return None
        age = self._clock() - warm.at
        if age <= 2 * self._interval_s or (warm.served.rev == self._feed.rev and age < IDLE_REFRESH_S):
            return warm
        return None

    def _store(self) -> _Warm:
        taken = self._clock()
        served, encoded = self._encode()
        self._interval_s = max(self._refresh_s, WARM_IDLE_PER_BUILD * (self._clock() - taken))
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
