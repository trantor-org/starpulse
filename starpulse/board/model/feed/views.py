"""Feed views: the snapshot, its deltas and subscribers."""

import logging
import queue
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import Executor
from typing import TYPE_CHECKING, Any

from starpulse.machine_engine.model.machine_ties import derive

if TYPE_CHECKING:  # annotation only: the event log opens the database stack
    pass
from starpulse.board.model.feed.follow import _ledger_changes
from starpulse.board.model.ledger import MERGE_EVENT
from starpulse.board.model.feed.shared import (
    FEED_EVENT_RESEND,
    LEDGER_WINDOW,
    _cold_stub,
    done_dot,
    LINKED,
    LIVE_WINDOW_S,
    local_midnight,
    read_model_detail,
    settled_entry,
    summary_agent,
)

logger = logging.getLogger(__name__)


def declared(
    domains: Mapping[str, Sequence[str]] | None = None,
    cues: Sequence[dict] = (),
    processes: Mapping[str, Sequence[tuple[str, Sequence[str]]]] | None = None,
) -> dict:
    """The workflow relationships the page draws: the board adapter's cues, and the config's domains.

    `domains` names workflows as `<instance>/<workflow>`, and so does each cue's `dag`.
    """
    procs = processes or {}

    def dags_of(names: Sequence[str]) -> list[dict]:
        return [{"name": dag} for dag in names]

    return {
        "cues": list(cues),
        "domains": [
            {
                "name": name,
                "dags": dags_of(dags),
                "processes": [{"name": pname, "dags": dags_of(p_dags)} for pname, p_dags in procs.get(name, ())],
            }
            for name, dags in (domains or {}).items()
        ],
    }


