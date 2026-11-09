"""The qa verdicts a lens gave a task, read from `task:verdicts` into the feed's `verdict` event."""

from __future__ import annotations

import threading

from starpulse.board.board_feed import BoardFeed, entry_position


class Verdicts:
    """Publishes each `task:verdicts` entry as a `verdict` event.

    The entries retained at start are history, already kept by the history store: a page is sent none of them, only the
    verdicts that arrive once the stream is read to the last of them.
    """

    def __init__(self, feed: BoardFeed) -> None:
        self._feed = feed
        self._expected: int | None = None
        self._seen = 0
        #: Set once the stream has been read up to the last entry it held when the server started.
        self.ready = threading.Event()

    def await_stream(self) -> None:
        """Nothing to say before the stream is reached: no verdicts is a correct view."""

    def expect(self, last_id: str) -> None:
        """Mark the replay read once the entry `last_id` has been; `0` is an empty stream."""
        self._expected = entry_position(last_id)
        self._check_ready()

    def _check_ready(self) -> None:
        if self._expected is not None and self._seen >= self._expected:
            self.ready.set()

    def handle_entry(self, entry_id: str, fields: dict) -> None:
        """Take one stream entry; one that is not a whole verdict is dropped."""
        self._seen = max(self._seen, entry_position(entry_id))
        try:
            verdict = {
                "task": fields["task"],
                "lens": fields["lens"],
                "round": fields["round"],
                "outcome": fields["outcome"],
                "reason": fields["reason"],
                "at": float(fields["time"]),
            }
        except KeyError, TypeError, ValueError:
            verdict = None
        if verdict is not None and self.ready.is_set():
            self._feed.publish("verdict", verdict)
        self._check_ready()
