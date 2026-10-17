"""The encoded snapshot, held between changes.

Encoding the snapshot costs about 100 ms of the interpreter, which every other request thread waits out, and gzipping
it tens of ms more, so the server does both once per change to the feed instead of once per request, and encodes only
the board tasks that changed. A background thread rebuilds it shortly after a change, so a page that connects finds it
current. `get` is strict: a request that finds it out of date builds it itself, once however many ask at the same
time, so what is served includes every change made before the request. `read`, which serves `/api/snapshot`, serves
the held snapshot while it is within the TTL, so a feed that changes every second never makes a request build; the
background thread rebuilds ahead of the TTL, and `require_current` makes the next `read` after a write hold it.
"""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, NamedTuple

from starpulse.contracts.api import encode_snapshot
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.server.compression import Encoded

logger = logging.getLogger(__name__)

#: How long a held snapshot is served with no change published: what moves without one is the clock and the windows
#: drawn from it.
TTL_S = 30.0
#: How long the rebuild waits after a change for the burst it belongs to to end.
SETTLE_S = 0.25
#: How many snapshots are kept by their key after a newer one is built, for a page that was sent a reference to one.
KEPT = 4


class Served(NamedTuple):
    rev: int
    #: The publish count the snapshot was taken at.
    sent: int
    at: float
    #: The body with its gzip, made when it was built so no request compresses it.
    encoded: Encoded
    #: The body's digest, which names it at `/api/events/body/<key>`.
    key: str
    #: The document the body encodes, for a reader that needs a part of it rather than all of it.
    snapshot: dict[str, Any]

    @property
    def body(self) -> bytes:
        return self.encoded.body


class SnapshotCache:
    def __init__(
        self,
        feed: BoardFeed,
        ttl_s: float = TTL_S,
        settle_s: float = SETTLE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._feed = feed
        self._ttl_s = ttl_s
        self._settle_s = settle_s
        self._clock = clock
        self._held: Served | None = None
        #: The feed revision a write last left behind, which `read` will not serve below.
        self._floor = 0
        self._building = threading.Lock()
        self._thread: threading.Thread | None = None
        self._built = threading.Condition()
        self._kept: OrderedDict[str, Encoded] = OrderedDict()
        #: Each board task's JSON, kept between builds so one that changed is the only one encoded afresh.
        self._tasks: dict[int, tuple[Any, bytes]] = {}

    def _current(self, held: Served | None) -> bool:
        return held is not None and held.rev == self._feed.rev and self._clock() - held.at < self._ttl_s

    def get(self) -> Served:
        """The snapshot as of now, encoded: the one held when no change was published since it was taken."""
        self._refresh_in_background()
        if self._current(held := self._held):
            return held  # type: ignore[return-value]
        return self._build()

    def after_current(self) -> Served:
        """The snapshot at the feed revision as of now or later, built by the background thread, never by the caller: a
        long-lived stream that built it would keep the heap pages of the build for as long as it is open."""
        self._refresh_in_background()
        target = self._feed.rev
        with self._built:
            while (held := self._held) is None or held.rev < target:
                self._feed.revised.set()  # wakes the background thread, which waits the settle out and builds
                self._built.wait(self._settle_s + 1)
        return held

    def read(self) -> Served:
        """The snapshot for a plain read: the one held while the background rebuild catches up with changes published
        since, unless a write came after it (`require_current`). Rebuilding for each change inside the request put a
        whole rebuild's wait on one read in ten while the feed changes about once a second."""
        self._refresh_in_background()
        held = self._held
        if held is not None and held.rev >= self._floor and self._clock() - held.at < self._ttl_s:
            return held
        return self.get()

    def require_current(self) -> None:
        """Make `read` serve nothing older than the feed is now: called once a write has published its change."""
        self._floor = self._feed.rev

    def _build(self, force: bool = False) -> Served:
        with self._building:
            if not force and self._current(held := self._held):
                return held  # type: ignore[return-value]
            rev, sent, snapshot = self._feed.snapshot_at()
            encoded = Encoded.of(encode_snapshot(snapshot, self._tasks))
            self._held = held = Served(
                rev, sent, self._clock(), encoded, hashlib.sha1(encoded.body).hexdigest(), snapshot
            )
            self._kept[held.key] = encoded
            while len(self._kept) > KEPT:
                self._kept.popitem(last=False)
        with self._built:
            self._built.notify_all()
        return held

    def body(self, key: str) -> Encoded | None:
        """The snapshot `key` names, while it is one of the last few built."""
        return self._kept.get(key)

    def latest(self) -> Served | None:
        """The snapshot held, however many changes it lacks, unless it is older than a refresh should leave it."""
        self._refresh_in_background()
        held = self._held
        return held if held is not None and self._clock() - held.at < 2 * self._ttl_s else None

    def _refresh_in_background(self) -> None:
        if self._thread is None:
            with self._building:
                if self._thread is None:
                    self._thread = threading.Thread(target=self._refresh, name="snapshot-cache", daemon=True)
                    self._thread.start()

    def _refresh(self) -> None:
        """Rebuild after each change, and halfway through the TTL with none, so a request never finds it expired."""
        while True:
            changed = self._feed.revised.wait(self._ttl_s / 2)
            self._feed.revised.clear()
            if changed:
                time.sleep(self._settle_s)
            try:
                held = self._held
                if held is None or held.rev != self._feed.rev or self._clock() - held.at >= self._ttl_s / 2:
                    self._build(force=True)
            except Exception:
                logger.exception("StarPulse: the snapshot could not be rebuilt; a request that asks for it sees why")
