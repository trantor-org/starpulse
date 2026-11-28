"""Feed lifecycle: the Board's ties, readiness and replay."""

from collections.abc import Mapping, Sequence
from functools import cached_property

from starpulse.board.model.feed.shared import entry_position
from starpulse.machine_engine.model.workflow_names import Qualify, qualifier
from starpulse.machine_engine.model.state_roles import StateRoles


class LifecycleMixin:
    # Built on first use: a feed given no cues names no workflow.
    @cached_property
    def _qualify(self) -> Qualify:
        return qualifier(self._domains)

    def _tied_to_events(self, cues: Sequence[dict]) -> dict[str, list[str]]:
        """Each Board event with the workflows (`<instance>/<workflow>`) it cues or that write it."""
        ties: dict[str, list[str]] = {}
        for cue in cues:
            if "event" in cue:
                ties.setdefault(cue["event"], []).append(self._qualify(cue["dag"]))
        for event, writers in self._drawn["board"].get("writers", {}).items():
            ties.setdefault(event, []).extend(writer["actor"] for writer in writers)
        return {event: list(dict.fromkeys(dags)) for event, dags in ties.items()}

    def tied(self, instance: str) -> frozenset[str]:
        """The workflows of `instance` a Board event cues or that write one: those whose runs the Ledger pairs."""
        prefix = f"{instance}/"
        return frozenset(
            dag.removeprefix(prefix) for dags in self._ties.values() for dag in dags if dag.startswith(prefix)
        )

    @property
    def roles(self) -> StateRoles:
        """Which of the Board's States play which part."""
        return self._roles

    @property
    def machines(self) -> Mapping[str, dict]:
        """The machines the page draws, the Board's as `board`."""
        return self._drawn

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

    def _replaying(self) -> bool:
        return self._awaiting and not self.ready.is_set()

    def seen(self, entry_id: str) -> None:
        """Note that a board adapter reading a stream has read up to the entry `entry_id`."""
        with self._lock:
            self._seen = max(self._seen, entry_position(entry_id))
        self._check_ready()
