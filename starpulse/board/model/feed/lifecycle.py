"""Feed lifecycle: the Board's ties, window, readiness and replay.

What every feed runs as it is built or publishes (`_tied_to_events`, `roles`, `machines`, `_replaying`) lives with
`BoardFeed` and the views, so an edit here selects the tests that exercise these methods, not every test that builds
a feed.
"""

from starpulse.board.model.feed.shared import entry_position


class LifecycleMixin:
    def tied(self, instance: str) -> frozenset[str]:
        """The workflows of `instance` a Board event cues or that write one: those whose runs the Ledger pairs."""
        prefix = f"{instance}/"
        return frozenset(
            dag.removeprefix(prefix) for dags in self._ties.values() for dag in dags if dag.startswith(prefix)
        )

    def set_window(self, window_s: float | None) -> None:
        """Draw with a new window from now on, and hand every connected page a snapshot that applies it."""
        with self._lock:
            self._window_s = window_s
            self._publish("snapshot", self.snapshot())

    def cap_lanes(self, cap_s: float | None) -> None:
        """Read the snapshot's machine lanes no further back than `cap_s` seconds when no window narrows them, except
        a lane whose Task is still open; the machine reads (`machine_tasks`) stay as the window leaves them."""
        with self._lock:
            self._lane_cap_s = cap_s

    def expect(self, last_id: str) -> None:
        """Mark the feed ready once the entry `last_id` has been read; `0` is an empty stream."""
        with self._lock:
            self._awaiting = True
            self._expected = entry_position(last_id)
        self._check_ready()

    def _check_ready(self) -> None:
        """Once the stream is read to the entry expected, build the Ledger the replay's moves left and mark the feed
        ready; the caller does not hold the lock."""
        with self._lock:
            if self._expected is None or self._seen < self._expected or self.ready.is_set():
                return
        self._refresh_ledgers()
        with self._lock:
            if self.ready.is_set():
                return
            self.ready.set()
            # the replay published no step, so a page connected through it is handed the Board it built in one piece
            self._publish("snapshot", self.snapshot())

    def seen(self, entry_id: str) -> None:
        """Note that a board adapter reading a stream has read up to the entry `entry_id`."""
        with self._lock:
            self._seen = max(self._seen, entry_position(entry_id))
        self._check_ready()
