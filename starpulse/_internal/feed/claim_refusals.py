"""The board writer's refusals of an agent's claim, read from `board:claims` into the feed."""

from __future__ import annotations

from starpulse._internal.feed.board_feed import BoardFeed

CLAIMS_STREAM = "board:claims"  # read, not produced here: the contract scan counts only `STREAM` producers


class ClaimRefusals:
    """Hands each `board:claims` entry to `BoardFeed.refuse_claim`, so a card waiting on that claim returns to its lane."""

    def __init__(self, feed: BoardFeed) -> None:
        self._feed = feed

    def await_stream(self) -> None:
        """Nothing to say before the stream is reached: no refusals is a correct claims view."""

    def expect(self, last_id: str) -> None:
        """The feed's readiness is `machine:events`'s; this stream gates nothing."""

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Take one stream entry; one without a task and a reason, or with no readable time, is dropped."""
        task, reason = fields.get("task"), fields.get("reason")
        try:
            at = float(fields["time"])
        except KeyError, TypeError, ValueError:
            return
        if task and reason:
            self._feed.refuse_claim(task, reason, at)
