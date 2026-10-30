"""Feed reads: a task, its moves and the machine tasks the page shows."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from starpulse.event_log.lane_events import done_lanes
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
    def task(self, task_id: str) -> dict | None:
        """The open Board task as the page draws it, or None when the Board holds no open task by that id, spelled as
        the board or its key scheme spells it.

        It takes no lock, so opening a task never waits on the feed: one dict read is atomic, and a placed task's
        entry is replaced, never changed in place.
        """
        if self._read_model is not None:
            return self._read_model_agent(task_id)
        agent = self.held(task_id)
        return None if agent is not None and is_cold(agent) else agent

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

    def _read_model_agent(self, task_id: str) -> dict | None:
        row = self._read_model.task(task_id)  # type: ignore[union-attr]
        if row is None or row["archived"]:
            return None
        ready = task_id in self._read_model.ready(row["state"], self._roles.done)  # type: ignore[union-attr]
        return self._expiring(
            summary_agent(row, ready, self._guarded(task_id, self._read_model_moves(row))) | read_model_detail(row, self._roles.attention)
        )

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
            return self._read_model_agent(task_id)
        return self._open.get(task_id) or self._open.get(self._keys.canonical(task_id) if self._keys else task_id)

    def cited(self, task_id: str) -> list[str]:
        """The pull request links the task cites, open or settled; none for a task the Board does not hold."""
        if self._read_model is not None:
            row = self._read_model.task(task_id)
            return [] if row is None else pull_links(row["references"])
        with self._lock:
            return list(self._cited.get(task_id, ()))

    def open_tasks(self) -> list[dict]:
        """Every open Board task as the page draws it, read under the lock so a caller walks a list no placement changes."""
        with self._lock:
            return self._hot()

    def is_done(self, task_id: str) -> bool:
        """Whether the task is done: completed, or in the done lane; a task the Board does not hold is not."""
        if self._read_model is not None:
            row = self._read_model.task(task_id)
            return row is not None and lane_id(row["state"]) in done_lanes(self._roles.done)
        with self._lock:
            return self._done_at(task_id) is not None

    def titled(self) -> dict[str, dict]:
        """Every Board task's `title` and `labels`, open or settled, by id; a settled task saved before its labels
        were kept has none."""
        with self._lock:
            named = {
                task_id: {"title": s["title"], "labels": s.get("labels", [])} for task_id, s in self._settled.items()
            }
            named.update(
                {
                    task_id: {"title": a["title"], "labels": a["labels"]}
                    for task_id, a in self._open.items()
                    if not is_cold(a)
                }
            )
            return named

    def machine_tasks(self, flow: str) -> list[dict]:
        """Every task as `flow`'s machine last placed it within the window, as the snapshot draws it; none for a machine
        the feed does not draw."""
        with self._lock:
            since = time.time() - self._window_s if self._window_s is not None else None
            return [a for a in self._machines.get(flow, {}).values() if since is None or a["active"] >= since]

    @property
    def window_s(self) -> float | None:
        """The seconds back a machine's task counts, or None for no limit."""
        with self._lock:
            return self._window_s

    def forget(self, flow: str, task_id: str) -> None:
        """Drop a task a machine placed, quietly: a snapshot already leaves out one past the window."""
        with self._lock:
            self._machines[flow].pop(task_id, None)

    def machine_task(self, flow: str, task_id: str) -> dict | None:
        """The task as `flow`'s machine last placed it, or None when it has not been placed there."""
        with self._lock:
            return self._machines[flow].get(task_id)

    def move(self, flow: str, agent: dict, *, publish: bool = True) -> None:
        """Place a task on a machine other than the Board and publish the move, unless `publish` is false: a replayed
        step is history, which the snapshot the replay ends with carries (`publish("snapshot", snapshot())`)."""
        with self._lock:
            self._machines[flow][agent["id"]] = agent
            if publish:
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
