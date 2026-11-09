"""Feed lifecycle: the Board's ties, readiness, replay and save."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING

from starpulse.board import criteria
from starpulse.board.snapshot import BoardSnapshot
from starpulse.machine_engine.model.snapshot import qualifier
from starpulse.machine_engine.model.state_roles import StateRoles

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    pass
from starpulse.board.feed.shared import (
    BoardStore,
    cooled,
    entry_position,
    logger,
)


class LifecycleMixin:
    def _tied_to_events(self, cues: Sequence[dict]) -> dict[str, list[str]]:
        """Each Board event with the workflows (`<instance>/<workflow>`) it cues or that write it."""
        qualify = qualifier(self._domains)
        ties: dict[str, list[str]] = {}
        for cue in cues:
            if "event" in cue:
                ties.setdefault(cue["event"], []).append(qualify(cue["dag"]))
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

    def resume(
        self, store: BoardStore, stream: str, retained: Callable[[int], bool], *, keep: bool = True
    ) -> int | None:
        """Restore the Board `store` saved for `stream` and return the position to read the stream after, else None.

        None means the reader replays what the stream retains: nothing was saved, `retained(position)` says the stream
        no longer holds every entry after the saved position, or the saved Board is not one this feed can read (another
        `BoardSnapshot.SCHEMA_VERSION`). The feed saves to `store` under `stream` from now on (`save`, `keep_saved`)
        unless `keep` is false, which makes it a reader of a Board another process saves. One line says which start it
        was: `resuming after <position>` or `replaying: <reason>`, at WARNING because nothing configures a lower level.
        """
        if keep:
            self._store = (store, stream)
        position, snapshot = store.load(stream, BoardSnapshot)
        if position is None:
            logger.warning("StarPulse: replaying: no saved Board")
            return None
        if not retained(position):
            logger.warning("StarPulse: replaying: cursor %s is no longer retained", position)
            return None
        try:
            if snapshot is None:
                raise ValueError("the saved Board is of another schema version or malformed")
            open_, settled, assignees = dict(snapshot.open), dict(snapshot.settled), dict(snapshot.assignees)
            pulls, answers, cited, source = (
                dict(snapshot.pulls),
                dict(snapshot.pull_answers),
                dict(snapshot.cited),
                dict(snapshot.source),
            )
        except TypeError, ValueError:
            logger.warning("StarPulse: replaying: the saved Board cannot be read")
            return None
        # a task done while the feed was down is cold
        open_ = {task: cooled(agent, self._clock, self._roles.done) for task, agent in open_.items()}
        with self._lock:
            self._open, self._settled, self._assignees, self._seen, self._saved = (
                open_,
                settled,
                assignees,
                position,
                position,
            )
            self._pulls, self._pull_answers = pulls, answers
            self._cited, self._kept, self._kept_saved = cited, source, source
            self._gated = {
                t
                for t, agent in open_.items()
                if agent["state"] == self._roles.waiting and criteria.authored(agent["description"])
            }
            self._dependents = {}  # the saved Board keeps no reverse links; `_link` needs them for the next change
            for task_id, agent in open_.items():
                self._link(task_id, (), agent.get("dependencies", ()))
        logger.warning("StarPulse: resuming after %s", position)
        return position

    def save(self) -> None:
        """Write the Board and the position it reflects to the store `resume` was given, unless the feed has read
        nothing since the last save. A store that cannot be written is logged; the next save tries again.

        The Board is copied under `recording`, so a saved Board never holds a change `put` has placed and not yet
        recorded: a restart that resumes from it would never place that change again, and its lane would go unrecorded."""
        if self._store is None:
            return
        store, stream = self._store
        with self.recording, self._lock:
            if self._seen == self._saved and not self._pulls_unsaved and self._kept is self._kept_saved:
                return
            seen, source = self._seen, self._kept
            snapshot = BoardSnapshot(
                open=dict(self._open),
                settled=dict(self._settled),
                assignees=dict(self._assignees),
                pulls=dict(self._pulls),
                pull_answers=dict(self._pull_answers),
                cited=dict(self._cited),
                source=source,
            )
        try:
            store.save(stream, seen, snapshot)
        except Exception as exc:  # the store is down; the Board still draws and the next save retries
            logger.warning("StarPulse: cannot save the Board of %s: %s", stream, exc)
            return
        self._saved, self._pulls_unsaved, self._kept_saved = seen, False, source
