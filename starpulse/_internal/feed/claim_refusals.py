"""The board writer's refusals of an agent's claim, read from `board:claims` into the feed."""

from __future__ import annotations

import threading

from starpulse._internal.feed.board_feed import BoardFeed, entry_position

CLAIMS_STREAM = "board:claims"  # read, not produced here: the contract scan counts only `STREAM` producers


class ClaimRefusals:
    """Hands each `board:claims` entry to `BoardFeed.refuse_claim`, so a card waiting on that claim returns to its lane.

    The entries retained at start are history: they are kept without a `claim` delta each, and a connected page is
    handed one snapshot once the stream is read to the last of them.
    """

    def __init__(self, feed: BoardFeed) -> None:
        self._feed = feed
        self._expected: int | None = None
        self._seen = 0
        #: Set once the stream has been read up to the last entry it held when the server started.
        self.ready = threading.Event()

    def await_stream(self) -> None:
        """Nothing to say before the stream is reached: no refusals is a correct claims view."""

    def expect(self, last_id: str) -> None:
        """Mark the replay read once the entry `last_id` has been; `0` is an empty stream. The feed's readiness stays `machine:events`'s."""
        self._expected = entry_position(last_id)
        self._check_ready()

    def _check_ready(self) -> None:
        if self._expected is None or self._seen < self._expected or self.ready.is_set():
            return
        self.ready.set()
        self._feed.publish("snapshot", self._feed.snapshot())

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Take one stream entry; one without a task and a reason, or with no readable time, is dropped."""
        self._seen = max(self._seen, entry_position(entry_id))
        task, reason = fields.get("task"), fields.get("reason")
        try:
            at = float(fields["time"])
        except KeyError, TypeError, ValueError:
            at = None
        if at is not None and task and reason:
            self._feed.refuse_claim(task, reason, at, publish=self._expected is None or self.ready.is_set())
        self._check_ready()
