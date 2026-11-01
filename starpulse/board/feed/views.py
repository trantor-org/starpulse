"""Feed views: the snapshot, its deltas and subscribers."""

from __future__ import annotations

import queue
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from starpulse.board.ledger import (
    PAGE,
)
from starpulse.machine_engine.model.machine_ties import derive, entries
from starpulse.machine_engine.model.machine_ties import page as machine_page
from starpulse.machine_engine.model.snapshot import declared

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    pass
from starpulse.board.feed.follow import _ledger_changes
from starpulse.board.feed.shared import (
    FEED_EVENT_RESEND,
    LEDGER_WINDOW,
    _cold_stub,
    is_cold,
    read_model_detail,
    summary_agent,
)


def local_midnight(now: float) -> float:
    """The start of the local day `now` falls in, as a Unix time: a Done Task changed since it is still live."""
    return datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


class ViewMethods:
    def cold_page(self, before: float | None, limit: int) -> tuple[list[dict], bool]:
        """`GET /api/done`: the next `limit` cold done stubs entered before `before` (None: the newest), and whether
        older ones remain."""
        if self._read_model is not None:
            page = self._read_model.archived(before, limit + 1)
            return [_cold_stub(item) for item in page[:limit]], len(page) > limit
        with self._lock:
            cold = sorted((a for a in self._open.values() if is_cold(a)), key=lambda a: a["entered"], reverse=True)
        older = [a for a in cold if before is None or a["entered"] < before]
        return older[:limit], len(older) > limit

    def _hot(self) -> list[dict]:
        """Every open task but the cold done ones; the caller holds the lock."""
        if self._read_model is not None:
            return self._read_model_hot()
        return [agent for agent in self._open.values() if not is_cold(agent)]

    def _read_model_hot(self) -> list[dict]:
        """The live Tasks of the read model as agents, queried on each request: nothing of the Board is held between them."""
        summaries = self._read_model.snapshot(self._roles.done, local_midnight(self._clock()))  # type: ignore[union-attr]
        ready = {
            task_id
            for state in {summary["state"] for summary in summaries}
            for task_id in self._read_model.ready(state, self._roles.done)  # type: ignore[union-attr]
        }
        return [
            self._expiring(
                summary_agent(summary, summary["id"] in ready, self._read_model_moves(summary))
                | read_model_detail(summary, self._roles.attention)
            )
            for summary in summaries
        ]

    def _done_fields(self) -> dict[str, Any]:
        """The snapshot's account of Done Tasks off the board; the caller holds the lock."""
        if self._read_model is None:
            cold = sorted(t for t, a in self._open.items() if is_cold(a))
            return {"settled": dict(self._settled), "cold_done": cold, "milestone_done": {}}
        counts = self._read_model.milestone_done(self._roles.done, local_midnight(self._clock()))
        return {"settled": {}, "cold_done": [], "milestone_done": counts}

    def _flows(self, now: float) -> tuple[list[dict], dict[str, dict]]:
        """Every flow with its tasks as the page draws them, and each machine's derivation (`machine_ties.derive`)."""
        since = now - self._window_s if self._window_s is not None else None
        lanes = {} if self._read_model is None else self._read_model.machine_lanes(since)
        flows = [
            {"name": "board", "machine": self._drawn["board"], "agents": self._hot()},
            *(
                {
                    "name": name,
                    "machine": self._drawn[name],
                    "agents": [self._modelled(a) for a in lanes.get(name, [])],
                }
                for name in self._drawn
                if name != "board"
            ),
        ]
        return flows, derive(flows, now)

    def machine_rows(self, open_: str | None, before: float | None, limit: int) -> dict | None:
        """`GET /api/machines`: the next `limit` machines entered from `open_` (None: the In Progress machine) with
        activity older than `before` (None: the newest), `{open, machines, more}`, each machine whole with its
        derivation; None when `open_` is not a machine here."""
        with self._lock:
            flows, derived = self._flows(time.time())
            if open_ is None:
                open_ = next((n for n, d in derived.items() if d["depth"] == 0), None)
            elif open_ not in derived:
                return None
            names, more = machine_page(derived, open_, before=before, limit=limit)
            by_name = {f["name"]: f for f in flows}
            return {"open": open_, "machines": [{**by_name[n], **derived[n]} for n in names], "more": more}

    def _machine_fields(self, flows: list[dict], derived: dict[str, dict], now: float) -> dict:
        """The snapshot's `machinePage` (names of the In Progress machine's first page of rows; their bodies are in
        `flows`) and `machineStrip` (the last 24 hours before `now` of machine entries, counted over every machine)."""
        top = next((n for n, d in derived.items() if d["depth"] == 0), None)
        names, more = machine_page(derived, top, before=None, limit=PAGE)
        return {
            "machinePage": {"open": top, "machines": names, "more": more},
            "machineStrip": {"entries": entries(flows, derived, now, LEDGER_WINDOW)},
        }

    def _refresh_ledgers(self) -> None:
        """Rebuild the Ledger page requests read, and send it when it or its strip differs from the one last sent; the
        caller does not hold the lock.

        The build (a lane history read and the pairing) runs outside the lock, from the pulls and runs the lock hands
        it, so no page request waits on it. Builds run one at a time, each from what it reads as it starts, so the
        last to finish reflects the latest update. A feed that ties no workflow to an event has no Ledger to build.
        """
        if not self._ties:
            return
        with self._building:
            with self._lock:
                pulls, recent, since = self._pulls, self._recent_runs(), self._clock() - LEDGER_WINDOW
            full = self._ledger(pulls, recent, since)
            with self._lock:
                self._ledger_full = full
                view = self._ledger_view(full)
                strip_ = view["mergeStrip"]
                changed = _ledger_changes(self._ledgers, view["ledgers"])
                marks = (strip_ and strip_["buckets"], view["mergePins"])
                shown = (self._strip and self._strip["buckets"], self._pins)
                self._ledgers, self._strip, self._pins = view["ledgers"], strip_, view["mergePins"]
                for event, changes in self._watchers:
                    if event in changed:
                        changes.put({"rows": changed[event]})
                if marks != shown:
                    self._publish("ledgers", {"mergeStrip": strip_, "mergePins": view["mergePins"]})

    def _drawn_pools(self) -> list[dict]:
        """Every instance's concurrency pools, each named `<instance>/<pool>` like the `pool` a workflow names."""
        return [
            {**pool, "name": f"{instance}/{pool['name']}"} for instance, pools in self._pools.items() for pool in pools
        ]

    def _error(self) -> str | None:
        if self._awaiting and not self.ready.is_set():
            return f"board: reading {self._source}"
        return "; ".join(f"{instance}: {error}" for instance, error in self._runs_errors.items()) or None

    def publish(self, kind: str, data: dict) -> None:
        """Put `kind`/`data` on every stream subscriber (and the reconnect log), as an adapter's own `_publish` does."""
        self._publish(kind, data)

    def _publish(self, kind: str, data: dict) -> None:
        with self._lock:
            self._rev += 1
            self.revised.set()
            if self._replaying() and not FEED_EVENT_RESEND.get(kind, False):
                return  # a replayed delta is history: the snapshot once the stream is read carries its result
            self._sent += 1
            self._sent_log.append((self._sent, kind, data))
            for subscriber in self._subscribers:
                subscriber.put((kind, data))

    def subscribe(self) -> tuple[dict[str, Any], queue.Queue]:
        """The snapshot now and the queue of every change after it."""
        with self._lock:
            subscriber: queue.Queue = queue.Queue()
            self._subscribers.append(subscriber)
            return self.snapshot(), subscriber

    @property
    def rev(self) -> int:
        """How many publishes the feed has made; a snapshot taken at another number is out of date."""
        return self._rev

    def snapshot_at(self) -> tuple[int, int, dict[str, Any]]:
        """The snapshot with the `rev` and the publish count it was taken at, as one reading."""
        with self._lock:
            return self._rev, self._sent, self.snapshot()

    def watch_from(self, sent: int) -> tuple[list[tuple[str, dict]], queue.Queue] | None:
        """The changes published after the `sent`-th, and the queue of every change after those: what a page needs on a
        snapshot taken at that count. None when the feed no longer holds them all.
        """
        with self._lock:
            missed = [(kind, data) for count, kind, data in self._sent_log if count > sent]
            if len(missed) != self._sent - sent:
                return None
            subscriber: queue.Queue = queue.Queue()
            self._subscribers.append(subscriber)
            self._streams.append(subscriber)
            return missed, subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.remove(subscriber)
            if subscriber in self._streams:
                self._streams.remove(subscriber)

    def announce(self, kind: str, data: dict, wait_s: float = 1.0) -> None:
        """Give every open stream one event outside the sent log, and wait up to `wait_s` for each stream to have
        written it. A page that connects afterwards never sees it: it is about the process, not the Board.

        A stream marks each item it took off its queue with `task_done`; the wait is for those marks.
        """
        with self._lock:
            streams = list(self._streams)
        for stream in streams:
            stream.put((kind, data))
        deadline = time.monotonic() + wait_s
        for stream in streams:
            while stream.unfinished_tasks and time.monotonic() < deadline:
                time.sleep(0.005)

    def snapshot(self) -> dict[str, Any]:
        """What the page draws: every machine with its tasks, the workflow declarations, the workflows and their pools."""
        with self._lock:
            now = time.time()
            flows, derived = self._flows(now)
            return {
                "graphs": [*self._drawn, "runs"],
                "flows": [{**f, **derived.get(f["name"], {})} for f in flows],
                **self._machine_fields(flows, derived, now),
                "dags": self._workflows(),
                "pools": self._drawn_pools(),
                "cpu": dict(self._cpu),
                "pulls": self._pulls,
                **self._ledger_marks(self._ledger_full),
                "claims": dict(self._claims),
                "roles": self._roles.wire(),
                "capabilities": dict(self._capabilities),
                **self._done_fields(),
                "ratings": {} if self._ratings is None else self._ratings.latest(),
                "interactive": dict.fromkeys(self._interactive, True),
                "error": self._error(),
                "reading": self._replaying() or self._machines_reading,
                **declared(self._domains, self._runnable(), self._cues, self._processes),
                "boardUrl": self._board_url,
                "hint": self._hint,
                "now": now,
            }
