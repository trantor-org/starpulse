"""What StarPulse draws, held in memory and kept current by the adapters.

The board adapter (`starpulse.board`) places each Board task here, the server keeps each task's latest state,
and every connected page gets one snapshot and then a delta per change. Each other machine's tasks arrive from
the event log (`machine_tasks`), and each runs adapter instance's workflows from its adapter module.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from starpulse.contracts import BoardTask, TaskKeys
from starpulse.event_log import DEFAULT_POLL_INTERVAL, EventLog, Tail
from starpulse.snapshot import declared
from starpulse.upstream_backlog import DEFAULT_STATUSES, board_machine

__all__ = ["BoardFeed", "BoardStore", "Followed", "Resumable"]

logger = logging.getLogger(__name__)

_PULL_REQUEST = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+/?")
# The runs instance pushed workflows belong to, so the page names them `pushed/<workflow>`.
PUSHED_INSTANCE = "pushed"
#: How often a running reader saves the Board, in seconds; a restart reads again what arrived since.
SAVE_INTERVAL = 60.0


def task_agent(task: BoardTask) -> dict:
    """One task as an agent on the Board machine, its lane as the state id."""
    return {
        "id": task.id,
        "title": task.title,
        "state": task.lane,
        "model": task.assignee,
        "labels": list(task.labels),
        "milestone": task.milestone,
        "dependencies": list(task.dependencies),
        "prs": [ref for ref in task.references if _PULL_REQUEST.fullmatch(ref)],
        "description": task.description,
        "moves": {column: move.model_dump() for column, move in task.moves.items()},
    }


def stream_id(entry_id: str) -> tuple[int, int]:
    """A stream id as numbers: `10-0` follows `9-0`, which text order gets backwards."""
    millis, _, sequence = entry_id.partition("-")
    return int(millis), int(sequence or 0)


class BoardStore(Protocol):
    """Where a feed keeps the Board it saved: the event log, or any store that holds one state per stream."""

    def load_board_state(self, stream: str) -> tuple[str, dict] | None: ...

    def save_board_state(self, stream: str, cursor: str, state: dict) -> None: ...


class BoardFeed:
    """Each task's latest projected state, as the page's Board snapshot and the deltas after it.

    Entries arrive on the consumers' threads and pages read from request threads; one lock holds
    them apart, and a subscriber takes its snapshot and its queue under that lock so no change
    falls between the two. A machine's task whose latest move is older than `window_s` seconds
    (None: never) is left out of a snapshot. `board_url` is the tracker's address the page links tasks
    to (None: no links). `machines` are the machines the page draws, the Board's as `board` (None: a Board of
    Backlog.md's default statuses alone), and `cues` the board adapter's workflow cues. `domains` and `run_safe`
    are the config's, each workflow as `<instance>/<workflow>`. `source` names what the Board is read from, for the
    page to show until the board adapter has read it.
    """

    def __init__(
        self,
        window_s: float | None = None,
        keys: TaskKeys | None = None,
        board_url: str | None = None,
        machines: Mapping[str, dict] | None = None,
        domains: Mapping[str, Sequence[str]] | None = None,
        run_safe: Collection[str] = (),
        cues: Sequence[dict] = (),
        source: str = "the board",
        capabilities: Mapping[str, bool] | None = None,
        hint: str | None = None,
    ) -> None:
        self._hint = hint
        self._capabilities = {"edit": False, "archive": False, "create": False} | dict(capabilities or {})
        self._keys = keys
        self._domains = domains or {}
        self._run_safe = run_safe
        self._cues = cues
        self._source = source
        self._drawn = machines if machines is not None else {"board": board_machine(DEFAULT_STATUSES)}
        self._board_url = board_url
        self._lock = threading.RLock()
        self._window_s = window_s
        self._open: dict[str, dict] = {}
        self._machines: dict[str, dict[str, dict]] = {name: {} for name in self._drawn if name != "board"}
        self._settled: dict[str, str] = {}
        #: Every placed task's assignee, a settled one's included, so a machine still drawing it keeps its colour.
        self._assignees: dict[str, str] = {}
        self._dags: dict[str, list] = {}
        self._pools: dict[str, list] = {}
        self._runs_errors: dict[str, str] = {}
        self._pulls: dict[str, list[dict]] = {}
        #: Each task's latest refused claim (a board adapter's `refuse_claim` call): its reason and when the writer refused it.
        self._claims: dict[str, dict] = {}
        self._subscribers: list[queue.Queue] = []
        self._awaiting = False  # pragma: no mutate — None is falsy too
        self._expected: tuple[int, int] | None = None
        self._seen = (0, 0)
        self._saved = (0, 0)
        self._store: tuple[BoardStore, str] | None = None
        #: Set once the stream has been read up to the last entry it held when the feed started.
        self.ready = threading.Event()

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
        """Mark the feed ready once the entry `last_id` has been read; `0-0` is an empty stream."""
        with self._lock:
            self._awaiting = True
            self._expected = stream_id(last_id)
            self._check_ready()

    def _check_ready(self) -> None:
        if self._expected is not None and self._seen >= self._expected and not self.ready.is_set():
            self.ready.set()
            # the replay published no step, so a page connected through it is handed the Board it built in one piece
            self._publish("snapshot", self.snapshot())

    def _replaying(self) -> bool:
        return self._awaiting and not self.ready.is_set()

    def seen(self, entry_id: str) -> None:
        """Note that a board adapter reading a stream has read up to the entry `entry_id`."""
        with self._lock:
            self._seen = max(self._seen, stream_id(entry_id))
            self._check_ready()

    def resume(self, store: BoardStore, stream: str, retained: Callable[[str], bool]) -> str | None:
        """Restore the Board `store` saved for `stream` and return the cursor to read the stream after, else None.

        None means the reader replays what the stream retains: nothing was saved, `retained(cursor)` says the stream
        no longer holds every entry after the saved cursor, or the saved state is not one this feed can read. The
        feed saves to `store` under `stream` from now on (`save`, `keep_saved`).
        """
        self._store = (store, stream)
        saved = store.load_board_state(stream)
        if saved is None or not retained(saved[0]):
            return None
        cursor, state = saved
        try:
            seen, open_, settled, assignees = (
                stream_id(cursor),
                dict(state["open"]),
                dict(state["settled"]),
                dict(state["assignees"]),
            )
        except KeyError, TypeError, ValueError:
            logger.warning("StarPulse: the Board saved for %s cannot be read, replaying instead", stream)
            return None
        with self._lock:
            self._open, self._settled, self._assignees, self._seen, self._saved = open_, settled, assignees, seen, seen
        return cursor

    def save(self) -> None:
        """Write the Board and the cursor it reflects to the store `resume` was given, unless the feed has read
        nothing since the last save. A store that cannot be written is logged; the next save tries again."""
        if self._store is None:
            return
        store, stream = self._store
        with self._lock:
            if self._seen == self._saved:
                return
            seen = self._seen
            state = {"open": dict(self._open), "settled": dict(self._settled), "assignees": dict(self._assignees)}
        try:
            store.save_board_state(stream, "-".join(map(str, seen)), state)
        except Exception as exc:  # the store is down; the Board still draws and the next save retries
            logger.warning("StarPulse: cannot save the Board of %s: %s", stream, exc)
            return
        self._saved = seen

    def keep_saved(self, stop: threading.Event, interval: float = SAVE_INTERVAL) -> None:
        """Save every `interval` seconds, and once more when `stop` is set."""
        while not stop.wait(interval):
            self.save()
        self.save()

    def put(self, task: BoardTask) -> None:
        """Place a task the board contract describes; one outside the adapter's key scheme is dropped."""
        if self._keys is not None and not self._keys.matches(task.id):
            return
        with self._lock:
            self._assignees[task.id] = task.assignee
            agent = None if task.settled else task_agent(task)
            before = self._open.get(task.id)
            if agent and before:
                # the lane the task left on its last move, kept while the hourly reconcile republishes it in place
                previous = before["state"] if before["state"] != agent["state"] else before.get("previous")
                if previous:
                    agent["previous"] = previous
            if before == agent and self._settled.get(task.id) == task.settled:
                return  # an hourly reconcile republishes every task; only a change reaches the page
            if agent is None:
                self._open.pop(task.id, None)
                if task.settled:
                    self._settled[task.id] = task.settled
            else:
                self._open[task.id] = agent
                self._settled.pop(task.id, None)
            self._publish("task", {"id": task.id, "agent": agent, "settled": task.settled})

    def pull_requests(self) -> dict[str, list[str]]:
        """Each open task's pull request links, for the tasks that cite any."""
        with self._lock:
            return {task: list(agent["prs"]) for task, agent in self._open.items() if agent["prs"]}

    def set_pulls(self, pulls: dict[str, list[dict]]) -> None:
        """Take each task's pull request state and publish it when it differs from before."""
        with self._lock:
            if pulls == self._pulls:
                return
            self._pulls = pulls
            self._publish("pulls", {"pulls": pulls})

    def refuse_claim(self, task: str, reason: str, at: float) -> None:
        """Keep the board writer's latest refusal of an agent's claim on `task` and publish it."""
        with self._lock:
            self._claims[task] = {"reason": reason, "at": at}
            self._publish("claim", {"task": task, "reason": reason, "at": at})

    def task(self, task_id: str) -> dict | None:
        """The open Board task as the page draws it, or None when the Board holds no open task by that id."""
        with self._lock:
            return self._open.get(task_id)

    def machine_task(self, flow: str, task_id: str) -> dict | None:
        """The task as `flow`'s machine last placed it, or None when it has not been placed there."""
        with self._lock:
            return self._machines[flow].get(task_id)

    def move(self, flow: str, agent: dict) -> None:
        """Place a task on a machine other than the Board and publish the move."""
        with self._lock:
            self._machines[flow][agent["id"]] = agent
            self._publish("move", {"flow": flow, "id": agent["id"], "agent": self._modelled(agent)})

    def _modelled(self, agent: dict) -> dict:
        """A machine's task with its Board task's assignee as its model when it carries none of its own."""
        return {**agent, "model": agent["model"] or self._assignees.get(agent["task"], "")}

    def await_stream(self) -> None:
        """Say the stream has not been reached yet, so a page shows that instead of an empty Board."""
        with self._lock:
            self._awaiting = True

    def runs(self, instance: str) -> InstanceRuns:
        """Where the runs adapter instance `instance` publishes its workflows."""
        return InstanceRuns(self, instance)

    def set_dags(self, instance: str, dags: list | None, error: str | None, pools: list | None = None) -> None:
        """Take the latest workflows and concurrency pools of `instance` (None keeps the last of each) and publish
        them when they differ from before; an empty `pools` says the instance now reports none."""
        with self._lock:
            dags = self._dags.get(instance, []) if dags is None else dags
            pools = self._pools.get(instance, []) if pools is None else pools
            if (dags, error, pools) == (
                self._dags.get(instance),
                self._runs_errors.get(instance),
                self._pools.get(instance, []),
            ):
                return
            self._dags[instance] = dags
            self._pools[instance] = pools
            if error is None:
                self._runs_errors.pop(instance, None)
            else:
                self._runs_errors[instance] = error
            self._publish("dags", {"dags": self._workflows(), "pools": self._drawn_pools(), "error": self._error()})

    def _workflows(self) -> list[dict]:
        """Every instance's workflows, each named `<instance>/<workflow>`; a pushed one an adapter lists is drawn by that adapter."""
        listed = {dag["name"] for instance, dags in self._dags.items() if instance != PUSHED_INSTANCE for dag in dags}
        return [
            {**dag, "name": f"{instance}/{dag['name']}"}
            | ({"pool": f"{instance}/{dag['pool']}"} if dag.get("pool") else {})
            for instance, dags in self._dags.items()
            for dag in dags
            if instance != PUSHED_INSTANCE or dag["name"] not in listed
        ]

    def _drawn_pools(self) -> list[dict]:
        """Every instance's concurrency pools, each named `<instance>/<pool>` like the `pool` a workflow names."""
        return [
            {**pool, "name": f"{instance}/{pool['name']}"} for instance, pools in self._pools.items() for pool in pools
        ]

    def _error(self) -> str | None:
        if self._awaiting and not self.ready.is_set():
            return f"board: reading {self._source}"
        return "; ".join(f"{instance}: {error}" for instance, error in self._runs_errors.items()) or None

    def _publish(self, kind: str, data: dict) -> None:
        if kind in ("task", "move") and self._replaying():
            return  # a replayed step is history, not a move to draw: the snapshot once the stream is read carries its result
        for subscriber in self._subscribers:
            subscriber.put((kind, data))

    def subscribe(self) -> tuple[dict[str, Any], queue.Queue]:
        """The snapshot now and the queue of every change after it."""
        with self._lock:
            subscriber: queue.Queue = queue.Queue()
            self._subscribers.append(subscriber)
            return self.snapshot(), subscriber

    def unsubscribe(self, subscriber: queue.Queue) -> None:
        with self._lock:
            self._subscribers.remove(subscriber)

    def snapshot(self) -> dict[str, Any]:
        """What the page draws: every machine with its tasks, the workflow declarations, the workflows and their pools."""
        with self._lock:
            since = time.time() - self._window_s if self._window_s is not None else None
            return {
                "graphs": [*self._drawn, "runs"],
                "flows": [
                    {"name": "board", "machine": self._drawn["board"], "agents": list(self._open.values())},
                    *(
                        {
                            "name": name,
                            "machine": self._drawn[name],
                            "agents": [
                                self._modelled(a) for a in agents.values() if since is None or a["active"] >= since
                            ],
                        }
                        for name, agents in self._machines.items()
                    ),
                ],
                "dags": self._workflows(),
                "pools": self._drawn_pools(),
                "pulls": self._pulls,
                "claims": dict(self._claims),
                "capabilities": dict(self._capabilities),
                "settled": dict(self._settled),
                "error": self._error(),
                "reading": self._replaying(),
                **declared(self._domains, self._run_safe, self._cues),
                "boardUrl": self._board_url,
                "hint": self._hint,
                "now": time.time(),
            }


