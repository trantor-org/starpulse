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
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from starpulse import criteria
from starpulse.analytics import LaneRow, move_shares
from starpulse.contracts.adapters import BoardTask, TaskKeys
from starpulse.domain.machine_ties import derive, entries
from starpulse.domain.machine_ties import page as machine_page
from starpulse.domain.snapshot import declared, qualifier
from starpulse.ledger import (
    MERGE_EVENT,
    NEXT,
    PAGE,
    STRIP_BUCKET,
    Occurrence,
    build,
    page,
    pull_occurrences,
    reruns,
    strip,
)
from starpulse.settings.config import CommitKeys
from starpulse.store.event_log import DEFAULT_POLL_INTERVAL, EventLog, Tail
from starpulse.upstream_backlog import DEFAULT_STATUSES, board_machine, lane_id

__all__ = ["BoardFeed", "BoardStore", "Followed", "Resumable"]

logger = logging.getLogger(__name__)

_PULL_REQUEST = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/pull/\d+/?")
# The runs instance pushed workflows belong to, so the page names them `pushed/<workflow>`.
PUSHED_INSTANCE = "pushed"
#: How often a running reader saves the Board, in seconds; a restart reads again what arrived since.
SAVE_INTERVAL = 60.0
#: The days of lane moves, before local midnight, a Board state's sun is sized from.
SUN_DAYS = 7
#: Seconds between looks for a local midnight that has passed.
SUN_INTERVAL = 60.0
#: Seconds between passes that evaluate the Start Criteria of the Waiting tasks, as long as the evaluator caches a result.
CRITERIA_INTERVAL = criteria.CACHE_SECONDS
#: The lanes a task's workability reads: it can wait on Start Criteria in one, and a dependency is done in the other.
WAITING, DONE = "waiting", "done"
#: How far back a task's entry into a lane is an occurrence a run can pair with, in seconds: as far as a tied workflow's recent runs reach.
LEDGER_WINDOW = 86400.0


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
        "created": task.created_at,
    }


def settled_entry(task: BoardTask) -> dict | None:
    """Where a settled task settled, when, and the title and assignee it settled with; None for an open task."""
    if not task.settled:
        return None
    return {
        "state": task.settled,
        "at": task.settled_at,
        "created": task.created_at,
        "title": task.title,
        "model": task.assignee,
    }


def stream_id(entry_id: str) -> tuple[int, int]:
    """A stream id as numbers: `10-0` follows `9-0`, which text order gets backwards."""
    millis, _, sequence = entry_id.partition("-")
    return int(millis), int(sequence or 0)


class LaneRecorder(Protocol):
    """Where a feed keeps each lane change it applies, idempotent on the event id (`HistoryStore`)."""

    def record_lane(self, event_id: str, task: str, status: str, at: float) -> None: ...


class BoardStore(Protocol):
    """Where a feed keeps the Board it saved: the event log, or any store that holds one state per stream."""

    def load_board_state(self, stream: str) -> tuple[str, dict] | None: ...

    def save_board_state(self, stream: str, cursor: str, state: dict) -> None: ...


class CriteriaStore(Protocol):
    """Where the feed keeps when each task's Start Criteria were first seen all met (`HistoryStore`)."""

    def criteria_met(self) -> dict[str, float]: ...

    def save_criteria_met(self, met: dict[str, float]) -> None: ...


