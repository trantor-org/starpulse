"""Feed reads: a task, its moves and the machine tasks the page shows."""

import re
import time
from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from starpulse.board.model.feed.shared import (
    done_dot,
    local_midnight,
    pull_links,
    read_model_detail,
    summary_agent,
)
from starpulse.event_log.lane_events import done_lanes
from starpulse.machine_engine.model.transitions import lane_id


_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class ReadMethods:
    def task(self, task_id: str, *, lean: bool = False) -> dict | None:
        """The open Board task as the page draws it, or None when the Board holds no open task by that id, spelled as
        the board or its key scheme spells it. A `lean` read of the read model leaves out the verdicts of the board's
        rules on its moves and its description, for a caller that reads only its fields.

        It takes no lock, so opening a task never waits on the feed: one dict read is atomic, and a placed task's
        entry is replaced, never changed in place.
        """
        key, row = self._found(task_id)
        return None if row is None else self._read_model_agent(key, lean, row)

    def _row(self, key: str) -> Mapping[str, Any] | None:
        """The read model's row of `key`: within this thread's `pinned_rows`, the one it loaded first, a miss included."""
        if (held := getattr(self._rows, "held", None)) is None:
            return self._read_model.task(key)
        rows = held[1]
        if key not in rows:
            rows[key] = self._read_model.task(key)
        return rows[key]

    @contextmanager
    def pinned_rows(self) -> Iterator[None]:
        """Within the block this thread loads each task's row from the read model once, for a pass that asks for the same
        rows again and again, and its reads share one connection. `repin` drops them when the read model moved, so a row
        is never older than the position the pass last saw."""
        if getattr(self._rows, "held", None) is not None:
            yield
            return
        with self._read_model.pinned():
            self._rows.held = (self._read_model.position(), {})
            try:
                yield
            finally:
                self._rows.held = None

    def repin(self) -> None:
        """Within `pinned_rows`, forget the rows held when the read model has moved since they were loaded."""
        if (held := getattr(self._rows, "held", None)) is not None and held[0] != (
            position := self._read_model.position()
        ):
            self._rows.held = (position, {})

    def _found(self, task_id: str) -> tuple[str, Mapping[str, Any] | None]:
        """The key the read model holds `task_id` under, with its row: its own key, else the id it was renamed to. A
        task renamed on disk keeps its old row until its stream is rewritten, so both spellings must find it; an archived
        row yields to the live row the id was renamed to."""
        candidates = (task_id, self._aliases.get(task_id))
        rows = {key: self._row(key) for key in candidates if key}
        held = [key for key, row in rows.items() if row is not None]
        live = [key for key in held if not rows[key]["archived"]]
        key = next(iter(live or held), task_id)
        if (row := rows.get(key)) is not None and str(row["id"]).lower() != key.lower():
            key = str(row["id"])  # a UUID or alias the read model resolved: draw it under the task's own key
        return key, row

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

    def _read_model_agent(
        self, task_id: str, lean: bool = False, row: Mapping[str, Any] | None = None, settled_done: bool = False
    ) -> dict | None:
        row = row or self._read_model.task(task_id)
        if row is None or (row["archived"] and not (settled_done and lane_id(row["state"]) == self._roles.done)):
            return None
        ready = bool(self._read_model.ready(row["state"], self._roles.done, task_id))
        moves = self._read_model_moves(row)
        agent = summary_agent(row, ready, moves if lean else self._guarded(task_id, moves), self._default_profiles)
        agent = agent | read_model_detail(row, self._roles.attention) | {"final_summary": row["final_summary"]}
        return agent if lean else agent | self._read_model_readable(row)

    def follow_read_model(self, limit: int = 1000) -> int:
        """Publish a `task` delta for each Task the read model changed since the last call, an archived one as gone, each
        carrying the count archived today, and return how many; the projector's catch-up is followed by a call, so a page open on `/api/events` sees the change."""
        changed = self._read_model.since(self._followed, limit)
        archived_today = self._read_model.archived_since(local_midnight(self._clock())) if changed else None
        for summary in changed:
            for alias in (summary["meta"] or {}).get("aliases") or []:
                self.alias(alias, summary["id"])
            agent = None if summary["archived"] else self._read_model_agent(summary["id"])
            if agent and agent["state"] == self._roles.done:
                agent = done_dot(agent)
            elif agent:
                agent = self._active(agent)
            settled = self.settled(summary["id"]).get(summary["id"]) if summary["archived"] else None
            self._publish(
                "task", {"id": summary["id"], "agent": agent, "settled": settled, "archived_today": archived_today}
            )
        if changed:
            self._followed = changed[-1]["seq"]
        return len(changed)

    def held(self, task_id: str, *, lean: bool = False) -> dict | None:
        """The open Board task as `task` has it, `lean` as there, or a settled Done one, which a reopen reaches."""
        key, row = self._found(task_id)
        return None if row is None else self._read_model_agent(key, lean, row, settled_done=True)

    def current_id(self, task_id: str) -> str:
        """The id the task answers to now: `task_id` itself unless a rename gave the task another or it is the task's UUID."""
        if (named := self._aliases.get(task_id)) is not None:
            return named
        return (self._read_model.resolve(task_id) if _UUID.fullmatch(task_id) else None) or task_id

    def is_open(self, task_id: str) -> bool:
        """Whether `held` finds the task, without building the moves and standing verdicts (one read of the task's file
        for each lane) that its answer carries."""
        row = self._found(task_id)[1]
        return row is not None and not row["archived"]

    def cited(self, task_id: str) -> list[str]:
        """The pull request links the task cites, open or settled; none for a task the Board does not hold."""
        row = self._found(task_id)[1]
        return [] if row is None else pull_links(row["references"])

    def open_tasks(self) -> list[dict]:
        """Every open Board task as the page draws it. Within this thread's `one_read` it is the list that read built.

        Outside one it is rebuilt only when the read model's position or the local day moved since the last build; a
        working task's `session_activity` is read again on each call, since a session's turn moves no task."""
        if (held := getattr(self._pinned, "tasks", None)) is not None:
            return list(held)
        key = (
            self._read_model.position(),
            local_midnight(self._clock()),
        )  # before the build: a change in it rebuilds next
        with self._build_lock:  # threads woken by one change build once; the rest read that build
            if (built := self._built) is None or built[0] < key:
                self._built = (key, self._hot())
                return list(self._built[1])
        return [self._active(agent) for agent in built[1]]

    @contextmanager
    def one_read(self) -> Iterator[None]:
        """Within the block this thread's `open_tasks` builds the list once, for a caller that asks for it a dozen times
        to compose one answer. The pinned list ends with the block; `open_tasks` keeps only its last build."""
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
        row = self._found(task_id)[1]
        return row is not None and lane_id(row["state"]) in done_lanes(self._roles.done)

    def is_archived(self, task_id: str) -> bool:
        """Whether the Board holds the task as archived: its file left the lanes by archive, so it never reaches Done."""
        row = self._found(task_id)[1]
        return row is not None and bool(row["archived"])

    def placement(self, task_id: str) -> tuple[bool, bool, float | None]:
        """Whether the task is open, whether it is archived, and when the read model last changed its row (for a
        settled Done task, when it entered Done), from one lookup of its row. The last is None without a row."""
        row = self._found(task_id)[1]
        if row is None:
            return False, False, None
        return not row["archived"], bool(row["archived"]), row["updated_at"]

    def titled(self, ids: Collection[str] | None = None) -> dict[str, dict]:
        """Every Board task's `title`, `labels`, `milestone` and `profile`, open, cold or settled, by id; a settled task
        saved before its labels were kept has none, and a cold done task has them from the scan after a restart. With a
        read model's query answers, archived Tasks included; `ids` limits them to those tasks."""
        return self._read_model.titled(ids)

    def machine_tasks(self, flow: str, since: float | None = None) -> list[dict]:
        """Every task as `flow`'s machine last placed it within the window, and at or after `since` when given, as the
        snapshot draws it, read from `starpulse_machine_tasks`; none for a machine the feed does not draw."""
        bounds = [bound for bound in (self._window_since(), since) if bound is not None]
        return self._read_model.machine_tasks(flow, max(bounds, default=None))

    def machine_task_ids(self, flow: str) -> list[str]:
        """The ids of the tasks `machine_tasks` holds for `flow`, read without their records."""
        return self._read_model.machine_task_ids(flow, self._window_since())

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
        return self._read_model.machine_task(flow, task_id)

    def publish_move(self, flow: str, agent: dict) -> None:
        """Publish one machine row the Board child folded as a `move` delta; the feed places nothing itself."""
        with self._lock:
            self._publish(
                "move", {"machine": flow, "id": agent["id"], "agent": {**agent, "model": agent["model"] or ""}}
            )

    def await_stream(self) -> None:
        """Say the stream has not been reached yet, so a page shows that instead of an empty Board."""
        with self._lock:
            self._awaiting = True

    def wait_replayed(self, timeout: float | None = None) -> bool:
        """Block until the stream has been read up to where it stood at the start, or `timeout` seconds pass, and say
        whether it has; at once for a feed that reads none."""
        # adr-exempt: handshake
        return self.ready.wait(timeout) if self._awaiting else True