class InstanceRuns:
    """The feed as one runs adapter instance sees it: it publishes its workflows and errors under its own name."""

    def __init__(self, feed: BoardFeed, instance: str) -> None:
        self._feed = feed
        self._instance = instance

    def set_dags(self, dags: list | None, error: str | None, pools: list | None = None) -> None:
        self._feed.set_dags(self._instance, dags, error, pools)


class Followed(Protocol):
    """What `follow` needs of a feed: to be told the stream is not reached yet and where it ends."""

    def await_stream(self) -> None: ...

    def expect(self, last_id: str) -> None: ...


@runtime_checkable
class Resumable(Protocol):
    """A feed that keeps its state across restarts (`BoardFeed`), so a reader of its stream resumes after a cursor."""

    def resume(self, store: BoardStore, stream: str, retained: Callable[[str], bool]) -> str | None: ...

    def keep_saved(self, stop: threading.Event, interval: float = ...) -> None: ...


def _retained(log: EventLog, stream: str) -> Callable[[str], bool]:
    """Whether the log still holds every `stream` row after a saved cursor: `Tail`'s gap rule, and a cursor the log
    has not reached yet (the database was replaced) is no cursor of this log."""

    def retained(cursor: str) -> bool:
        after = stream_id(cursor)[0]
        oldest = log.oldest()
        return oldest is not None and oldest - 1 <= after <= (log.last(stream) or 0)

    return retained


