"""What StarPulse draws, held in memory and kept current by the adapters.

The board adapter (`starpulse.board`) places each Board task here, the server keeps each task's latest state,
and every connected page gets one snapshot and then a delta per change. Each other machine's tasks arrive from
`machine:events` (`machine_tasks`), and each runs adapter instance's workflows from its adapter module.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from collections.abc import Collection, Mapping, Sequence
from typing import Any, Protocol

import redis.exceptions

from starpulse.contracts import BoardTask, TaskKeys
from starpulse.snapshot import declared
from starpulse.streams import StreamConsumer
from starpulse.upstream_backlog import DEFAULT_STATUSES, board_machine

logger = logging.getLogger(__name__)

_PULL_REQUEST = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+/?")
# The runs instance pushed workflows belong to, so the page names them `pushed/<workflow>`.
PUSHED_INSTANCE = "pushed"


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
    ) -> None:
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
        self._runs_errors: dict[str, str] = {}
        self._pulls: dict[str, list[dict]] = {}
        #: Each task's latest refused claim (a board adapter's `refuse_claim` call): its reason and when the writer refused it.
        self._claims: dict[str, dict] = {}
        self._subscribers: list[queue.Queue] = []
        self._awaiting = False  # pragma: no mutate — None is falsy too
        self._expected: tuple[int, int] | None = None
        self._seen = (0, 0)
        #: Set once the stream has been read up to the last entry it held when the feed started.
        self.ready = threading.Event()

    @property
    def machines(self) -> Mapping[str, dict]:
        """The machines the page draws, the Board's as `board`."""
        return self._drawn

    def expect(self, last_id: str) -> None:
        """Mark the feed ready once the entry `last_id` has been read; `0-0` is an empty stream."""
        with self._lock:
            self._awaiting = True
            self._expected = stream_id(last_id)
            self._check_ready()

    def _check_ready(self) -> None:
        if self._expected is not None and self._seen >= self._expected:
            self.ready.set()

    def seen(self, entry_id: str) -> None:
        """Note that a board adapter reading a stream has read up to the entry `entry_id`."""
        with self._lock:
            self._seen = max(self._seen, stream_id(entry_id))
            self._check_ready()

    def put(self, task: BoardTask) -> None:
        """Place a task the board contract describes; one outside the adapter's key scheme is dropped."""
        if self._keys is not None and not self._keys.matches(task.id):
            return
        with self._lock:
            self._assignees[task.id] = task.assignee
            agent = None if task.settled else task_agent(task)
            if self._open.get(task.id) == agent and self._settled.get(task.id) == task.settled:
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

    def set_dags(self, instance: str, dags: list | None, error: str | None) -> None:
        """Take the latest workflows of `instance` (None keeps its last) and publish them when they differ from before."""
        with self._lock:
            dags = self._dags.get(instance, []) if dags is None else dags
            if (dags, error) == (self._dags.get(instance), self._runs_errors.get(instance)):
                return
            self._dags[instance] = dags
            if error is None:
                self._runs_errors.pop(instance, None)
            else:
                self._runs_errors[instance] = error
            self._publish("dags", {"dags": self._workflows(), "error": self._error()})

    def _workflows(self) -> list[dict]:
        """Every instance's workflows, each named `<instance>/<workflow>`; a pushed one an adapter lists is drawn by that adapter."""
        listed = {dag["name"] for instance, dags in self._dags.items() if instance != PUSHED_INSTANCE for dag in dags}
        return [
            {**dag, "name": f"{instance}/{dag['name']}"}
            for instance, dags in self._dags.items()
            for dag in dags
            if instance != PUSHED_INSTANCE or dag["name"] not in listed
        ]

    def _error(self) -> str | None:
        if self._awaiting and not self.ready.is_set():
            return f"board: reading {self._source}"
        return "; ".join(f"{instance}: {error}" for instance, error in self._runs_errors.items()) or None

    def _publish(self, kind: str, data: dict) -> None:
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
        """What the page draws: every machine with its tasks, the workflow declarations, and the workflows."""
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
                "pulls": self._pulls,
                "claims": dict(self._claims),
                "settled": dict(self._settled),
                "error": self._error(),
                **declared(self._domains, self._run_safe, self._cues),
                "boardUrl": self._board_url,
                "now": time.time(),
            }


class RunsSink(Protocol):
    """Where a runs adapter publishes the workflows of its one instance, and says when it cannot read them."""

    def set_dags(self, dags: list | None, error: str | None) -> None: ...


class InstanceRuns:
    """The feed as one runs adapter instance sees it: it publishes its workflows and errors under its own name."""

    def __init__(self, feed: BoardFeed, instance: str) -> None:
        self._feed = feed
        self._instance = instance

    def set_dags(self, dags: list | None, error: str | None) -> None:
        self._feed.set_dags(self._instance, dags, error)


class Followed(Protocol):
    """What `follow` needs of a feed: to be told the stream is not reached yet and where it ends."""

    def await_stream(self) -> None: ...

    def expect(self, last_id: str) -> None: ...


def follow(feed: Followed, consumer: StreamConsumer) -> threading.Thread:  # pragma: no mutate block — Redis retry loop
    """Read the whole retained stream into `feed` on a daemon thread and return it.

    The feed lives in memory, so every start replays the stream from its first entry: the group is
    dropped, then recreated at `0` by the consumer. Hourly reconciles keep the latest state of
    every task inside the stream's retention. The feed turns ready once the entry that was last
    when it started has been read.
    """
    feed.await_stream()

    def run() -> None:
        while True:
            try:
                client = consumer.connect()
                try:
                    client.xgroup_destroy(consumer.stream, consumer.group)
                except redis.exceptions.ResponseError:
                    pass  # no stream yet, so no group to drop
                last = client.xrevrange(consumer.stream, count=1)
                feed.expect(str(last[0][0]) if last else "0-0")
                break
            except redis.exceptions.RedisError as exc:
                logger.warning("StarPulse: cannot reach %s, retrying: %s", consumer.stream, exc)
                time.sleep(consumer.reconnect_delay)
        consumer.run_forever()

    thread = threading.Thread(target=run, name="board-feed", daemon=True)
    thread.start()
    return thread
