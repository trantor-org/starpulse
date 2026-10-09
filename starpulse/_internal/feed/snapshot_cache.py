"""The encoded snapshot, held between changes.

Encoding the snapshot costs about 100 ms of the interpreter, which every other request thread waits out, so the server
encodes it once per change to the feed instead of once per request. A background thread rebuilds it shortly after a
change, so a page that connects finds it current; a request that finds it out of date builds it itself, once however
many ask at the same time, so what is served always includes every change made before the request.
"""

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import NamedTuple

from starpulse.contracts.api import encode
from starpulse._internal.feed.board_feed import BoardFeed

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
    body: bytes
    #: The body's digest, which names it at `/api/events/body/<key>`.
    key: str


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
        self._building = threading.Lock()
        self._thread: threading.Thread | None = None
        self._kept: OrderedDict[str, bytes] = OrderedDict()

    def _current(self, held: Served | None) -> bool:
        return held is not None and held.rev == self._feed.rev and self._clock() - held.at < self._ttl_s

    def get(self) -> Served:
        """The snapshot as of now, encoded: the one held when no change was published since it was taken."""
        self._refresh_in_background()
        if self._current(held := self._held):
            return held  # type: ignore[return-value]
        with self._building:
            if self._current(held := self._held):
                return held  # type: ignore[return-value]
            rev, sent, snapshot = self._feed.snapshot_at()
            body = encode("snapshot", snapshot)
            self._held = held = Served(rev, sent, self._clock(), body, hashlib.sha1(body).hexdigest())
            self._kept[held.key] = body
            while len(self._kept) > KEPT:
                self._kept.popitem(last=False)
            return held

    def body(self, key: str) -> bytes | None:
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
        while True:
            self._feed.revised.wait(self._ttl_s)
            self._feed.revised.clear()
            time.sleep(self._settle_s)
            try:
                self.get()
            except Exception:
                logger.exception("StarPulse: the snapshot could not be rebuilt; a request that asks for it sees why")
