"""Feed reads: a task, its moves and the machine tasks the page shows."""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from starpulse.event_log.lane_events import ARCHIVED, done_lanes
from starpulse.machine_engine.model.transitions import lane_id

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    pass
from starpulse.board.feed.shared import (
    is_cold,
    pull_links,
    read_model_detail,
    summary_agent,
)


class ReadMethods:
    def task(self, task_id: str, *, lean: bool = False) -> dict | None:
        """The open Board task as the page draws it, or None when the Board holds no open task by that id, spelled as
        the board or its key scheme spells it. A `lean` read of the read model leaves out the verdicts of the board's
        rules on its moves and its description, for a caller that reads only its fields.

        It takes no lock, so opening a task never waits on the feed: one dict read is atomic, and a placed task's
        entry is replaced, never changed in place.
        """
        if self._read_model is not None:
            key, row = self._found(task_id)
            return self._read_model_agent(key, lean, row)
        task_id = self._aliases.get(task_id, task_id)
        agent = self.held(task_id)
        return None if agent is not None and is_cold(agent) else agent

    def _found(self, task_id: str) -> tuple[str, Mapping[str, Any] | None]:
        """The key the read model holds `task_id` under, with its row: its own key, else the id it was renamed to, else
        one it was renamed from. A task renamed on disk keeps its old row until its stream is rewritten, so both
        spellings must find it; an archived row, a promoted proposal's, yields to the live row the id was renamed to."""
        candidates = (task_id, self._aliases.get(task_id), *self._renamed.get(task_id, ()))
        rows = {key: self._read_model.task(key) for key in candidates if key}  # type: ignore[union-attr]
        held = [key for key, row in rows.items() if row is not None]
        live = [key for key in held if not rows[key]["archived"]]
        key = next(iter(live or held), task_id)
        return key, rows.get(key)

    def _keyed(self, task_id: str) -> str:
        """The key the read model holds `task_id` under, as `_found` finds it."""
        return self._found(task_id)[0]

    def _read_model_moves(self, summary: Mapping[str, Any]) -> dict:
        """The moves a read-model Task offers: the Board machine's out of its lane, a done Task's reopen among them."""
        return self._lane_moves.get(lane_id(summary["state"]), {})

    def _guarded(self, task_id: str, moves: Mapping[str, dict]) -> dict[str, dict]:
        """`moves` with each one the board's rules refuse for the task as its file stands now marked refused."""
        guarded = {}
        for lane, move in moves.items():
            refused = self._standing(task_id, lane)
            guarded[lane] = move if refused is None else {**move, **refused}
        return guarded

    def _read_model_readable(self, summary: Mapping[str, Any]) -> dict[str, str]:
        """The verdict of the board's `readable` rules on an open task's description, which a done task never carries."""
        done = lane_id(summary["state"]) in done_lanes(self._roles.done)
        return {"readable": "" if done else self._readable(summary, summary["description"])}

    def _read_model_agent(self, task_id: str, lean: bool = False, row: Mapping[str, Any] | None = None) -> dict | None:
        row = row or self._read_model.task(task_id)  # type: ignore[union-attr]
        if row is None or row["archived"]:
            return None
        ready = bool(self._read_model.ready(row["state"], self._roles.done, task_id))  # type: ignore[union-attr]
        moves = self._read_model_moves(row)
        agent = summary_agent(row, ready, moves if lean else self._guarded(task_id, moves), self._default_profiles)
        agent = agent | read_model_detail(row, self._roles.attention)
        return self._expiring(agent if lean else agent | self._read_model_readable(row))

    def follow_read_model(self, limit: int = 1000) -> int:
        """Publish a `task` delta for each Task the read model changed since the last call, an archived one as gone, and
        return how many; the projector's catch-up is followed by a call, so a page open on `/api/events` sees the change."""
        changed = self._read_model.since(self._followed, limit)  # type: ignore[union-attr]
        for summary in changed:
            agent = None if summary["archived"] else self._read_model_agent(summary["id"])
            self._publish("task", {"id": summary["id"], "agent": agent, "settled": None})
        if changed:
            self._followed = changed[-1]["seq"]
        return len(changed)

    def held(self, task_id: str) -> dict | None:
        """The open Board task as `task` has it, or its cold stub (`is_cold`) when it is done and entered before local midnight."""
        if self._read_model is not None:
            return self._read_model_agent(self._keyed(task_id))
        task_id = self._aliases.get(task_id, task_id)
        return self._open.get(task_id) or self._open.get(self._keys.canonical(task_id) if self._keys else task_id)

    def current_id(self, task_id: str) -> str:
        """The id the task answers to now: `task_id` itself unless a rename gave the task another."""
        return self._aliases.get(task_id, task_id)

    def is_resident(self, task_id: str) -> bool:
        """Whether the feed holds the open task in memory, so asking runs no query; never with a read model, which the
        feed queries on each request. False is no answer, `is_open` is."""
        if self._read_model is not None:
            return False
        return self.held(task_id) is not None

    def is_open(self, task_id: str) -> bool:
        """Whether `held` finds the task, without building the moves and standing verdicts (one read of the task's file
        for each lane) that its answer carries."""
        if self._read_model is not None:
            row = self._found(task_id)[1]
            return row is not None and not row["archived"]
        return self.held(task_id) is not None

    def cited(self, task_id: str) -> list[str]:
        """The pull request links the task cites, open or settled; none for a task the Board does not hold."""
        if self._read_model is not None:
            row = self._found(task_id)[1]
            return [] if row is None else pull_links(row["references"])
        with self._lock:
            return list(self._cited.get(task_id, ()))

    def open_tasks(self) -> list[dict]:
        """Every open Board task as the page draws it, read under the lock so a caller walks a list no placement changes.
        Within this thread's `one_read` it is the list that read built."""
        if (held := getattr(self._pinned, "tasks", None)) is not None:
            return list(held)
        with self._lock:
            return self._hot()

    def done_tasks(self) -> list[str]:
        """The ids of unarchived Done tasks of any age, the cold ones `open_tasks` leaves out; none without a read model."""
        return [] if self._read_model is None else self._read_model.held_done(self._roles.done)

    @contextmanager
    def one_read(self) -> Iterator[None]:
        """Within the block this thread's `open_tasks` builds the list once, for a caller that asks for it a dozen times
        to compose one answer. Nothing outlives the block: the feed holds no Task between requests."""
        if getattr(self._pinned, "tasks", None) is not None:
            yield
            return
        self._pinned.tasks = self.open_tasks()
        try:
            yield
        finally:
            self._pinned.tasks = None

    def is_done(self, task_id: str) -> bool:
        """Whether the task is done: completed, or in the done lane; a task the Board does not hold is not."""
        if self._read_model is not None:
            row = self._found(task_id)[1]
            return row is not None and lane_id(row["state"]) in done_lanes(self._roles.done)
        with self._lock:
            return self._done_at(task_id) is not None

    def is_archived(self, task_id: str) -> bool:
        """Whether the Board holds the task as archived: its file left the lanes by archive, so it never reaches Done."""
        if self._read_model is not None:
            row = self._found(task_id)[1]
            return row is not None and bool(row["archived"])
        with self._lock:
            settled = self._settled.get(task_id)
            return settled is not None and settled["state"] == ARCHIVED

    def placement(self, task_id: str) -> tuple[bool, bool]:
        """Whether the task is open and whether it is archived, from one lookup of its row."""
        if self._read_model is None:
            return self.is_open(task_id), self.is_archived(task_id)
        row = self._found(task_id)[1]
        return row is not None and not row["archived"], row is not None and bool(row["archived"])

    def entered_at(self, task_id: str) -> float | None:
        """When the read model last changed the task's row, which for a settled Done task is when it entered Done; None
        when the board keeps no read model or no row."""
        if self._read_model is None:
            return None
        row = self._found(task_id)[1]
        return None if row is None else row["updated_at"]

    def titled(self) -> dict[str, dict]:
        """Every Board task's `title`, `labels`, `milestone` and `profile`, open, cold or settled, by id; a settled task
        saved before its labels were kept has none, and a cold done task has them from the scan after a restart. With a
        read model, its query answers, archived Tasks included."""
        if self._read_model is not None:
            return self._read_model.titled()
        with self._lock:
            named = {
                task_id: {
                    "title": s["title"],
                    "labels": s.get("labels", []),
                    "milestone": s.get("milestone") or None,
                    "profile": s.get("model") or None,
                }
                for task_id, s in self._settled.items()
            }
            named.update(self._cold_titled)
            named.update(
                {
                    task_id: {
                        "title": a["title"],
                        "labels": a["labels"],
                        "milestone": a.get("milestone") or None,
                        "profile": a.get("profile") or None,
                    }
                    for task_id, a in self._open.items()
                    if not is_cold(a)
                }
            )
            return named

    def machine_tasks(self, flow: str, since: float | None = None) -> list[dict]:
        """Every task as `flow`'s machine last placed it within the window, and at or after `since` when given, as the
        snapshot draws it, read from `starpulse_machine_tasks`; none for a machine the feed does not draw."""
        bounds = [bound for bound in (self._window_since(), since) if bound is not None]
        return [] if self._read_model is None else self._read_model.machine_tasks(flow, max(bounds, default=None))

    @property
    def window_s(self) -> float | None:
        """The seconds back a machine's task counts, or None for no limit."""
        with self._lock:
            return self._window_s

    def _window_since(self) -> float | None:
        """The earliest time a machine's task still counts, or None for no limit."""
        with self._lock:
            return time.time() - self._window_s if self._window_s is not None else None

    def machine_task(self, flow: str, task_id: str) -> dict | None:
        """The task as `flow`'s machine last placed it, or None when it has not been placed there."""
        return None if self._read_model is None else self._read_model.machine_task(flow, task_id)

    def publish_move(self, flow: str, agent: dict) -> None:
        """Publish one machine row the Board child folded as a `move` delta; the feed places nothing itself."""
        with self._lock:
            self._publish("move", {"machine": flow, "id": agent["id"], "agent": self._modelled(agent)})

    def _modelled(self, agent: dict) -> dict:
        """A machine's task with its Board task's assignee as its model when it carries none of its own."""
        return {**agent, "model": agent["model"] or self._assignees.get(agent["task"], "")}

    def await_stream(self) -> None:
        """Say the stream has not been reached yet, so a page shows that instead of an empty Board."""
        with self._lock:
            self._awaiting = True

    def wait_replayed(self, timeout: float | None = None) -> bool:
        """Block until the stream has been read up to where it stood at the start, or `timeout` seconds pass, and say
        whether it has; at once for a feed that reads none."""
        return self.ready.wait(timeout) if self._awaiting else True
