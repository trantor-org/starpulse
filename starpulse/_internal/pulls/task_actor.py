"""The task actor: a task advances itself on the facts its lane waits on.

A machine state's `waits` name a fact kind and the event that leaves the state when the fact holds
(`machine_definition.WAIT_FACTS`). The actor keeps a `PR -> tasks` and a `task -> dependents` index, so one change
touches only the tasks naming it, and when a task's pull request state, its own lane or a dependency's changes it
re-derives that task's waits and writes the first that holds through the board's task editor as `starpulse/task-actor`.
The board's rules and the machine's guards judge the write like any other. A write the board refuses is logged and
counted, and not tried again until the task's facts change. A start re-derives every open task once, which is the
recovery for a change that happened while the server was down.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from starpulse._internal.board.seam import TaskEditor, Written
from starpulse._internal.config.config import Repo
from starpulse._internal.config.pins import Pins
from starpulse._internal.feed import criteria
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.pulls.pull_requests import PULL_URL
from starpulse._internal.pulls.pulls import PullStore
from starpulse._internal.pulls.release import Settlement

logger = logging.getLogger(__name__)

__all__ = ["ACTOR", "TaskActor", "moves_of"]

#: The actor every write of the task actor names.
ACTOR = "starpulse/task-actor"
#: The pull request states that end a pull request.
_TERMINAL = ("MERGED", "CLOSED")
REFUSALS_METRIC = "starpulse_task_actor_refusals_total"
LATENCY_METRIC = "starpulse_task_actor_latency_seconds"
#: The upper bounds of the latency histogram's buckets, in seconds; the count past the last is the `+Inf` bucket's.
BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
#: Seconds the event loop waits for a change before it looks at its stop flag.
_POLL_S = 0.5


def moves_of(machine: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """`{(lane, event): target lane}` for the transitions of a drawn machine (`snapshot.describe`)."""
    return {(move["source"], move["event"]): move["target"] for move in machine["transitions"]}


class TaskActor:
    """Moves each open task whose lane waits on a fact that holds, once per change of that fact.

    `waits` is `{lane: {fact kind: event}}` (`Compiled.waits`) and `moves` is `{(lane, event): target lane}`, from the
    Board machine's transitions. `edit` is the board's task editor. `repos`, `settle` and `pins` are the `[release]`
    settle rule (`release.Settlement`): a dependency in a pinned repository settles on the parent's pin bump.
    """

    def __init__(
        self,
        feed: BoardFeed,
        store: PullStore,
        edit: TaskEditor,
        waits: Mapping[str, Mapping[str, str]],
        moves: Mapping[tuple[str, str], str],
        repos: Sequence[Repo] = (),
        settle: str | None = None,
        pins: Pins | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._feed = feed
        self._store = store
        self._edit = edit
        self._waits = waits
        self._moves = moves
        self._clock = clock
        self._settlement = Settlement(feed, store, repos, settle, pins)
        self._lock = threading.RLock()
        #: Each open task's lane, dependencies and pull requests as the actor last saw them.
        self._seen: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {}
        self._by_pr: dict[str, set[str]] = {}
        #: What each pull request last read as, so a refresh that changed nothing derives nothing.
        self._pull_states: dict[str, tuple[str, str | None]] = {}
        #: Tasks whose dependencies are done but wait for a pin bump, and the store revision last read for them.
        self._pin_held: set[str] = set()
        self._store_rev = store.rev
        #: The move last tried for each task, until the task changes lane: the same facts are not tried twice.
        self._tried: dict[str, tuple] = {}
        self._metrics = threading.Lock()
        self._refusals = 0
        #: How many writes landed within each bound of `BUCKETS_S`, then how many in all, and their seconds summed.
        self._buckets = [0] * (len(BUCKETS_S) + 1)
        self._sum = 0.0
        #: Set once the start's derivation of every open task is done.
        self.ready = threading.Event()
        #: How many times each task's waits were derived, for the tests and a diagnosis.
        self.derivations: Counter[str] = Counter()

    def exposition(self) -> str:
        """Prometheus text of the writes the board refused and of how long a fact took to become a landed write."""
        with self._metrics:
            counts, total, refusals = list(self._buckets), self._sum, self._refusals
        samples = [
            f'{LATENCY_METRIC}_bucket{{le="{bound:g}"}} {count}' for bound, count in zip(BUCKETS_S, counts, strict=False)
        ]
        return "\n".join(
            [
                f"# HELP {REFUSALS_METRIC} Writes the board refused to the task actor.",
                f"# TYPE {REFUSALS_METRIC} counter",
                f"{REFUSALS_METRIC} {refusals}",
                f"# HELP {LATENCY_METRIC} Seconds from the task actor observing a fact to its write landing.",
                f"# TYPE {LATENCY_METRIC} histogram",
                *samples,
                f'{LATENCY_METRIC}_bucket{{le="+Inf"}} {counts[-1]}',
                f"{LATENCY_METRIC}_sum {total:g}",
                f"{LATENCY_METRIC}_count {counts[-1]}",
                "",
            ]
        )

    def start(self, stop: threading.Event) -> threading.Thread:
        """Follow the feed on a daemon thread until `stop` is set."""
        thread = threading.Thread(target=self._run, args=(stop,), name="task-actor", daemon=True)
        thread.start()
        return thread

    def _run(self, stop: threading.Event) -> None:
        self._feed.wait_replayed()
        _, changes = self._feed.subscribe()
        with self._lock:
            observed = self._clock()
            tasks = self._feed.open_tasks()
            for agent in tasks:
                self._index(agent)
            self._read_pulls()
            self._derive_all([agent["id"] for agent in tasks], observed)
        self.ready.set()
        while not stop.is_set():
            try:
                kind, data = changes.get(timeout=_POLL_S)
            except queue.Empty:
                continue
            if kind == "task":
                try:
                    self._changed(data)
                except Exception:  # one change must not end the actor
                    logger.exception("task actor: cannot handle the change of %s", data.get("id"))

    def _index(self, agent: dict[str, Any]) -> None:
        """Take `agent`'s lane, dependencies and pull requests into the indexes."""
        name = agent["id"]
        for url in self._seen.get(name, ("", (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._seen[name] = (agent["state"], tuple(agent["dependencies"]), tuple(agent["prs"]))
        for url in agent["prs"]:
            self._by_pr.setdefault(url, set()).add(name)

    def _changed(self, data: dict[str, Any]) -> None:
        """Re-derive what a change of one task's record touches: the task itself when its lane, dependencies or pull
        requests changed, and the tasks depending on it when its lane did."""
        observed = self._clock()
        name, agent = data["id"], data["agent"]
        with self._lock:
            before = self._seen.get(name)
            if agent is None:  # settled or gone: the tasks that waited on it may now proceed
                self._forget(name)
                self._derive_all(self._dependents(name), observed)
                return
            if before == (now := (agent["state"], tuple(agent["dependencies"]), tuple(agent["prs"]))):
                return
            self._index(agent)
            touched = {name}
            if before is None or before[0] != now[0]:
                self._tried.pop(name, None)
                touched |= self._dependents(name)
            self._derive_all(touched, observed)

    def _forget(self, name: str) -> None:
        for url in self._seen.pop(name, ("", (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._tried.pop(name, None)

    def _dependents(self, name: str) -> set[str]:
        return {other for other, (_, dependencies, _) in self._seen.items() if name in dependencies}

    def pulls_changed(self) -> None:
        """Re-derive the tasks whose pull requests read differently since the last call; the server calls it after each
        projection of the pull request store."""
        observed = self._clock()
        with self._lock:
            touched = self._read_pulls()
            if self._store.rev != self._store_rev:  # a pin bump is no pull request any task cites
                self._store_rev = self._store.rev
                touched |= self._pin_held
            self._derive_all(touched, observed)

    def _read_pulls(self) -> set[str]:
        """The tasks citing a pull request whose state changed since it was last read."""
        touched: set[str] = set()
        for url, names in self._by_pr.items():
            if self._pull_states.get(url) != (state := self._pull_state(url)):
                self._pull_states[url] = state
                touched |= names
        return touched

    def _record(self, url: str) -> dict[str, Any] | None:
        found = PULL_URL.fullmatch(url)
        records = self._store.find(repo=found[1], number=int(found[2])) if found else []
        return records[0] if records else None

    def _pull_state(self, url: str) -> tuple[str, str | None]:
        record = self._record(url)
        return (record["state"], record["mergeSha"]) if record else ("", None)

    def _derive_all(self, names: Any, observed: float) -> None:
        for name in sorted(names):
            self._derive(name, observed)

    def _derive(self, name: str, observed: float) -> None:
        """Write the first move the task's lane waits on whose fact holds."""
        agent = self._feed.task(name)
        if agent is None:
            return
        self.derivations[name] += 1
        for fact, event in self._waits.get(agent["state"], {}).items():
            target = self._moves.get((agent["state"], event))
            held = self._facts.get(fact, lambda *_: None)(self, agent) if target else None
            if held is None:
                continue
            evidence, comment = held
            sent = (agent["state"], event, evidence)
            if self._tried.get(name) != sent:
                self._tried[name] = sent
                self._write(name, target, comment, observed)
            return

    def _write(self, name: str, target: str, comment: str, observed: float) -> None:
        self._feed.note_actor(name, ACTOR)
        try:
            written = self._edit(name, {"status": target}, comment, actor=ACTOR)
        except Exception as error:  # a board that raises refuses like one that answers no
            written = Written(False, str(error))
        if written.ok:
            self._landed(self._clock() - observed)
            return
        logger.warning("task actor: %s was not moved to %s: %s", name, target, written.output)
        self._feed.note_actor(name, None)
        with self._metrics:
            self._refusals += 1

    def _landed(self, seconds: float) -> None:
        with self._metrics:
            at = next((i for i, bound in enumerate(BUCKETS_S) if seconds <= bound), len(BUCKETS_S))
            for i in range(at, len(self._buckets)):
                self._buckets[i] += 1
            self._sum += seconds

    def _pr_terminal(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The merge evidence when the task cites pull requests and every one has ended, else None."""
        parts = []
        for url in agent["prs"]:
            record = self._record(url)
            if record is None or record["state"] not in _TERMINAL:
                return None
            part = f"{record['repo']}#{record['number']} {record['state'].lower()}"
            if record["mergeSha"]:
                part += f" as {record['mergeSha']}"
            parts.append(f"{part} (PR #{record['number']})")
        if not parts:
            return None
        proof = "; ".join(parts)
        return proof, f"Closed on merge evidence: {proof}"

    def _deps_done(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The dependencies when the task has some, every one is done and settled, and no Start Criteria gate it."""
        dependencies = tuple(agent["dependencies"])
        self._pin_held.discard(agent["id"])
        if not dependencies or not all(map(self._feed.is_done, dependencies)) or criteria.authored(agent["description"]):
            return None
        if self._settlement.unapplied(agent):
            self._pin_held.add(agent["id"])
            return None
        return dependencies, "Every dependency has settled."

    def _deps_unresolved(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The dependencies that are not done, when there are any."""
        open_ = tuple(dependency for dependency in agent["dependencies"] if not self._feed.is_done(dependency))
        return (open_, f"Not done: {', '.join(open_)}.") if open_ else None

    _facts: dict[str, Callable[[TaskActor, dict[str, Any]], tuple[Any, str] | None]] = {
        "pr_terminal": _pr_terminal,
        "deps_done": _deps_done,
        "deps_unresolved": _deps_unresolved,
    }