def follow(
    feed: Followed,
    log: EventLog,
    stream: str,
    handle: Callable[[str, dict], None],
    *,
    stop: threading.Event | None = None,
    interval: float = DEFAULT_POLL_INTERVAL,
) -> threading.Thread:
    """Read `stream` of the event log into `feed` through `handle(entry_id, fields)` on a daemon thread and return it.

    A feed that keeps its state (`Resumable`) restores the Board the last run saved in the log and reads only the
    entries after the cursor it reflects, then keeps saving it until `stop`. With no saved Board, or one the log no
    longer covers, the feed replays from the oldest entry the log retains: hourly reconciles keep the latest state
    of every task inside the retention. The feed turns ready once the newest entry `stream` held when it started
    has been read. While the database cannot be reached the feed is not ready and the start retries every
    `interval`; a later outage is `Tail.run`'s to retry. `stop` ends the reader.
    """
    feed.await_stream()
    stop = stop or threading.Event()

    def run() -> None:
        after = None
        while not stop.is_set():
            try:
                last = log.last(stream)
                if isinstance(feed, Resumable):
                    after = feed.resume(log, stream, _retained(log, stream))
                break
            except Exception as exc:  # the database is unreachable; the next attempt retries
                logger.warning("StarPulse: cannot reach the event log for %s, retrying: %s", stream, exc)
                stop.wait(interval)
        else:
            return
        feed.expect(str(last) if last else "0-0")
        if isinstance(feed, Resumable):
            threading.Thread(target=feed.keep_saved, args=(stop,), name="board-state", daemon=True).start()
        # no cursor replays the whole retention
        tail = Tail(log, stream, after=None if after is None else stream_id(after)[0], interval=interval)
        tail.run(lambda entry: handle(str(entry.id), entry.fields), stop)

    thread = threading.Thread(target=run, name="board-feed", daemon=True)
    thread.start()
    return thread