class BoardFeed:
    """Each task's latest projected state, as the page's Board snapshot and the deltas after it.

    Entries arrive on the consumers' threads and pages read from request threads; one lock holds
    them apart, and a subscriber takes its snapshot and its queue under that lock so no change
    falls between the two. A machine's task whose latest move is older than `window_s` seconds
    (None: never) is left out of a snapshot. `board_url` is the tracker's address the page links tasks
    to (None: no links). `machines` are the machines the page draws, the Board's as `board` (None: a Board of
    Backlog.md's default statuses alone), and `cues` the board adapter's workflow cues. `domains` and `run_safe`
    are the config's, each workflow as `<instance>/<workflow>`. `source` names what the Board is read from, for the
    page to show until the board adapter has read it. `commit` is each runs instance's `[runs.commit]` keys, by instance
    name: they say which run parameters carry a merge's commit or a task, so the Ledger pairs a run with it for certain.

    Each open task carries `workable` and `workable_since`. A task is workable unless a dependency is not done (completed,
    or in the `done` lane) or it waits on Start Criteria that are not all met; it is then workable since the latest of
    when it entered its lane, when each dependency was done and when `evaluate_criteria` first saw its criteria all met.
    A task that is not workable has `workable_since` None.
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
        commit: Mapping[str, CommitKeys] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._hint = hint
        self._clock = clock
        #: A task's lane changes as the history keeps them (`History.lane_path`), read while the feed replays.
        self._lane_path: Callable[[str], list[dict]] = lambda _task: []
        #: Where a lane change the feed applies is kept (`HistoryStore`); None records nothing.
        self._lanes: LaneRecorder | None = None
        self._capabilities = {"edit": False, "archive": False, "create": False} | dict(capabilities or {})
        self._keys = keys
        self._domains = domains or {}
        self._run_safe = run_safe
        self._cues = cues
        self._source = source
        self._drawn = machines if machines is not None else {"board": board_machine(DEFAULT_STATUSES)}
        self._board_url = board_url
        self._commit = commit or {}
        self._ties = self._tied_to_events(cues)
        qualify = qualifier(self._domains)
        #: How a failure of each workflow a machine event cues resolves, by `(event, workflow)`; any other resolves on its next success.
        self._resolves = {
            (cue["event"], qualify(cue["dag"])): cue["resolves"] for cue in cues if "event" in cue and "resolves" in cue
        }
        #: The Ledger as last published, so a change to it is sent once.
        self._ledgers: dict[str, list[dict]] = {}
        self._strip: dict | None = None
        self._pins: list[dict] = []
        self._lock = threading.RLock()
        self._window_s = window_s
        self._open: dict[str, dict] = {}
        self._machines: dict[str, dict[str, dict]] = {name: {} for name in self._drawn if name != "board"}
        self._settled: dict[str, dict] = {}
        #: Every placed task's assignee, a settled one's included, so a machine still drawing it keeps its colour.
        self._assignees: dict[str, str] = {}
        self._dags: dict[str, list] = {}
        self._pools: dict[str, list] = {}
        #: The workflows each instance's adapter reported it can start; an instance not here can start all it has.
        self._startable: dict[str, frozenset[str]] = {}
        self._runs_errors: dict[str, str] = {}
        self._pulls: dict[str, list[dict]] = {}
        #: What the pull request reader learned from GitHub (`PullRequests.answers`), saved so a restart reads warm.
        self._pull_answers: dict = {}
        self._pulls_unsaved = False
        #: Each task's latest refused claim (a board adapter's `refuse_claim` call): its reason and when the writer refused it.
        self._claims: dict[str, dict] = {}
        #: The findings an engine posted that are live, by id, as the contract's JSON (`put_insight`).
        self._insights: dict[str, dict] = {}
        #: The Waiting tasks whose description declares Start Criteria, and for each task the open tasks that list it as a dependency.
        self._gated: set[str] = set()
        self._dependents: dict[str, set[str]] = {}
        #: When each gated task's criteria were first seen all met, kept while they stay met; a task not here has unmet criteria.
        self._met: dict[str, float] = {}
        self._evaluate: Callable[[str, str], list[dict]] = criteria.unevaluated
        self._criteria_store: CriteriaStore | None = None
        self._subscribers: list[queue.Queue] = []
        self._awaiting = False  # pragma: no mutate — None is falsy too
        self._expected: tuple[int, int] | None = None
        self._seen = (0, 0)
        self._saved = (0, 0)
        self._store: tuple[BoardStore, str] | None = None
        self._lane_rows: Callable[..., list[LaneRow]] | None = None
        #: The local midnight the suns were last sized at, and the shares it gave them.
        self._sized: tuple[datetime | None, dict[str, float]] = (None, {})
        #: Set once the stream has been read up to the last entry it held when the feed started.
        self.ready = threading.Event()

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
        return frozenset(dag.removeprefix(prefix) for dags in self._ties.values() for dag in dags if dag.startswith(prefix))

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
        feed saves to `store` under `stream` from now on (`save`, `keep_saved`). One line says which start it was:
        `resuming after <cursor>` or `replaying: <reason>`, at WARNING because nothing configures a lower level.
        """
        self._store = (store, stream)
        saved = store.load_board_state(stream)
        if saved is None:
            logger.warning("StarPulse: replaying: no saved Board")
            return None
        if not retained(saved[0]):
            logger.warning("StarPulse: replaying: cursor %s is no longer retained", saved[0])
            return None
        cursor, state = saved
        try:
            seen, open_, settled, assignees, pulls, answers = (
                stream_id(cursor),
                dict(state["open"]),
                dict(state["settled"]),
                dict(state["assignees"]),
                dict(state.get("pulls", {})),  # a Board saved before pull requests were kept has none
                dict(state.get("pull_answers", {})),
            )
            if not all(isinstance(entry, dict) for entry in settled.values()):
                raise TypeError("a settled task saved before settled entries carried their time")
        except KeyError, TypeError, ValueError:
            logger.warning("StarPulse: replaying: the saved Board cannot be read")
            return None
        with self._lock:
            self._open, self._settled, self._assignees, self._seen, self._saved = open_, settled, assignees, seen, seen
            self._pulls, self._pull_answers = pulls, answers
        logger.warning("StarPulse: resuming after %s", cursor)
        return cursor

    def save(self) -> None:
        """Write the Board and the cursor it reflects to the store `resume` was given, unless the feed has read
        nothing since the last save. A store that cannot be written is logged; the next save tries again."""
        if self._store is None:
            return
        store, stream = self._store
        with self._lock:
            if self._seen == self._saved and not self._pulls_unsaved:
                return
            seen = self._seen
            state = {
                "open": dict(self._open),
                "settled": dict(self._settled),
                "assignees": dict(self._assignees),
                "pulls": dict(self._pulls),
                "pull_answers": dict(self._pull_answers),
            }
        try:
            store.save_board_state(stream, "-".join(map(str, seen)), state)
        except Exception as exc:  # the store is down; the Board still draws and the next save retries
            logger.warning("StarPulse: cannot save the Board of %s: %s", stream, exc)
            return
        self._saved, self._pulls_unsaved = seen, False

    def pull_answers(self) -> dict:
        """What the pull request reader last handed `set_pulls`, as saved; empty when nothing was."""
        with self._lock:
            return dict(self._pull_answers)

    def keep_saved(self, stop: threading.Event, interval: float = SAVE_INTERVAL) -> None:
        """Save every `interval` seconds, and once more when `stop` is set."""
        while not stop.wait(interval):
            self.save()
        self.save()

    def date_lanes(self, lane_path: Callable[[str], list[dict]]) -> None:
        """Date a lane the feed replays by the history's last change into it (`History.lane_path`), not by the replay."""
        self._lane_path = lane_path

    def record_lanes(self, lanes: LaneRecorder) -> None:
        """Keep each lane change the feed applies in `lanes` (`HistoryStore.record_lane`).

        The event id names the task, the lane and when it entered it, so a replay of a change the history holds
        repeats nothing. A history that cannot be written is logged: the task is still placed.
        """
        self._lanes = lanes

    def size_suns(self, lane_rows: Callable[..., list[LaneRow]]) -> None:
        """Size each Board state's sun from its share of the lane moves in the week before local midnight, read through
        `lane_rows` (`LaneHistory.lane_rows`). The shares are worked out once a day, the first time a snapshot is
        taken after midnight, so a move made since then changes none until the next one."""
        self._lane_rows = lane_rows

    def resize_suns(self) -> None:
        """Publish the suns a local midnight has resized since the last snapshot or delta; a day that changes no share
        publishes nothing."""
        with self._lock:
            before = self._sized[1]
            if self._suns() != before:
                self._publish("suns", {"suns": self._sized[1]})

    def keep_suns(self, stop: threading.Event, interval: float = SUN_INTERVAL) -> None:
        """Resize the suns every `interval` seconds until `stop` is set, so a page open across midnight is told."""
        while not stop.wait(interval):
            self.resize_suns()

    def _suns(self) -> dict[str, float]:
        """The shares the last local midnight set (empty until `size_suns`); the caller holds the lock."""
        if self._lane_rows is None:
            return {}
        today = datetime.fromtimestamp(self._clock()).replace(hour=0, minute=0, second=0, microsecond=0)
        if self._sized[0] != today:
            week = move_shares(
                self._drawn["board"],
                self._lane_rows(),
                start=(today - timedelta(days=SUN_DAYS)).timestamp(),
                end=today.timestamp(),
            )
            self._sized = (today, week)
        return self._sized[1]

    def put(self, task: BoardTask) -> None:
        """Place a task the board contract describes; one outside the adapter's key scheme is dropped."""
        if self._keys is not None and not self._keys.matches(task.id):
            return
        entered = self._place(task)
        if entered is not None and self._lanes is not None:
            try:
                self._lanes.record_lane(f"{task.id}@{task.lane}@{entered}", task.id, task.lane, entered)
            except Exception as exc:  # the history is down; the task is placed and the next change is recorded
                logger.warning("StarPulse: cannot record the lane change of %s: %s", task.id, exc)

    def _place(self, task: BoardTask) -> float | None:
        """Place `task`; when it entered its lane if that is a change of lane, else None."""
        with self._lock:
            self._assignees[task.id] = task.assignee
            agent, settled = (None, settled_entry(task)) if task.settled else (task_agent(task), None)
            before = self._open.get(task.id)
            if agent and before:
                # the lane the task left on its last move, kept while the hourly reconcile republishes it in place
                previous = before["state"] if before["state"] != agent["state"] else before.get("previous")
                if previous:
                    agent["previous"] = previous
            if agent:
                agent["entered"] = self._entered(task, before)
                agent["workable"], agent["workable_since"] = self._workable(agent)
            self._gated.discard(task.id)
            if agent and task.lane == WAITING and criteria.authored(task.description):
                self._gated.add(task.id)
            if before == agent and self._settled.get(task.id) == settled:
                return None  # an hourly reconcile republishes every task; only a change reaches the page
            if agent is None:
                self._open.pop(task.id, None)
                if settled:
                    self._settled[task.id] = settled
            else:
                self._open[task.id] = agent
                self._settled.pop(task.id, None)
            self._link(task.id, before["dependencies"] if before else (), agent["dependencies"] if agent else ())
            self._publish("task", {"id": task.id, "agent": agent, "settled": settled})
            self._reassess(self._dependents.get(task.id, ()))
            return agent["entered"] if agent and (before is None or before["state"] != agent["state"]) else None

    def retract(self, task_id: str) -> None:
        """Remove a task the adapter's source no longer holds, open or settled; a task not placed is a no-op."""
        with self._lock:
            self._assignees.pop(task_id, None)
            gone = self._open.pop(task_id, None)
            if gone is None and self._settled.pop(task_id, None) is None:
                return
            self._gated.discard(task_id)
            self._link(task_id, gone["dependencies"] if gone else (), ())
            self._publish("task", {"id": task_id, "agent": None, "settled": None})
            self._reassess(self._dependents.get(task_id, ()))

    def _entered(self, task: BoardTask, before: dict | None) -> float:
        """When `task` entered its lane: kept while it stays there, now for a move read live, else the history's date."""
        if before and before["state"] == task.lane and "entered" in before:
            return before["entered"]
        if not self.ready.is_set():
            try:
                path = self._lane_path(task.id)
            except Exception as exc:  # the history is down; the task is still placed, dated now
                logger.warning("StarPulse: cannot read the lane history of %s: %s", task.id, exc)
                path = []
            dated = [c["at"] for c in path if lane_id(c["to"]) == task.lane]
            if dated:
                return dated[-1]
        return self._clock()

    def _link(self, task_id: str, before: Collection[str], after: Collection[str]) -> None:
        """Keep each dependency's dependents current when `task_id` moves from depending on `before` to `after`."""
        for dependency in set(before) - set(after):
            self._dependents[dependency].discard(task_id)
        for dependency in set(after) - set(before):
            self._dependents.setdefault(dependency, set()).add(task_id)

    def _done_at(self, task_id: str) -> float | None:
        """When the task was done, or None when it is not: completed (0 when the board does not say when) or in the done lane."""
        if (settled := self._settled.get(task_id)) is not None:
            return (settled["at"] or 0.0) if settled["state"] == "completed" else None
        agent = self._open.get(task_id)
        return agent["entered"] if agent and agent["state"] == DONE else None

    def _unblocked(self, agent: dict) -> bool:
        return all(self._done_at(dependency) is not None for dependency in agent["dependencies"])

    def _workable(self, agent: dict) -> tuple[bool, float | None]:
        """Whether the task can be worked, and since when; the caller holds the lock."""
        if not self._unblocked(agent) or (agent["id"] in self._gated and agent["id"] not in self._met):
            return False, None
        since = max(
            [agent["entered"], self._met.get(agent["id"], 0.0)]
            + [self._done_at(d) or 0.0 for d in agent["dependencies"]]
        )
        return True, since

    def _reassess(self, task_ids: Collection[str]) -> None:
        """Work out again whether each open task of `task_ids` is workable and publish those that changed."""
        for task_id in sorted(task_ids):
            if (agent := self._open.get(task_id)) is None:
                continue
            workable, since = self._workable(agent)
            if (agent["workable"], agent["workable_since"]) != (workable, since):
                agent = {**agent, "workable": workable, "workable_since": since}
                self._open[task_id] = agent
                self._publish("task", {"id": task_id, "agent": agent, "settled": None})

    def track_criteria(self, evaluate: Callable[[str, str], list[dict]] | None, store: CriteriaStore | None) -> None:
        """Evaluate Waiting tasks' Start Criteria with `evaluate` (None: each is `not evaluated`, so none is met).

        `store` keeps when each task's criteria were first seen met, so a restart keeps how long a task has been
        workable; None keeps it in memory only.
        """
        with self._lock:
            self._evaluate = evaluate or criteria.unevaluated
            self._criteria_store = store
            if store is not None:
                try:
                    self._met = dict(store.criteria_met())
                except Exception as exc:  # the store is down; the next pass dates each task afresh
                    logger.warning("StarPulse: cannot read when Start Criteria were met: %s", exc)
            self._reassess(list(self._open))

    def evaluate_criteria(self) -> None:
        """Evaluate the Start Criteria of every Waiting task whose dependencies are done, and publish each task whose
        workability changed. A task whose criteria are all met keeps the moment it was first seen so; a task whose
        criteria are not met, or that is no longer evaluated, is forgotten, so its next met moment is a new one."""
        with self._lock:
            due = [(t, self._open[t]["description"]) for t in sorted(self._gated) if self._unblocked(self._open[t])]
            evaluate, now = self._evaluate, self._clock()
        met = []
        for task, description in due:
            try:
                results = evaluate(task, description)
            except Exception as exc:  # an evaluator is meant to return errors as results; this one raised
                logger.warning("StarPulse: cannot evaluate the Start Criteria of %s: %s", task, exc)
                continue
            if results and all(result["status"] == "met" for result in results):
                met.append(task)
        with self._lock:
            kept = {task: self._met.get(task, now) for task in met}
            if kept == self._met:
                return
            previous, self._met, store = self._met, kept, self._criteria_store
            self._reassess(previous.keys() | kept.keys())
        if store is not None:
            try:
                store.save_criteria_met(kept)
            except Exception as exc:  # the store is down; the pass stands and the next change saves it
                logger.warning("StarPulse: cannot save when Start Criteria were met: %s", exc)

    def keep_criteria(self, stop: threading.Event, interval: float = CRITERIA_INTERVAL) -> None:
        """Evaluate now and then every `interval` seconds until `stop` is set."""
        while True:
            self.evaluate_criteria()
            if stop.wait(interval):
                return

    def pull_requests(self) -> dict[str, list[str]]:
        """Each open task's pull request links, for the tasks that cite any."""
        with self._lock:
            return {task: list(agent["prs"]) for task, agent in self._open.items() if agent["prs"]}

    def put_insight(self, finding: dict) -> None:
        """Draw a finding an engine posted, replacing the one of its id, and send it as an `insight` event.

        A finding already past its `expires_at` is not drawn: it retracts the one it replaces, if any.
        """
        with self._lock:
            expires = finding.get("expires_at")
            if expires is not None and expires <= self._clock():
                self.retract_insight(finding["id"])
                return
            self._insights[finding["id"]] = finding
            self._publish("insight", {"id": finding["id"], "finding": finding})

    def retract_insight(self, finding_id: str) -> None:
        """Stop drawing a finding and send its retraction, an `insight` event whose `finding` is null; a finding that
        is not drawn sends nothing."""
        with self._lock:
            if self._insights.pop(finding_id, None) is not None:
                self._publish("insight", {"id": finding_id, "finding": None})

    def set_pulls(self, pulls: dict[str, list[dict]], answers: dict | None = None) -> None:
        """Take each task's pull request state and publish it when it differs from before; `answers` is what the
        reader learned from GitHub, kept with the saved Board so a restart need not ask again."""
        with self._lock:
            if answers is not None and answers != self._pull_answers:
                self._pull_answers, self._pulls_unsaved = answers, True
            if pulls == self._pulls:
                return
            self._pulls_unsaved = True
            self._pulls = pulls
            self._publish("pulls", {"pulls": pulls})
            self._refresh_ledgers()

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

    def wait_replayed(self) -> None:
        """Block until the stream has been read up to where it stood at the start; at once for a feed that reads none."""
        if self._awaiting:
            self.ready.wait()

    def runs(self, instance: str) -> InstanceRuns:
        """Where the runs adapter instance `instance` publishes its workflows."""
        return InstanceRuns(self, instance)

    def set_dags(
        self,
        instance: str,
        dags: list | None,
        error: str | None,
        pools: list | None = None,
        startable: list[str] | None = None,
    ) -> None:
        """Take the latest workflows and concurrency pools of `instance` (None keeps the last of each) and publish
        them when they differ from before; an empty `pools` says the instance now reports none.

        `startable` names the workflows of `instance` its adapter can start now (None keeps the last report; an
        instance that never reports one can start every workflow it has a start for). Run now is declared only on a
        `run_safe` workflow in it, and a change hands every page a snapshot, which is what carries the declaration.
        """
        with self._lock:
            dags = self._dags.get(instance, []) if dags is None else dags
            pools = self._pools.get(instance, []) if pools is None else pools
            reported = self._startable.get(instance) if startable is None else frozenset(startable)
            moved = (dags, error, pools) != (
                self._dags.get(instance),
                self._runs_errors.get(instance),
                self._pools.get(instance, []),
            )
            changed = reported != self._startable.get(instance)
            if not (moved or changed):
                return
            self._dags[instance] = dags
            self._pools[instance] = pools
            if reported is not None:
                self._startable[instance] = reported
            if error is None:
                self._runs_errors.pop(instance, None)
            else:
                self._runs_errors[instance] = error
            if moved:
                self._publish("dags", {"dags": self._workflows(), "pools": self._drawn_pools(), "error": self._error()})
                self._refresh_ledgers()
            if changed:
                self._publish("snapshot", self.snapshot())

    def _runnable(self) -> list[str]:
        """The `run_safe` workflows Run now is declared on: those their instance's adapter can start."""
        out = []
        for name in self._run_safe:
            instance, _, workflow = name.partition("/")
            startable = self._startable.get(instance)
            if startable is None or workflow in startable:
                out.append(name)
        return out

    def _workflows(self) -> list[dict]:
        """Every instance's workflows, each named `<instance>/<workflow>`; a pushed one an adapter lists is drawn by that adapter."""
        listed = {dag["name"] for instance, dags in self._dags.items() if instance != PUSHED_INSTANCE for dag in dags}
        return [
            {**{key: value for key, value in dag.items() if key != "recent"}, "name": f"{instance}/{dag['name']}"}
            | ({"pool": f"{instance}/{dag['pool']}"} if dag.get("pool") else {})
            for instance, dags in self._dags.items()
            for dag in dags
            if instance != PUSHED_INSTANCE or dag["name"] not in listed
        ]

    def _ledger(self) -> dict[str, list[dict]]:
        """Every tied Board event's occurrences of the last `LEDGER_WINDOW`, newest first, with the run of every
        workflow tied to it (`starpulse.ledger`).

        The merge event's occurrences are the merged pull requests; any other event's are the tasks that entered the
        lane it reaches, read from the lane history `size_suns` was given. Only the window's changes are read: this runs
        under the lock on every run and pull update, and the whole history is far larger than a day.
        """
        events: dict[str, list[Occurrence]] = {}
        since = self._clock() - LEDGER_WINDOW
        if MERGE_EVENT in self._ties:
            events[MERGE_EVENT] = [o for o in pull_occurrences(self._pulls) if o.at >= since]
        reached = {
            event: {t["target"] for t in self._drawn["board"].get("transitions", []) if t["event"] == event}
            for event in self._ties.keys() - {MERGE_EVENT}
        }
        if reached and self._lane_rows is not None:
            for task, at, _from, to in self._lane_rows(since):
                for event, lanes in reached.items():
                    if lane_id(to) in lanes:
                        events.setdefault(event, []).append(Occurrence(f"{task}@{at}", at, (task,)))
        return build(
            events,
            self._ties,
            self._recent_runs(),
            lambda dag: self._commit.get(dag.partition("/")[0]),
            lambda event, dag: self._resolves.get((event, dag), NEXT),
        )

    def _recent_runs(self) -> dict[str, list]:
        return {
            f"{instance}/{dag['name']}": dag.get("recent", [])
            for instance, dags in self._dags.items()
            for dag in dags
        }

    def commit_keys(self, instance: str) -> CommitKeys | None:
        """The `[runs.commit]` of runs instance `instance`, or None when it declares none."""
        return self._commit.get(instance)

    def open_failure(self, dag: str) -> dict | None:
        """The newest unresolved failure of workflow `dag` (`<instance>/<workflow>`) as `{runId, params}`, the parameters
        that run started with, or None when it has none or the runs adapter no longer lists the run."""
        with self._lock:
            open_ = [
                fail
                for rows in self._ledger().values()
                for row in rows
                if (fail := row["fails"].get(dag)) and fail["resolved"] is None
            ]
            instance, _, workflow = dag.partition("/")
            recent = next((d.get("recent", []) for d in self._dags.get(instance, []) if d["name"] == workflow), [])
        newest = max(open_, key=lambda fail: fail["startedAt"], default=None)
        run = next((r for r in recent if newest and r["runId"] == newest["runId"]), None)
        return None if run is None else {"runId": run["runId"], "params": dict(run.get("params", {}))}

    def _head(self, ledgers: dict[str, list[dict]]) -> dict[str, list[dict]]:
        """`ledgers` with the merge event's rows cut to the newest page; older ones come from `merges`."""
        if MERGE_EVENT not in ledgers:
            return ledgers
        found, _ = page(ledgers[MERGE_EVENT], before=None, limit=PAGE, since=self._clock() - LEDGER_WINDOW)
        return {**ledgers, MERGE_EVENT: found}

    def _merge_strip(self, ledgers: dict[str, list[dict]]) -> dict | None:
        """The 24-hour strip of the merge ledger (`ledger.strip`), counted over every row rather than the page sent;
        None when no workflow is tied to the merge event."""
        if MERGE_EVENT not in ledgers:
            return None
        recent = self._recent_runs()
        forced = [
            at
            for dag in self._ties[MERGE_EVENT]
            for at in reruns(recent.get(dag, ()), self._commit.get(dag.partition("/")[0]))
        ]
        return strip(ledgers[MERGE_EVENT], forced, now=self._clock(), span=LEDGER_WINDOW, bucket=STRIP_BUCKET)

    def _merge_pins(self, ledgers: dict[str, list[dict]], head: dict[str, list[dict]]) -> list[dict]:
        """The pinned merge rows of the last day that the newest page leaves out, so a failure waiting on its cue is
        never paged out of sight."""
        shown = {row["key"] for row in head.get(MERGE_EVENT, ())}
        return [row for row in ledgers.get(MERGE_EVENT, ()) if row["pinned"] and row["key"] not in shown]

    def _ledger_view(self, full: dict[str, list[dict]]) -> dict:
        head = self._head(full)
        return {"ledgers": head, "mergeStrip": self._merge_strip(full), "mergePins": self._merge_pins(full, head)}

    def _ledger_fields(self) -> dict:
        return self._ledger_view(self._ledger())

    def merges(self, before: float | None, limit: int) -> dict:
        """`GET /api/merges`: the next `limit` merges older than `before` (None: the newest), `{merges, more}`, none
        from beyond `LEDGER_WINDOW`."""
        with self._lock:
            found, more = page(
                self._ledger().get(MERGE_EVENT, ()), before=before, limit=limit, since=self._clock() - LEDGER_WINDOW
            )
            return {"merges": found, "more": more}

    def _flows(self, now: float) -> tuple[list[dict], dict[str, dict]]:
        """Every flow with its tasks as the page draws them, and each machine's derivation (`machine_ties.derive`)."""
        since = now - self._window_s if self._window_s is not None else None
        flows = [
            {"name": "board", "machine": self._drawn["board"], "agents": list(self._open.values())},
            *(
                {
                    "name": name,
                    "machine": self._drawn[name],
                    "agents": [self._modelled(a) for a in agents.values() if since is None or a["active"] >= since],
                }
                for name, agents in self._machines.items()
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
        """Send the Ledger when it or its strip differs from the one last sent; the caller holds the lock."""
        view = self._ledger_view(self._ledger())
        strip_ = view["mergeStrip"]
        seen = (view["ledgers"], strip_ and strip_["buckets"], view["mergePins"])
        if seen != (self._ledgers, self._strip and self._strip["buckets"], self._pins):
            self._ledgers, self._strip, self._pins = view["ledgers"], strip_, view["mergePins"]
            self._publish("ledgers", view)

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
            now = time.time()
            flows, derived = self._flows(now)
            return {
                "graphs": [*self._drawn, "runs"],
                "flows": [{**f, **derived.get(f["name"], {})} for f in flows],
                **self._machine_fields(flows, derived, now),
                "dags": self._workflows(),
                "pools": self._drawn_pools(),
                "pulls": self._pulls,
                **self._ledger_fields(),
                "claims": dict(self._claims),
                "insights": [
                    finding
                    for finding in self._insights.values()
                    if finding.get("expires_at") is None or finding["expires_at"] > self._clock()
                ],
                "capabilities": dict(self._capabilities),
                "settled": dict(self._settled),
                "error": self._error(),
                "reading": self._replaying(),
                **declared(self._domains, self._runnable(), self._cues),
                "boardUrl": self._board_url,
                "hint": self._hint,
                "suns": self._suns(),
                "now": now,
            }


class InstanceRuns:
    """The feed as one runs adapter instance sees it: it publishes its workflows and errors under its own name."""

    def __init__(self, feed: BoardFeed, instance: str) -> None:
        self._feed = feed
        self._instance = instance

    @property
    def tied(self) -> frozenset[str]:
        """The workflows of this instance a Board event cues or that write one, whose recent runs the adapter reports."""
        return self._feed.tied(self._instance)

    def set_dags(
        self, dags: list | None, error: str | None, pools: list | None = None, startable: list[str] | None = None
    ) -> None:
        self._feed.set_dags(self._instance, dags, error, pools, startable)


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