class ViewMethods:
    def cold_page(self, before: float | None, limit: int, milestone: str | None = None) -> tuple[list[dict], bool]:
        """`GET /api/done`: the next `limit` cold done stubs entered before `before` (None: the newest), and whether
        older ones remain, of `milestone` alone when given. The page ends after the last stub sharing its final
        timestamp, so the next page's `entered < before` skips none."""
        size = limit + 1
        while True:
            rows = [_cold_stub(item) for item in self._read_model.archived(before, size, milestone)]
            if len(rows) < size or rows[-1]["entered"] != rows[limit - 1]["entered"]:
                break
            size *= 2
        end = limit
        while end < len(rows) and rows[end]["entered"] == rows[limit - 1]["entered"]:
            end += 1
        return rows[:end], len(rows) > end

    def run_list(self) -> dict[str, Any]:
        """`POST /api/jobs` and `GET /api/jobs/{name}`: the snapshot's `dags`, `domains`, `cues`, `pools` and `error`, with no board read."""
        with self._lock:
            return {
                "dags": self._workflow_rows,
                **declared(self._domains, self._cues, self._processes),
                "pools": self._drawn_pools(),
                "error": self._error(),
            }

    def declared_jobs(self) -> dict[str, Any]:
        """The config's `domains` and `cues`, which a `jobChanges` frame carries beside the event's own fields."""
        with self._lock:
            return declared(self._domains, self._cues, self._processes)

    def contract_inputs(self) -> dict[str, Any]:
        """The `dags` and `cues` of the snapshot, the only two fields the doctor's contract checks read, with no board read."""
        with self._lock:
            return {"dags": self._workflow_rows, "cues": list(self._cues)}

    def _hot(self) -> list[dict]:
        """The live Tasks of the read model as agents, queried on each call; `open_tasks` keeps the last build until a task changes."""
        summaries = self._read_model.snapshot(self._roles.done, self._clock() - LIVE_WINDOW_S)
        ready = {
            task_id
            for state in {summary["state"] for summary in summaries}
            for task_id in self._read_model.ready(state, self._roles.done)
        }
        pulls = self._pull_links(summaries)
        return [self._hot_agent(summary, summary["id"] in ready, pulls.get(summary["id"], ())) for summary in summaries]

    def _pull_links(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, list[tuple[str, str]]]:
        """The `(role, page)` of each pull request each row's task has a `delivers` or `cites` link to, by task id: a task with no UUID has none."""
        named = {uuid: str(row["id"]) for row in rows if (uuid := str((row.get("meta") or {}).get("uuid") or ""))}
        found: dict[str, list[tuple[str, str]]] = {}
        for uuid, links in self._read_model.linked(list(named), LINKED).items():
            if pages := [(role, url) for role, ref in links if (url := self._change_url(ref))]:
                found[named[uuid]] = pages
        return found

    def _hot_agent(self, summary: dict, ready: bool, links: Sequence[tuple[str, str]] = ()) -> dict:
        return self._active(
            summary_agent(summary, ready, self._read_model_moves(summary), self._default_profiles)
            | read_model_detail(summary, self._roles.attention, links)
            | {"final_summary": summary["final_summary"]}
            | self._read_model_readable(summary)
        )

    def _active(self, agent: dict) -> dict:
        """A copy of a held working task's agent with its holder's `session_activity`; any other task awaits nothing."""
        if agent["state"] != self._roles.working or not agent.get("assignee"):
            return {**agent, "awaiting": None} if agent.get("awaiting") else agent
        return {**agent, "session_activity": self._activity(agent["assignee"])}

    def drawn_task(self, task_id: str) -> tuple[dict | None, str | None]:
        """The agent a whole build draws on the board flow for the Task (a Done one as its dot), None when the Task is
        not live; and the milestone the build counts it in off the board, None when it counts in none."""
        done, since = self._roles.done, self._clock() - LIVE_WINDOW_S
        found = self._read_model.snapshot(done, since, task_id)
        if not found:
            return None, self._read_model.cold_done(done, since, task_id).get(task_id)
        ready = bool(self._read_model.ready(found[0]["state"], done, task_id))
        agent = self._hot_agent(found[0], ready, self._pull_links(found).get(task_id, ()))
        return (done_dot(agent) if agent["state"] == done else agent), None

    def cold_done(self) -> dict[str, str]:
        """The milestone of each Done Task the board flow leaves out and `milestone_done` counts, by id."""
        return self._read_model.cold_done(self._roles.done, self._clock() - LIVE_WINDOW_S)

    def settled(self, only: str | None = None) -> dict[str, dict]:
        """The Done Tasks archived in the last day as `settled` entries by id; `only` limits them to one Task."""
        rows = self._read_model.settled_done(self._roles.done, self._clock() - LEDGER_WINDOW, only)
        return {row["id"]: settled_entry(row, self._default_profiles) for row in rows}

    def done_fields(self) -> dict[str, Any]:
        """The snapshot's account of Done Tasks off the board."""
        now = self._clock()
        counts = self._read_model.milestone_done(self._roles.done, now - LIVE_WINDOW_S)
        archived = self._read_model.archived_since(local_midnight(now))
        return {"settled": self.settled(), "cold_done": [], "milestone_done": counts, "archived_today": archived}

    def _machine_lanes(self, now: float) -> dict[str, list[dict]]:
        """The tasks of each drawn machine but the board, as the page draws them."""
        reach = self._window_s if self._window_s is not None else self._lane_cap_s
        since = now - reach if reach is not None else None
        keep_open = self._roles.done if self._window_s is None else None
        lanes = self._read_model.machine_lanes(since, keep_open, self._clock() - LIVE_WINDOW_S)
        return {name: [{**a, "model": a["model"] or ""} for a in agents] for name, agents in lanes.items()}

    def machine_agents(self) -> list[tuple[str, dict]]:
        """Every task of a machine but the board as the snapshot draws it, with its machine's name."""
        lanes = self._machine_lanes(self._clock())
        return [(name, agent) for name in self._drawn if name != "board" for agent in lanes.get(name, [])]

    def _flows(self, now: float) -> tuple[list[dict], dict[str, dict]]:
        """Every flow with its tasks as the page draws them, and each machine's derivation (`machine_ties.derive`)."""
        lanes = self._machine_lanes(now)
        flows = [
            {
                "name": "board",
                "machine": self._drawn["board"],
                "agents": [done_dot(a) if a.get("state") == self._roles.done else a for a in self._hot()],
            },
            *(
                {
                    "name": name,
                    "machine": self._drawn[name],
                    "agents": lanes.get(name, []),
                }
                for name in self._drawn
                if name != "board"
            ),
        ]
        return flows, derive(flows, now)

    def build_ledgers_on(self, worker: Executor) -> None:
        """Rebuild the Ledger on `worker` from now on, so the thread that applied the update returns at once; updates that
        arrive while a build waits for the worker share the one build, which reads the latest."""
        self._ledger_worker = worker

    def _refresh_ledgers(self) -> None:
        """Rebuild the Ledger page requests read, and send it when it or its strip differs from the one last sent; the
        caller does not hold the lock.

        The build (a lane history read and the pairing) runs outside the lock, from the pulls and runs the lock hands
        it, so no page request waits on it. Builds run one at a time, each from what it reads as it starts, so the
        last to finish reflects the latest update. A feed that ties no workflow to an event has no Ledger to build.
        """
        if not self._ties:
            return
        if self._ledger_worker is None:
            self._build_ledgers()
        elif not self._ledger_queued.is_set():  # two racing callers may queue two builds, never none
            self._ledger_queued.set()
            self._ledger_worker.submit(self._build_queued)

    def _build_queued(self) -> None:
        self._ledger_queued.clear()  # before the build reads, so an update during it queues the next
        try:
            self._build_ledgers()
        except Exception:
            logger.warning("feed: the Ledger was not rebuilt", exc_info=True)

    def _build_ledgers(self) -> None:
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
                    if event in changed or (event == MERGE_EVENT and marks != shown):
                        changes.put({"rows": changed.get(event, []), **self._marks_of(event)})
                if marks != shown:
                    self._publish("ledgers", {"mergeStrip": strip_, "mergePins": view["mergePins"]})

    def _drawn_pools(self) -> list[dict]:
        """Every instance's concurrency pools, each named `<instance>/<pool>` like the `pool` a workflow names."""
        return [
            {**pool, "name": f"{instance}/{pool['name']}"} for instance, pools in self._pools.items() for pool in pools
        ]

    def _replaying(self) -> bool:
        return self._awaiting and not self.ready.is_set()

    def _error(self) -> str | None:
        if self._replaying():
            return f"board: reading {self._source}"
        return "; ".join(f"{instance}: {error}" for instance, error in self._runs_errors.items()) or None

    def publish(self, kind: str, data: dict) -> None:
        """Put `kind`/`data` on every subscriber, as an adapter's own `_publish` does."""
        self._publish(kind, data)

    def _publish(self, kind: str, data: dict) -> None:
        with self._lock:
            self.revised.set()
            if self._replaying() and not FEED_EVENT_RESEND.get(kind, False):
                return  # a replayed delta is history: the snapshot once the stream is read carries its result
            for subscriber in self._subscribers:
                subscriber.put((kind, data))

    def subscribe(self) -> tuple[dict[str, Any], queue.Queue]:
        """The snapshot now and the queue of every change after it."""
        with self._lock:
            return self.snapshot(), self.follow_changes()

    def follow_changes(self) -> queue.Queue:
        """The queue of every change from now on, with no snapshot built: for a follower that discards it."""
        with self._lock:
            subscriber: queue.Queue = queue.Queue()
            self._subscribers.append(subscriber)
            return subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.remove(subscriber)

    def snapshot(self) -> dict[str, Any]:
        """What the page draws: every machine with its tasks, the workflow declarations, the workflows and their pools.
        The tasks are read before the lock is taken, because the feed holds none of them: a build holding the feed lock for
        its queries would keep a publish, and the comment it announces, off the stream for as long as the build ran."""
        now = time.time()
        modelled = self._modelled_fields(now)
        with self._lock:
            return self._snapshot(now, modelled)

    def _modelled_fields(self, now: float) -> dict[str, Any]:
        """The snapshot's fields read from a store: the flows and the Done account."""
        flows, derived = self._flows(now)
        return {
            "flows": [{**f, **derived.get(f["name"], {})} for f in flows],
            **self.done_fields(),
        }

    def ledger_marks(self) -> dict:
        """The snapshot's merge strip and pins as of the clock now."""
        with self._lock:
            return self._ledger_marks(self._ledger_full)

    def interactive(self) -> dict[str, bool]:
        with self._lock:
            return dict.fromkeys(self._interactive, True)

    def _snapshot(self, now: float, modelled: dict[str, Any]) -> dict[str, Any]:
        """The snapshot from `modelled` and the state the feed holds; the caller holds the lock."""
        return {
            "graphs": [*self._drawn, "runs"],
            **modelled,
            "dags": self._workflow_rows,
            "pools": self._drawn_pools(),
            "pulls": self._pulls,
            **self._ledger_marks(self._ledger_full),
            "roles": self._roles.wire(),
            "interactive": dict.fromkeys(self._interactive, True),
            "error": self._error(),
            "reading": self._replaying(),
            **declared(self._domains, self._cues, self._processes),
            "now": now,
        }
