"""The task actor: a task advances itself on the facts its lane waits on.

A machine state's `waits` name a fact kind and the event that leaves the state when the fact holds
(`machine_definition.WAIT_FACTS`). The actor keeps a `PR -> tasks` and a `task -> dependents` index, so one change
touches only the tasks naming it, and when a task's pull request state, its own lane or a dependency's changes it
re-derives that task's waits and writes the first that holds through the board's task editor as `starpulse/task-actor`.
The board's rules and the machine's guards judge the write like any other. A write the board refuses is logged and
counted, and not tried again until the task's facts change. A move to Done the board refuses (a Definition of Done item
left open) is commented on the task as `Held from Done: <reason>` and handed to the `delivered` hook, so the holder
wakes on the refusal; the last item checked tries the move again. A release to Ready that the board's lint refuses (a
declared guard or the validate hook) leaves the task in its lane with the lint's reason as a comment and no operator
question, and the release is tried again when the task's description, profile, labels or dependencies change; any
other refused release parks the task in Needs attention with the refusal as its reason, once per refusal. A start
re-derives every open task once, which is the recovery for a change that happened while the server was down.

A lifecycle machine whose phase state links a skill machine with `exits` (`submachines[].exits`) advances that phase
too: when the skill machine reaches an exit state the actor calls `advance(machine, task, event)` with the exit's event,
once per visit to the phase, and only for the skill machine the task's current phase links. A link that lists `routes`
(phase state to event) sends instead the event for the phase that follows it in the `sequences` entry of the task's
type (`default` for a type it does not name), when one is listed; the exit's own event serves every other sequence.
The Board's phase is a task's lane, and its links count only when the actor writes every event they exit on (the Verify
machine's `passed` and `missed` close and send back a Verifying task); a skill placement from before the task entered
the lane is the last visit's and advances nothing.

A task whose lane waits on its Start Criteria is evaluated on a thread of its own when it has no result, when
`criteria_changed` says an event its criteria await has happened, or at the deadline its own result names (the shortest
`refresh.interval` it prints, scheduled once per result), and re-derived when the result changes; a criterion that
cannot be evaluated is exported, not retried before then. The board adapter may hold a task's `deps_done` with reasons, written once as a comment; a task
created re-derives every held task.

Nothing derives a lane on a period. A task moves when a fact its lane watches changes: its own record, a dependency's
lane or checked criteria, a pull request, a criteria event, or its deadline. Each derivation of a task in a lane that
waits on `deps_done` comments once, as `Flagged in Waiting: <reason>`, when a dependency nothing will finish (the board
holds no such task, or it is Proposed). A dependency Done or Archived is met. The start derivation reads every open
task not unchanged since the actor's checkpoint once as recovery and logs each move it makes as a defect: a move the
events should have made before it. The checkpoint (`CHECKPOINT` worker state) keeps the digest of the facts each task was
last derived on, saved while the actor runs and again on a clean stop; a start derives only the tasks whose digest
differs, and every open task when no checkpoint is readable or the lanes' waits and moves changed since it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import queue
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from starpulse.board import criteria
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.markdown import section_set
from starpulse.board.model.rollup import checks_verdict
from starpulse.board.model.seam import (
    COMMENT_CAP,
    FLAGGED,
    HELD,
    MERGE_EVIDENCE,
    TaskCreator,
    TaskEditor,
    TaskReader,
    TaskReleaser,
    Written,
)
from starpulse.event_log.deadlines import Deadlines
from starpulse.event_log.wake import StopEvent
from starpulse.machine_engine.model.state_roles import StateRoles
from starpulse.pulls.adapters.inbound.unblock import PinGate
from starpulse.pulls.adapters.outbound.pull_requests import landed, own_prs, pull_record
from starpulse.pulls.model.pins import LiveBuild, Pins, Repo

if TYPE_CHECKING:  # annotation only: the pull store and the event log open the database stack
    from starpulse.event_log.event_log import EventLog
    from starpulse.pulls.adapters.outbound.pulls import PullStore

logger = logging.getLogger(__name__)

__all__ = ["ACTOR", "ATTENTION_QUESTION", "LINT_REFUSED", "TaskActor", "moves_of"]

#: The actor every write of the task actor names.
ACTOR = "starpulse/task-actor"
#: The machine whose phase is a task's lane.
BOARD = "board"
#: What the task actor comments when the board's lint refuses a task's release to Ready, before the refusal.
LINT_REFUSED = "Release to Ready refused by the task lint, repair the record to release it:"
#: What the task actor comments on a task whose Start Criteria stayed in error for two passes, before the errors.
REGATE = "Start Criteria could not be evaluated for two passes, an agent re-gates the task:"
#: The machine event a delivery run publishes when it ends, its verdict in the event's data.
DELIVER_FINISHED = "DELIVER_FINISHED"
#: The question that ends the `## Needs attention` reason of a task the actor moves there on a pull request fact.
ATTENTION_QUESTION = "Fix it on the task branch and redeliver, or rescope?"
#: The pull request states that end a pull request.
_TERMINAL = ("MERGED", "CLOSED")
REFUSALS_METRIC = "starpulse_task_actor_refusals_total"
CRITERIA_ERRORS_METRIC = "starpulse_task_actor_criteria_errors"
PIN_HELD_METRIC = "starpulse_task_actor_pin_held"
HEARTBEAT_METRIC = "starpulse_task_actor_heartbeat_timestamp_seconds"
RECOVERY_FINISHED_METRIC = "starpulse_task_actor_recovery_finished"
MERGED_WAITING_METRIC = "starpulse_task_actor_merged_review_waiting"
DERIVE_METRIC = "starpulse_task_actor_derive_seconds"
DONE_HELD = "Held from Done:"
#: Seconds between two progress lines of the start recovery.
_PROGRESS_S = 30.0
#: Seconds the idle actor loop waits for a change before it beats again.
_HEARTBEAT_S = 30.0
#: Seconds the exposition waits for the actor lock before it leaves out the series that need it.
_LOCK_WAIT_S = 2.0
#: The shortest wait a `refresh.interval` hint can ask for, in seconds.
MIN_REFRESH_S = 1.0
#: Seconds the merged Review tasks count is kept, so a scrape loop never makes the scan over the open tasks a load.
_WAITING_TTL_S = 5.0
#: The facts read from a task's evaluated Start Criteria.
_CRITERIA_FACTS = ("criteria_met", "criteria_unmet")
LATENCY_METRIC = "starpulse_task_actor_latency_seconds"
#: The upper bounds of the latency histogram's buckets, in seconds; the count past the last is the `+Inf` bucket's.
BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
PROJECTION_METRIC = "starpulse_task_actor_projection_seconds"
HANDOFF_METRIC = "starpulse_task_actor_handoff_seconds"
MERGE_MOVE_METRIC = "starpulse_task_merge_move_seconds"
#: The facts whose write moves a task because its pull requests ended; the merge-to-move histogram observes them.
_MERGE_FACTS = frozenset({"pr_terminal", "pr_merged", "pr_merged_planned", "pr_merged_unfinished"})
#: Most seconds start recovery waits for the saves and changes pending before it takes its next task, so steady traffic
#: slows recovery down but never stops it.
_YIELD_S = 2.0
#: The worker state holding each sent-back task's hold (task name to the head of each pull request it held on), so a
#: restart of the actor reads the hold back.
SENT_BACK = "pulls.sent_back"
#: The worker state holding the digest of the facts each task was last derived on, and of the waits and moves it was
#: derived under, so a start derives only the tasks that changed since.
CHECKPOINT = "pulls.task_actor_checkpoint"
#: Bumped when a fact function reads something new or reads it differently: a checkpoint of another revision is unread.
_FACTS_REVISION = 1
#: Seconds between two saves of the checkpoint while the actor runs.
_CHECKPOINT_S = 30.0
_NOTICE_JOIN_S = 10.0
#: The bounds of the projection and handoff histograms: a pin walk takes seconds, and the 10 s bound is the measure.
SLOW_BUCKETS_S = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
#: Seconds between two wakes of a task that rests in Verifying: a holder that was reaped or stalled runs its QA again.
REWAKE_S = 3600.0
#: Seconds a holder may stay busy after it settled idle (it runs a command or its `deliver` run is live) before the
#: `delivered` hook wakes it with the fact that its deliver run has not come back.
DELIVER_RETURN_S = 3600.0
#: A Waiting task's service level expectation: seconds from entering Waiting, or past its latest `expect_by`.
_DAY_S = 86_400.0
#: Seconds to wait before each retry of a write that found the board database locked.
LOCK_BACKOFF_S = (0.1, 0.4, 1.6)

#: The facts whose event parks a task in Needs attention: the comment is also its `## Needs attention` reason, a question.
_ASKS = ("overdue", "pr_closed_unmerged", "pr_failing", "holder_idle")

#: How many times a task's idle holder is released and its session started again before the idle is asked about.
IDLE_RESTARTS = 3
IDLE_RELEASE = "Released: holder idle after a checkpoint request"
_SLE_DAYS, _GRACE_DAYS = 7, 2
#: A comment recording the operator's answer: `backlog-task answer`'s line, or the audit comment of a relayed answer.
_ANSWER_COMMENT = re.compile(r"\W*Operator answer\b")
#: Start Criteria evaluated at once: each is a subprocess, so the pass is bounded rather than one thread per gated task.
_EVALUATIONS = 8


def _exit_links(machines: Mapping[str, Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Each lifecycle machine's links that exit on a skill machine's state: `{machine: [link]}`.

    The Board's links count only when the actor writes every event they exit on: another writer's exit (an agent's
    `review`, `park`) is that writer's to send, and sending it here would move the lane twice.
    """
    found = {
        name: [link for link in drawn.get("submachines", ()) if link.get("exits") and _written_here(name, drawn, link)]
        for name, drawn in machines.items()
    }
    return {name: links for name, links in found.items() if links}


def _written_here(name: str, drawn: Mapping[str, Any], link: Mapping[str, Any]) -> bool:
    """Whether the link may be sent by the actor: any link of a phase machine, a Board link whose exits it writes."""
    if name != BOARD:
        return True
    writers = drawn.get("writers", {})
    return all(ACTOR in (writer["actor"] for writer in writers.get(event, ())) for event in link["exits"].values())


def _lint_record(agent: Mapping[str, Any]) -> tuple[Any, ...]:
    """The parts of a task's record the board's lint reads, which a repair changes and a comment does not."""
    return agent["description"], agent["profile"], tuple(agent["labels"]), tuple(agent["dependencies"])


def _view(agent: Mapping[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[bool, ...]]:
    """The parts of a task's record the actor re-derives on: its lane, dependencies, pull requests and checked criteria."""
    ticks = tuple(criterion["checked"] for criterion in agent.get("criteria", ()))
    return agent["state"], tuple(agent["dependencies"]), tuple(agent["prs"]), ticks


def _rules_digest(
    waits: Mapping[str, Mapping[str, str]], moves: Mapping[tuple[str, str], str], sequences: Mapping[str, Sequence[str]]
) -> str:
    """A digest of the lanes' waits, the moves and the phase sequences, which a checkpoint is valid under."""
    drawn = [_FACTS_REVISION, waits, {f"{lane}|{event}": target for (lane, event), target in moves.items()}, sequences]
    return hashlib.sha1(json.dumps(drawn, sort_keys=True, default=dict).encode(), usedforsecurity=False).hexdigest()[
        :16
    ]


def _epoch(text: str) -> float | None:
    """Epoch seconds of an ISO date or timestamp (UTC when it names no zone); None when it is neither."""
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).timestamp()


def _stamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d")


def _need_of(need: str) -> tuple[str, int]:
    """`(task, criterion number)` of a dependency need `TASK-N#K`; a need that names no number is number 0, which
    no task has."""
    task, _, number = need.partition("#")
    return task, int(number) if number.isdigit() else 0


def moves_of(machine: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """`{(lane, event): target lane}` for the transitions of a drawn machine (`snapshot.describe`)."""
    return {(move["source"], move["event"]): move["target"] for move in machine["transitions"]}


#: How many of a hold's reasons its comment lists; the rest are counted.
HOLD_REASONS_LISTED = 3


def _hold_comment(prefix: str, reasons: Sequence[str]) -> str:
    """The comment for a hold: the first few `reasons` and a count of the rest, clipped to the comment cap."""
    text = f"{prefix} {'; '.join(reasons[:HOLD_REASONS_LISTED])}"
    if len(reasons) > HOLD_REASONS_LISTED:
        text += f" (and {len(reasons) - HOLD_REASONS_LISTED} more)"
    return f"{text}."[:COMMENT_CAP]


class _Histogram:
    """Seconds observed from any thread, as the cumulative buckets of a Prometheus histogram."""

    def __init__(self, bounds: Sequence[float]) -> None:
        self._bounds = bounds
        self._lock = threading.Lock()
        self._counts = [0] * (len(bounds) + 1)
        self._sum = 0.0

    def observe(self, seconds: float) -> None:
        at = next((i for i, bound in enumerate(self._bounds) if seconds <= bound), len(self._bounds))
        with self._lock:
            for i in range(at, len(self._counts)):
                self._counts[i] += 1
            self._sum += seconds

    def lines(self, name: str, help_text: str) -> list[str]:
        return [f"# HELP {name} {help_text}", f"# TYPE {name} histogram", *self.samples(name)]

    def samples(self, name: str, labels: str = "") -> list[str]:
        """The histogram's sample lines, each carrying `labels` (`lane="ready",hook="false"`) when given."""
        with self._lock:
            counts, total = list(self._counts), self._sum
        head, tail = (f"{labels},", f"{{{labels}}}") if labels else ("", "")
        buckets = [
            f'{name}_bucket{{{head}le="{bound:g}"}} {count}' for bound, count in zip(self._bounds, counts, strict=False)
        ]
        return [
            *buckets,
            f'{name}_bucket{{{head}le="+Inf"}} {counts[-1]}',
            f"{name}_sum{tail} {total:g}",
            f"{name}_count{tail} {counts[-1]}",
        ]


class TaskActor:
    """Moves each open task whose lane waits on a fact that holds, once per change of that fact.

    `waits` is `{lane: {fact kind: event}}` (`Compiled.waits`) and `moves` is `{(lane, event): target lane}`, from the
    Board machine's transitions. `edit` is the board's task editor. `repos`, `pin_rule` and `pins` are the `[release]`
    pin-bump rule (`unblock.PinGate`): a dependency in a pinned repository is merged on the parent's pin bump.
    `evaluate` is the board's Start Criteria evaluator (`Board.evaluate`; None: no criteria fact ever holds) and `holds`
    the reasons the board adapter withholds a task's `deps_done` (`Board.holds`; None: it holds none). `read` is the
    board's task reader (`Board.read`), which tells `pr_merged` and `pr_merged_planned` apart by the task's Verify plan
    (None: no task has one). `unfinished` is the work a task whose pull requests merged still has (`Board.unfinished`;
    None: it has none).
    """

    def __init__(
        self,
        feed: BoardFeed,
        store: PullStore,
        edit: TaskEditor,
        waits: Mapping[str, Mapping[str, str]],
        moves: Mapping[tuple[str, str], str],
        repos: Sequence[Repo] = (),
        pin_rule: str | None = None,
        pins: Pins | None = None,
        board_repo: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        evaluate: Callable[[str, str], list[dict[str, Any]]] | None = None,
        holds: Callable[[str], Sequence[str]] | None = None,
        parked: Callable[[str], None] | None = None,
        released: Callable[[str], None] | None = None,
        delivered: Callable[[str, str], None] | None = None,
        closed: Callable[[str], None] | None = None,
        returned: Callable[[str], None] | None = None,
        alive: Callable[[str], bool] | None = None,
        enqueued: Callable[[str], None] | None = None,
        verifying: Callable[[str], None] | None = None,
        live: LiveBuild | None = None,
        advance: Callable[[str, str, str], None] | None = None,
        read: TaskReader | None = None,
        idle: Callable[[str, str], None] | None = None,
        release: TaskReleaser | None = None,
        sequences: Mapping[str, Sequence[str]] = MappingProxyType({}),
        unfinished: Callable[[str], Sequence[str]] | None = None,
        create: TaskCreator | None = None,
        rewake_s: float = REWAKE_S,
        deliver_return_s: float = DELIVER_RETURN_S,
        log: EventLog | None = None,
    ) -> None:
        self._read = read
        self._idle = idle
        self._release = release
        #: How many times each In Progress holder settled idle and was reached since its task last moved.
        self._idled: dict[str, int] = {}
        #: How many times each task's idle holder was released and its session started again since it last left the working lane.
        self._restarts: dict[str, int] = {}
        self._create = create
        self._advance = advance
        #: The phases a task of each type goes through, in order (`[sequences]`); `default` serves an unnamed type.
        self._sequences = sequences
        self._unfinished = unfinished
        #: Each non-Board machine's links that exit on a skill machine's state, when there is somewhere to send the exit.
        self._links = _exit_links(feed.machines) if advance else {}
        #: The exit last sent for each `(machine, task)`, with the phase's step count, so one exit is sent once.
        self._exited: dict[tuple[str, str], tuple[str, int, str]] = {}
        #: When each task entered the Board lane it holds, read at the move: the feed's `entered` is its newest event of
        #: any kind, which a comment after a verdict moves past the verdict's time.
        self._lane_entered: dict[str, tuple[str, float]] = {}
        self._feed = feed
        self._store = store
        self._edit = edit
        self._waits = waits
        #: The lane that waits on a pull request's end, whatever the board names it.
        self._review = StateRoles(dict.fromkeys(waits, "waiting_on_fact"), waits).review
        self._moves = moves
        self._clock = clock
        #: Epoch seconds, which a task's `entered` and `expect_by` are in; `clock` is monotonic and has no date.
        self._wall = wall
        #: The lanes that wait on the service level expectation.
        self._timed_lanes = {lane for lane, facts in waits.items() if "overdue" in facts}
        #: When each timed task's deadline falls, if still ahead; a fired one derives its task again.
        self._deadlines = Deadlines(self._derive_overdue, clock=wall)
        #: The Waiting tasks the last `reconcile_waiting` found releasable, so a second pass finding one counts a miss.
        self._releasable: set[str] = set()
        self._dates: dict[str, tuple[str, ...]] = {}
        self._evaluate = evaluate
        self._holds = holds
        self._tell = parked
        self._released = released
        self._delivered = delivered
        #: The step count of each task's last finished delivery handed to `delivered`, so one run's end is told once.
        self._told: dict[str, int] = {}
        self._closed = closed
        self._returned = returned
        self._alive = alive
        self._enqueued = enqueued
        self._verifying = verifying
        self._rewake_s = rewake_s
        self._deliver_return_s = deliver_return_s
        #: When each In Progress task's holder first settled idle while busy, until it settles idle and reachable.
        self._busy_since: dict[str, float] = {}
        #: When the `verifying` hook last told each Verifying task's holder to run its post-merge QA.
        self._woken: dict[str, float] = {}
        #: The lanes that wait on their tasks' dependencies, whose derivation flags a wait nothing ends.
        self._sweep_lanes = {lane for lane, facts in waits.items() if "deps_done" in facts}
        #: The lanes that wait on a task's Start Criteria.
        self._gated_lanes = {lane for lane, facts in waits.items() if facts.keys() & set(_CRITERIA_FACTS)}
        #: When each gated task's criteria were last evaluated, and each criterion's `(id, status)` then.
        self._results: dict[str, tuple[float, tuple[tuple[str, str], ...]]] = {}
        #: When each gated task's result is due again: the shortest `refresh.interval` the result printed after it was read.
        self._expires: dict[str, float] = {}
        self._criteria_generation = (
            0  # counts `criteria_changed` events, so a pass that began before one keeps its results due
        )
        #: Set when a gated task has no result or an event its criteria await happened; wakes the criteria thread.
        self._criteria_wake = threading.Event()
        #: Whether the start derivation is running, which only recovers moves the events missed.
        self._recovering = False
        #: The Start Criteria each gated task carried when its record last changed: a result is dropped when they change.
        self._gates: dict[str, list[dict[str, Any]] | None] = {}
        #: Tasks whose `deps_done` the board adapter holds; a task created re-derives them.
        self._held: set[str] = set()
        self._gate = PinGate(feed, store, repos, pin_rule, pins, live)
        self._board_repo = (
            board_repo  # the repository whose pull requests read as a bare `PR #N`; another repo links its URL
        )
        self._lock = threading.RLock()
        #: Each open task's lane, dependencies and pull requests as the actor last saw them.
        self._seen: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], tuple[bool, ...]]] = {}
        self._by_pr: dict[str, set[str]] = {}
        #: What each pull request last read as, so a refresh that changed nothing derives nothing.
        self._pull_states: dict[str, tuple[str, str | None, bool, str, str, str]] = {}
        #: Per task sent back from Review to the working lane, the head of each pull request it cites at that moment: a
        #: ready pull request still on that head is the reviewed work, which `pr_ready` does not send to Review again.
        #: Kept in the `SENT_BACK` worker state of `log`, so a restart of the actor reads it back.
        self._log = log
        self._sent_back: dict[str, dict[str, str]] = self._restored_holds()
        #: Digest of the waits, moves and sequences the checkpoint is valid under.
        self._rules = _rules_digest(waits, moves, sequences)
        #: The digest of the facts each task was last derived on, read back from the checkpoint; a task whose facts
        #: still digest to it needs no derivation at start.
        self._derived: dict[str, str] = self._restored_checkpoint()
        self._kept: dict[str, str] = dict(self._derived)
        #: Whether the derivation running now called a board hook, or could not settle (a transient write failure, a
        #: hold it could not read), which keeps its digest out of the checkpoint.
        self._hooked = False
        self._unsettled = False
        #: The board hooks of moves already written, run one at a time in the order written by their own thread: a
        #: hook runs a command for seconds, and run under `_lock` it held back the move of every task behind it.
        self._notices: queue.SimpleQueue[Callable[[], None] | None] = queue.SimpleQueue()
        self._noticing_ended = False
        self._noticing = threading.Lock()
        self._notifier: threading.Thread | None = None
        #: How long each derivation ran, by the lane the task was in and whether a board hook ran in it.
        self._derive_seconds: dict[tuple[str, bool], _Histogram] = {}
        #: Tasks whose dependencies are done but wait for a pin bump, and the store revision last read for them.
        self._pin_held: set[str] = set()
        self._store_rev = store.rev
        #: The move last tried for each task, until the task changes lane: the same facts are not tried twice.
        self._tried: dict[str, tuple] = {}
        #: The refusal each task was last parked in Needs attention for, so the same refusal parks it once.
        self._parked: dict[str, str] = {}
        #: The record each task's release was last refused on by the board's lint, so a repaired record is tried again.
        self._lint_held: dict[str, tuple[Any, ...]] = {}
        #: The passes in a row each gated task had a criterion in error, so the second re-gates it.
        self._error_passes: dict[str, int] = {}
        self._metrics = threading.Lock()
        self._refusals = 0
        #: How many writes landed within each bound of `BUCKETS_S`, then how many in all, and their seconds summed.
        self._buckets = [0] * (len(BUCKETS_S) + 1)
        self._sum = 0.0
        #: How long each projection of the pull request store ran, and how long a store save waited for the actor.
        self._projection = _Histogram(SLOW_BUCKETS_S)
        self._handoff = _Histogram(SLOW_BUCKETS_S)
        #: Seconds from a pull request's merge to the write that moved the task citing it.
        self._merge_move = _Histogram(SLOW_BUCKETS_S)
        #: How many store saves, task or move changes and projections wait for the lock or hold it; start recovery takes
        #: its next task only when none does. `_events` is notified each time one ends.
        self._pending = 0
        self._events = threading.Condition(threading.Lock())
        #: Set by a store save; `_saved_at` is the clock when the oldest unread save happened.
        self._saved = threading.Event()
        self._saved_at = 0.0
        #: The wall clock of the actor's last beat, None before the first: it moves only while the actor loop, or the
        #: start recovery, takes its turn, so a stuck actor with a live process stops moving it.
        self._heartbeat: float | None = None
        #: The merged Review tasks not tried, and the monotonic clock it was counted at.
        self._waiting: tuple[float, int] = (float("-inf"), 0)
        #: Set once the start's derivation of every open task is done. A task or move change, a store save and the
        #: Verifying rewake are handled from `indexed` on, while it runs.
        self.ready = threading.Event()
        #: Set once the start sweep has indexed the open tasks and read their pull requests, before it derives them.
        self.indexed = threading.Event()
        #: How many times each task's waits were derived, for the tests and a diagnosis.
        self.derivations: Counter[str] = Counter()

    def exposition(self) -> str:
        """Prometheus text of the writes the board refused, how long a fact took to become a landed write, and whether the
        actor is alive: its heartbeat, whether start recovery finished and the merged Review tasks it has not tried."""
        with self._metrics:
            counts, total, refusals = list(self._buckets), self._sum, self._refusals
            timed = sorted(self._derive_seconds.items())
        held = self._held_counts()
        derives = [
            line
            for (lane, hook), histogram in timed
            for line in histogram.samples(DERIVE_METRIC, f'lane="{lane}",hook="{str(hook).lower()}"')
        ]
        samples = [
            f'{LATENCY_METRIC}_bucket{{le="{bound:g}"}} {count}'
            for bound, count in zip(BUCKETS_S, counts, strict=False)
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
                *self._projection.lines(
                    PROJECTION_METRIC, "Seconds each projection of the pull request store ran, the pin walk included."
                ),
                *self._handoff.lines(
                    HANDOFF_METRIC, "Seconds from a pull request store save to the task actor reading it."
                ),
                *self._merge_move.lines(
                    MERGE_MOVE_METRIC, "Seconds from a pull request's merge to the write that moved its task."
                ),
                f"# HELP {DERIVE_METRIC} Seconds each derivation of a task's waits ran, by lane and whether a board hook ran.",
                f"# TYPE {DERIVE_METRIC} histogram",
                *derives,
                f"# HELP {RECOVERY_FINISHED_METRIC} 1 once the start recovery derived every open task, else 0.",
                f"# TYPE {RECOVERY_FINISHED_METRIC} gauge",
                f"{RECOVERY_FINISHED_METRIC} {int(self.ready.is_set())}",
                *self._heartbeat_lines(),
                *self._held_lines(held),
                "",
            ]
        )

    def _heartbeat_lines(self) -> list[str]:
        beat = self._heartbeat
        if beat is None:
            return []
        return [
            f"# HELP {HEARTBEAT_METRIC} Unix time of the task actor's last turn of its loop, start recovery included.",
            f"# TYPE {HEARTBEAT_METRIC} gauge",
            f"{HEARTBEAT_METRIC} {beat:.3f}",
        ]

    def _beat(self) -> None:
        self._heartbeat = self._wall()

    def _held_counts(self) -> tuple[dict[str, int], int, int] | None:
        """The series that read the actor's state under its lock: each gated task's criteria in error, the tasks held
        for a pin and the merged Review tasks not tried. None when another thread holds the lock past `_LOCK_WAIT_S`:
        a scrape must answer then, since a held lock is what the heartbeat and the recovery gauge report."""
        if not self._lock.acquire(timeout=_LOCK_WAIT_S):
            return None
        try:
            errors = {
                name: sum(status == "error" for _, status in statuses) for name, (_, statuses) in self._results.items()
            }
            return errors, len(self._pin_held), self._merged_waiting()
        finally:
            self._lock.release()

    def _merged_waiting(self) -> int:
        counted_at, waiting = self._waiting
        if time.monotonic() - counted_at >= _WAITING_TTL_S:
            waiting = sum(self._merged_untried(agent) for agent in self._feed.open_tasks())
            self._waiting = (time.monotonic(), waiting)
        return waiting

    def _merged_untried(self, agent: dict[str, Any]) -> bool:
        """Whether a Review task has a merged proof pull request and the actor has tried no move for it."""
        if agent["state"] != self._review or agent["id"] in self._tried:
            return False
        records = [self._record(url) for url in self._proof_prs(agent)]
        return any(record and record["state"] == "MERGED" for record in records)

    @staticmethod
    def _held_lines(held: tuple[dict[str, int], int, int] | None) -> list[str]:
        if held is None:
            return []
        errors, pin_held, waiting = held
        return [
            f"# HELP {PIN_HELD_METRIC} Waiting tasks whose dependencies are done but wait for a pin bump to merge.",
            f"# TYPE {PIN_HELD_METRIC} gauge",
            f"{PIN_HELD_METRIC} {pin_held}",
            f"# HELP {MERGED_WAITING_METRIC} Review tasks with a merged pull request whose move the actor has not tried.",
            f"# TYPE {MERGED_WAITING_METRIC} gauge",
            f"{MERGED_WAITING_METRIC} {waiting}",
            f"# HELP {CRITERIA_ERRORS_METRIC} Start Criteria the evaluator could not evaluate, per gated task; such a gate never passes.",
            f"# TYPE {CRITERIA_ERRORS_METRIC} gauge",
            *(f'{CRITERIA_ERRORS_METRIC}{{task="{name}"}} {count}' for name, count in sorted(errors.items()) if count),
        ]

    def start(self, stop: StopEvent) -> threading.Thread:
        """Follow the feed on a daemon thread until `stop` is set."""
        thread = threading.Thread(target=self._run, args=(stop,), name="task-actor", daemon=True)
        thread.start()
        if self._sweep_lanes:
            self._feed.reconcilers["waiting"] = self.reconcile_waiting
        if self._evaluate is not None and self._gated_lanes:
            if isinstance(self._evaluate, criteria.Evaluator):
                self._evaluate.listen(self.criteria_changed)  # a sweeper pass expires every result
            threading.Thread(target=self._keep_criteria, args=(stop,), name="task-actor-criteria", daemon=True).start()
        threading.Thread(target=self._follow_store, args=(stop,), name="task-actor-store", daemon=True).start()
        if self._log is not None:
            threading.Thread(
                target=self._keep_checkpoint, args=(stop,), name="task-actor-checkpoint", daemon=True
            ).start()
        if self._idle and self._delivered:
            threading.Thread(
                target=self._keep_awaiting_delivery, args=(stop,), name="task-actor-deliver", daemon=True
            ).start()
        if self._verifying and self._feed.roles.verifying:
            threading.Thread(target=self._keep_rewaking, args=(stop,), name="task-actor-rewake", daemon=True).start()
        if self._timed_lanes:
            self._deadlines.start(stop, thread_name="task-actor-deadlines")
        return thread

    def store_changed(self) -> None:
        """Tell the actor the pull request store saved. Only a flag is set, as the saving thread must not wait."""
        if not self._saved.is_set():
            self._saved_at = self._clock()
        self._saved.set()

    def timed_projection(self, project: Callable[[], None]) -> Callable[[], None]:
        """`project` that records how long each run took, however it ends."""

        def timed() -> None:
            started = self._clock()
            try:
                project()
            finally:
                self._projection.observe(self._clock() - started)

        return timed

    def _follow_store(self, stop: StopEvent) -> None:
        """Re-derive the tasks whose pull requests changed as soon as the store saves, ahead of the projection that
        saved it finishing its pin walk."""
        self.indexed.wait()
        stop.listen(self._saved.set)  # a stop wakes the wait below, which then sees it
        try:
            while not stop.is_set():
                self._saved.wait()
                if stop.is_set():
                    return
                try:
                    with self._pressing():
                        self._saved.clear()
                        self._store_saved(self._saved_at)
                except Exception:  # one pass must not end the thread
                    logger.exception("task actor: cannot read the pull request store")
        finally:
            stop.unlisten(self._saved.set)

    @contextmanager
    def _pressing(self) -> Iterator[None]:
        """Count the body as waiting for the lock or holding it, so start recovery yields to it."""
        with self._events:
            self._pending += 1
        try:
            yield
        finally:
            with self._events:
                self._pending -= 1
                self._events.notify_all()

    def _yield(self) -> None:
        """Wait, up to `_YIELD_S`, until no save, change or projection is pending."""
        with self._events:
            self._events.wait_for(lambda: not (self._pending or self._saved.is_set()), timeout=_YIELD_S)

    def _store_saved(self, saved: float) -> None:
        with self._lock:
            observed = self._clock()
            self._handoff.observe(observed - saved)
            self._derive_pulled(self._read_pulls(), observed)

    def criteria_changed(self) -> None:
        """Tell the actor an event its gated tasks' criteria await happened (a run ended, a pull request merged): every
        result is due now, and the evaluator answers the ones it still holds current from its own cache."""
        with self._lock:
            self._expires = dict.fromkeys(self._results, 0.0)
            self._criteria_generation += 1
        self._criteria_wake.set()

    def _keep_criteria(self, stop: StopEvent) -> None:
        """Evaluate each gated task whose result is missing or due, and re-derive it when the result changed. It sleeps
        until the nearest deadline a result named, or until an event or a task entering a gated lane wakes it."""
        self.ready.wait()
        stop.listen(self._criteria_wake.set)  # a stop wakes the wait below, which then sees it
        try:
            while not stop.is_set():
                self._criteria_wake.clear()
                try:
                    self._evaluate_due()
                except Exception:  # one pass must not end the thread
                    logger.exception("task actor: cannot evaluate Start Criteria")
                with self._lock:
                    ahead = min(self._expires.values(), default=None)
                forever = (
                    ahead is None or ahead == math.inf
                )  # a result with no hint waits for an event or a sweeper pass
                self._criteria_wake.wait(None if forever else max(0.0, ahead - self._clock()))
        finally:
            stop.unlisten(self._criteria_wake.set)

    def _keep_awaiting_delivery(self, stop: StopEvent) -> None:
        """Wake a holder that stayed busy `deliver_return_s` after it settled idle: its deliver run never came back."""
        while not stop.is_set():
            try:
                self._wake_overdue_deliveries()
            except Exception:  # one pass must not end the thread
                logger.exception("task actor: cannot wake the holders of the overdue deliver runs")
            stop.wait(min(self._deliver_return_s / 4, 60.0))

    def _wake_overdue_deliveries(self) -> None:
        """Hand `delivered` each holder busy past `deliver_return_s` that still holds its task In Progress, once. The
        task stays In Progress and its claim stays: the wake is the session's to act on. A hook runs outside the lock."""
        now = self._clock()
        with self._lock:
            overdue = [name for name, since in self._busy_since.items() if now - since >= self._deliver_return_s]
            for name in overdue:
                del self._busy_since[name]
        for name in overdue:
            agent = self._feed.task(name, lean=True)
            if agent is not None and agent["state"] == self._feed.roles.working and self._delivered:
                minutes = round(self._deliver_return_s / 60)
                self._delivered(name, f"deliver did not come back within {minutes} min of the session going idle")

    def _keep_rewaking(self, stop: StopEvent) -> None:
        """Tell the holder of a task resting in Verifying again, now and every `rewake_s` after its last wake: a holder
        whose session was reaped or stalled runs its post-merge QA until a verdict moves the task out. It moves no lane."""
        self.indexed.wait()
        while not stop.is_set():
            try:
                self._rewake()
            except Exception:  # one pass must not end the thread
                logger.exception("task actor: cannot wake the holders of the verifying tasks")
            stop.wait(self._rewake_s / 4)

    def _rewake(self) -> None:
        """Run the `verifying` hook again for each task still resting in Verifying `rewake_s` after its last wake, so a
        holder whose session was reaped or stalled runs its post-merge QA until a verdict moves the task out. A hook
        runs outside the lock, which it may hold for seconds."""
        lane = self._feed.roles.verifying
        if not (self._verifying and lane):
            return
        # a verdict whose move the actor never took, or whose exit write failed, leaves the lane here
        self._exit_all([agent for agent in self._feed.open_tasks() if agent["state"] == lane])
        now = self._clock()
        due = [
            agent["id"]
            for agent in self._feed.open_tasks()
            if agent["state"] == lane and now - self._woken.get(agent["id"], -self._rewake_s) >= self._rewake_s
        ]
        for name in due:
            self._woken[name] = now
            self._notice(self._verifying, name, "is in post-merge QA with no verdict but its holder was not told")

    def _stuck(self, agent: dict[str, Any]) -> tuple[str, ...]:
        """The dependencies that will not finish on their own: the Board holds no such task, or it is Proposed until the
        operator promotes it."""
        proposed = self._feed.roles.proposed
        reasons = []
        for dependency in agent["dependencies"]:
            found = self._feed.task(dependency, lean=True)
            if found and proposed and found["state"] == proposed:
                reasons.append(f"{dependency} is Proposed until the operator promotes it")
            elif dependency in self._missing(agent):
                reasons.append(f"{dependency} is not on the board")
        return tuple(reasons)

    def _missing(self, agent: dict[str, Any]) -> tuple[str, ...]:
        """The dependencies the Board holds in no store: no open task, none done, none archived. Nothing finishes them."""
        return tuple(
            dependency
            for dependency in agent["dependencies"]
            if not self._feed.is_open(dependency) and not self._cleared(dependency)
        )

    def _cleared(self, dependency: str) -> bool:
        """Whether the dependency is done, or archived: its file left the lanes without reaching Done."""
        return self._feed.is_done(dependency) or self._feed.is_archived(dependency)

    def _derive_overdue(self, name: str) -> None:
        """Derive a task again at its own deadline, so a Waiting task goes overdue with no event to wake it."""
        with self._lock:
            self._derive_all([name], self._clock())

    def reconcile_waiting(self) -> tuple[int, int]:
        """The sweeper's `waiting` pass: (the tasks in the lanes that wait on `deps_done`, those it released). A task whose
        dependencies are done and merged is released on the event that made them so; one found so on two passes in a row
        missed it, so it is derived again, and counted when that moved it on: a refused release does not count."""
        with self._lock:
            tasks = [agent for agent in self._feed.open_tasks() if agent["state"] in self._sweep_lanes]
            releasable = {agent["id"] for agent in tasks if self._deps_done(agent) is not None}
            missed = sorted(releasable & self._releasable)
            self._releasable = releasable
            for name in missed:
                self._tried.pop(name, None)
            self._derive_all(missed, self._clock())
            released = [name for name in missed if name not in self._parked]
        return len(tasks), len(released)

    def _evaluate_due(self) -> None:
        gated = {
            agent["id"]: agent["description"]
            for agent in self._feed.open_tasks()
            if agent["state"] in self._gated_lanes and criteria.authored(agent["description"])
        }
        with self._lock:
            for name in self._results.keys() - gated.keys():  # no longer gated: its result and its errors go
                del self._results[name]
                self._expires.pop(name, None)
                self._error_passes.pop(name, None)
            now = self._clock()
            generation = self._criteria_generation
            due = [name for name in sorted(gated) if name not in self._results or self._expires.get(name, 0.0) <= now]
        with ThreadPoolExecutor(
            max_workers=_EVALUATIONS
        ) as pool:  # a slow task must not hold up the ones sorted after it
            running = {pool.submit(self._evaluated, name, gated[name]): name for name in due}
            for finished in as_completed(running):
                self._keep_result(running[finished], gated[running[finished]], finished.result(), generation)

    def _evaluated(self, name: str, description: str) -> list[dict[str, Any]]:
        try:
            return self._evaluate(name, description)
        except Exception as error:  # an evaluator returns errors as results; this one raised
            logger.warning("task actor: cannot evaluate the Start Criteria of %s: %s", name, error)
            return [{"id": each["id"], "status": "error"} for each in criteria.authored(description)]

    def _keep_result(self, name: str, description: str, evaluated: list[dict[str, Any]], generation: int) -> None:
        statuses = tuple((str(each["id"]), str(each["status"])) for each in evaluated)
        observed = self._clock()
        with self._lock:
            current = self._feed.task(name, lean=True)
            if not current or criteria.authored(current["description"]) != criteria.authored(description):
                return  # parked again on other criteria, or gone, while it ran: the result is not this park's
            before = self._results.get(name)
            self._results[name] = (observed, statuses)
            wait = criteria.interval(evaluated)
            wait = max(wait, MIN_REFRESH_S)  # a zero hint would spin the loop
            # an event since the pass began reset the expiries; a result read before it is already due again
            self._expires[name] = observed if generation != self._criteria_generation else observed + wait
            if before is None or before[1] != statuses:
                self._derive(name, observed)
            self._count_error_passes(name, evaluated)

    def _run(self, stop: StopEvent) -> None:
        self._feed.wait_replayed()
        changes = self._feed.follow_changes()
        with self._lock:
            observed = self._clock()
            tasks = self._feed.open_tasks()
            for agent in tasks:
                self._index(agent)
            self._drop_holds_outside(tasks)
            self._read_pulls()
            open_ids = {agent["id"] for agent in tasks}
            self._derived = {name: digest for name, digest in self._derived.items() if name in open_ids}
        self.indexed.set()
        threading.Thread(
            target=self._recovered, args=(tasks, observed), name="task-actor-recovery", daemon=True
        ).start()  # a task or move change, a phase exit above all, is handled while recovery derives the rest

        def stopped() -> None:
            changes.put(("stop", {}))  # a stop wakes the wait below, which then sees it

        stop.listen(stopped)
        try:
            while not stop.is_set():
                self._beat()
                try:
                    kind, data = changes.get(timeout=_HEARTBEAT_S)
                except queue.Empty:
                    continue
                if kind in ("task", "move"):
                    handle = self._changed if kind == "task" else self._moved
                    try:
                        with self._pressing():
                            handle(data)
                    except Exception:  # one change must not end the actor
                        logger.exception("task actor: cannot handle the change of %s", data.get("id"))
        finally:
            stop.unlisten(stopped)
            self._end_notices()

    def _recovered(self, tasks: Sequence[dict[str, Any]], observed: float) -> None:
        self._recover(tasks, observed)
        self.ready.set()

    def _recover(self, tasks: Sequence[dict[str, Any]], observed: float) -> None:
        """Move each Review task whose pull request merged, then send each phase's missed exit, then derive every other
        open task whose facts differ from the checkpoint's (all of them when none is readable). A merge or a verdict that
        landed while the actor was down is the move an operator waits on, so neither waits for the derive of the whole
        board, which takes minutes. Each task is handled under its own hold of the lock, so a store save or a task
        change is handled between two tasks instead of waiting for the pass to end."""
        started = self._clock()
        report = self._reporter(started)
        names = sorted(agent["id"] for agent in tasks)
        with self._lock:
            merged = [agent["id"] for agent in sorted(tasks, key=lambda agent: agent["id"]) if self._merged_untried(agent)]

        def derive(batch: Sequence[str], offset: int) -> int:
            moved = 0
            for done, name in enumerate(batch, offset + 1):
                self._yield()
                with self._lock:  # the flag holds only under the lock, so no other thread's move reads it
                    if not self._unchanged(name):
                        self._recovering = True
                        try:
                            self._derive(name, observed)
                        finally:
                            self._recovering = False
                        moved += 1
                report("derived", done, len(names))
            return moved

        derived = derive(merged, 0)
        self._exit_all(tasks, lambda done, total: report("exited the phases of", done, total))
        settled = set(merged)
        derived += derive([name for name in names if name not in settled], len(merged))
        self.checkpoint()
        logger.info(
            "task actor: start recovery finished: %d tasks in %.1fs, %d unchanged since the checkpoint",
            derived,
            self._clock() - started,
            len(names) - derived,
        )

    def _reporter(self, started: float) -> Callable[[str, int, int], None]:
        """A function that logs how far recovery has come, at most once every `_PROGRESS_S`."""
        last = started

        def report(stage: str, done: int, total: int) -> None:
            nonlocal last
            self._beat()
            now = self._clock()
            if now - last >= _PROGRESS_S:
                last = now
                logger.info("task actor: start recovery %s %d of %d after %.0fs", stage, done, total, now - started)

        return report

    def _exit_all(
        self, tasks: Sequence[Mapping[str, Any]], report: Callable[[int, int], None] = lambda done, total: None
    ) -> None:
        """Send the exit event each of `tasks`, and each open task a phase machine places, is due, taking the lock once
        per task. A phase machine keeps every placement it made (tens of thousands, nearly all of closed tasks), and
        `_exit_phase` reads every parent for the task it takes, so each open task is swept once and a closed task's
        placement not at all."""
        open_ids = {agent["id"] for agent in self._feed.open_tasks()}
        names = {agent["id"] for agent in tasks} if BOARD in self._links else set()
        for parent in self._links.keys() - {BOARD}:
            placed = (each["id"] for each in self._feed.machine_tasks(parent))
            names.update(name for name in placed if self._feed.current_id(name) in open_ids)
        swept = sorted(names)
        for done, name in enumerate(swept, 1):
            with self._lock:
                self._exit_phase(name)
            report(done, len(swept))

    def _drop_stale_result(self, name: str, agent: dict[str, Any]) -> None:
        """Forget the last evaluation of a task that left the gated lanes or was gated on other criteria: the sweep
        that does so runs only between passes, and a slow evaluation holds a pass, so a task parked again would
        otherwise be released on the result of its last park."""
        gate = self._gate_of(agent)
        if self._gates.get(name) != gate:
            self._results.pop(name, None)
            self._expires.pop(name, None)
        self._gates[name] = gate
        if gate and name not in self._results:
            self._criteria_wake.set()  # a task entered a gated lane: its first result is due

    def _gate_of(self, agent: dict[str, Any]) -> list[dict[str, Any]] | None:
        return criteria.authored(agent["description"]) if agent["state"] in self._gated_lanes else None

    def _index(self, agent: dict[str, Any]) -> None:
        """Take `agent`'s lane, dependencies, pull requests and checked criteria into the indexes."""
        name = agent["id"]
        for url in self._seen.get(name, ("", (), (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._seen[name] = _view(agent)
        if self._lane_entered.get(name, ("",))[0] != agent["state"]:
            self._lane_entered[name] = (agent["state"], agent.get("entered") or 0.0)
        self._gates.setdefault(name, self._gate_of(agent))
        for url in agent["prs"]:
            self._by_pr.setdefault(url, set()).add(name)

    def _changed(self, data: dict[str, Any]) -> None:
        """Re-derive what a change of one task's record touches: the task itself when its lane, dependencies, pull
        requests or checked criteria changed, and the tasks depending on it when its lane or checked criteria did: a
        dependency stays open for criteria its dependent may not need."""
        observed = self._clock()
        name, agent = data["id"], data["agent"]
        with self._lock:
            before = self._seen.get(name)
            if agent is None:  # merged or gone: the tasks that waited on it may now proceed
                self._forget(name)
                self._derive_all(self._dependents(name), observed)
                return
            self._drop_stale_result(name, agent)
            repaired = name in self._lint_held and self._lint_held[name] != _lint_record(agent)
            if repaired:
                del self._lint_held[name]
                self._tried.pop(name, None)
            rearmed = agent["state"] in self._timed_lanes and tuple(
                criteria.expect_dates(agent["description"])
            ) != self._dates.get(name, ())
            if before == (now := _view(agent)) and not repaired and not rearmed:
                return
            self._index(agent)
            touched = {name}
            if before is None:  # a task created: a hold may have waited on it
                touched |= self._held
            if before is None or before[0] != now[0]:
                self._tried.pop(name, None)
                working = self._feed.roles.working
                if before and before[0] == self._review and now[0] == working:
                    self._sent_back[name] = self._heads(agent)
                    self._keep_holds()
                elif (before is not None or now[0] != working) and self._sent_back.pop(name, None) is not None:
                    self._keep_holds()  # a task first seen outside the working lane keeps no hold from an earlier run
            if before is None or (before[0], before[3]) != (now[0], now[3]):
                touched |= self._dependents(name)
            self._derive_all(touched, observed)

    def _moved(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._exit_phase(data["id"])
        self._finished(data["id"], data["agent"])

    def _finished(self, task: str, placed: Mapping[str, Any]) -> None:
        """Hand `delivered` the task and verdict of a move whose last step is a delivery run's end, `DELIVER_FINISHED`,
        so the session that holds the task resumes on the verdict without waiting on the run."""
        last = placed["trail"][-1] if placed.get("trail") else {}
        if not self._delivered or last.get("event") != DELIVER_FINISHED or self._told.get(task) == placed["steps"]:
            return
        self._told[task] = placed["steps"]
        with self._lock:
            self._idled.pop(task, None)  # the verdict wakes the holder to work: its next idle is the first again
        data = last.get("data") or {}
        verdict = " ".join(part for part in (data.get("verdict"), data.get("step")) if part)
        try:
            self._delivered(task, verdict)
            logger.info("task actor: %s finished its delivery (%s) and its holder was told", task, verdict)
        except Exception:  # the move stands; a board hook is a notice, not part of the write
            logger.exception("task actor: %s finished its delivery but its holder was not told", task)

    def _exit_phase(self, task: str) -> None:
        """Send the exit event of the phase `task` is in when that phase's skill machine sits in the state its link exits
        on. A skill machine the current phase does not link never counts, so a late final event of an earlier phase's
        skill advances nothing."""
        for parent, links in self._links.items():
            phase = self._phase(parent, task)
            event = self._exit_event(links, phase, task) if phase else None
            if phase and event and self._exited.get((parent, task)) != (phase["state"], phase["steps"], event):
                self._exited[parent, task] = (phase["state"], phase["steps"], event)
                target = self._moves.get((phase["state"], event)) if parent == BOARD else None
                if target:  # the Board's lane is the task's status: the exit is that write, not an event beside it
                    self._write(
                        task, target, f"{phase['state']} phase exited on {event}", self._clock(), phase["state"]
                    )
                else:
                    self._advance(parent, task, event)

    def _phase(self, parent: str, task: str) -> dict[str, Any] | None:
        """The phase `task` is in under lifecycle machine `parent`: the machine's placement, or the Board's lane, whose
        visit is told apart by when the task entered it (`since`, which a skill placement must not precede)."""
        if parent != BOARD:
            return self._feed.machine_task(parent, task)
        agent = self._feed.task(task, lean=True)
        entered = (agent or {}).get("entered") or 0.0
        lane, indexed = self._lane_entered.get(task, ("", 0.0))
        if agent and agent["state"] == lane:
            entered = indexed
        return {"state": agent["state"], "steps": entered, "since": entered} if agent else None

    def _exit_event(self, links: Sequence[Mapping[str, Any]], phase: Mapping[str, Any], task: str) -> str | None:
        for link in links:
            placed = self._feed.machine_task(link["machine"], task) if link["state"] == phase["state"] else None
            if placed and placed["active"] >= phase.get("since", 0.0) and link["exits"].get(placed["state"]):
                return self._route(link, task) or link["exits"][placed["state"]]
        return None

    def _route(self, link: Mapping[str, Any], task: str) -> str | None:
        """The event of the link's route to the phase after it in the sequence of `task`'s type, when the link draws one."""
        kind = (self._feed.task(task, lean=True) or {}).get("type", "").lower()
        sequence = self._sequences.get(kind) or self._sequences.get("default", ())
        following = sequence[sequence.index(link["state"]) + 1 :][:1] if link["state"] in sequence else ()
        return link.get("routes", {}).get(following[0]) if following else None

    def _restored_holds(self) -> dict[str, dict[str, str]]:
        """The holds the worker state kept, so a restart of the actor keeps each sent-back task's hold."""
        if self._log is None:
            return {}
        try:
            _, held = self._log.state(SENT_BACK)
        except Exception:  # the actor runs without the holds a read cannot give: a notice, never a refused start
            logger.exception("task actor: cannot read the sent-back holds")
            return {}
        return dict(held or {})

    def _keep_holds(self) -> None:
        """Keep the sent-back holds in the worker state, after each change to them."""
        if self._log is None:
            return
        try:
            self._log.put_state(SENT_BACK, self._sent_back)
        except Exception:  # the hold stands in memory; a database error is a notice, not part of the derivation
            logger.exception("task actor: cannot keep the sent-back holds")

    def _drop_holds_outside(self, tasks: Sequence[dict[str, Any]]) -> None:
        """Drop each restored hold whose task a restart found outside the working lane, as its hold ends there."""
        working = self._feed.roles.working
        lanes = {agent["id"]: agent["state"] for agent in tasks}
        stale = [name for name in self._sent_back if lanes.get(name) != working]
        for name in stale:
            del self._sent_back[name]
        if stale:
            self._keep_holds()

    def _restored_checkpoint(self) -> dict[str, str]:
        """The digests the checkpoint kept, or none when it is missing, unreadable or taken under other waits and moves:
        a start then derives every open task."""
        if self._log is None:
            return {}
        try:
            _, kept = self._log.state(CHECKPOINT)
        except Exception:  # the actor runs without the checkpoint a read cannot give: a notice, never a refused start
            logger.exception("task actor: cannot read the checkpoint")
            return {}
        if not isinstance(kept, dict) or kept.get("rules") != self._rules or not isinstance(kept.get("facts"), dict):
            return {}
        return {str(name): str(digest) for name, digest in kept["facts"].items()}

    def checkpoint(self) -> None:
        """Keep the digests of the facts each task was last derived on, when they changed since the last save."""
        if self._log is None:
            return
        with self._lock:
            facts = dict(self._derived)
        if facts == self._kept:
            return
        try:
            self._log.put_state(CHECKPOINT, {"rules": self._rules, "facts": facts})
        except Exception:  # the next save keeps it; a database error is a notice, not part of the derivation
            logger.exception("task actor: cannot keep the checkpoint")
        else:
            self._kept = facts

    def _keep_checkpoint(self, stop: StopEvent) -> None:
        """Save the checkpoint every `_CHECKPOINT_S` while recovery or the actor runs, and once more on a stop."""
        try:
            while not stop.wait(_CHECKPOINT_S):
                self.checkpoint()
        finally:
            self.checkpoint()

    def _unchanged(self, name: str) -> bool:
        """Whether the task's facts digest to what it was last derived on; when they do, arm its deadline, the one thing
        a derivation leaves in memory that nothing else rebuilds at start."""
        agent = self._feed.task(name)
        if agent is None or self._derived.get(name) != self._digest(agent):
            return False
        self._arm(name, agent)
        return True

    def _digest(self, agent: dict[str, Any]) -> str:
        """A digest of every fact a derivation of the task reads: its record, its dependencies' lanes and checked
        criteria, the state of each pull request it cites, and whether its deadline has passed."""
        name = agent["id"]
        dependencies = []
        for dependency in agent["dependencies"]:
            other = self._feed.task(dependency)
            dependencies.append((dependency, self._cleared(dependency), other and _view(other)))
        pulls = [(url, self._pull_state(url)) for url in agent["prs"]]
        timed = agent["state"] in self._timed_lanes
        deadline = self._deadline(agent) if timed else None
        facts = (
            name,
            _view(agent),
            _lint_record(agent),
            agent.get("type"),
            dependencies,
            pulls,
            agent.get("entered") if timed else None,
            bool(deadline and deadline[0] <= self._wall()),
        )
        return hashlib.sha1(repr(facts).encode(), usedforsecurity=False).hexdigest()[:16]

    def _forget(self, name: str) -> None:
        self._derived.pop(name, None)
        for url in self._seen.pop(name, ("", (), (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._tried.pop(name, None)
        self._idled.pop(name, None)
        if self._sent_back.pop(name, None) is not None:
            self._keep_holds()
        self._lint_held.pop(name, None)
        self._deadlines.cancel(name)
        self._dates.pop(name, None)
        self._gates.pop(name, None)
        self._lane_entered.pop(name, None)
        self._expires.pop(name, None)

    def _dependents(self, name: str) -> set[str]:
        return {
            other
            for other, (_, dependencies, *_) in self._seen.items()
            if name in map(self._feed.current_id, dependencies)
        }

    def pulls_changed(self) -> None:
        """Re-derive the tasks whose pull requests read differently since the last call; the server calls it after each
        projection of the pull request store."""
        observed = self._clock()
        with self._pressing(), self._lock:
            touched = self._read_pulls()
            if self._store.rev != self._store_rev:  # a pin bump is no pull request any task cites
                self._store_rev = self._store.rev
                touched |= self._pin_held
            self._derive_pulled(touched, observed)

    def _read_pulls(self) -> set[str]:
        """The tasks citing a pull request whose state changed since it was last read."""
        touched: set[str] = set()
        for url, names in self._by_pr.items():
            if self._pull_states.get(url) != (state := self._pull_state(url)):
                self._pull_states[url] = state
                touched |= names
        return touched

    def _record(self, url: str) -> dict[str, Any] | None:
        return pull_record(self._store, url)

    def _own_prs(self, agent: dict[str, Any]) -> list[str]:
        return own_prs(self._store, agent)

    def _proof_prs(self, agent: dict[str, Any]) -> list[str]:
        """The pull requests whose ends prove a task's work. In Review, a task with no own pull request merged takes
        every cited one: another task's delivery may have superseded its own, which closed unmerged or never existed."""
        own = self._own_prs(agent)
        if agent["state"] != self._review:
            return own
        if any((record := self._record(url)) and record["state"] == "MERGED" for url in own):
            return own
        return agent["prs"]

    def _pull_state(self, url: str) -> tuple[str, str | None, bool, str, str, str, str]:
        record = self._record(url)
        if record is None:
            return "", None, False, "", "", "", ""
        return (
            record["state"],
            record["mergeSha"],
            record["isDraft"],
            record["headRefOid"],
            record["mergeable"],
            checks_verdict(record["state"], record["checks"], record["headRefOid"], record["rollup"]),
            record.get("updatedAt") or "",
        )

    def _heads(self, agent: dict[str, Any]) -> dict[str, str]:
        """The head of each own pull request of the task the store holds."""
        records = {url: self._record(url) for url in self._own_prs(agent)}
        return {url: record["headRefOid"] for url, record in records.items() if record}

    def _derive_all(self, names: Any, observed: float) -> None:
        for name in sorted(names):
            self._derive(name, observed)

    def _derive_pulled(self, names: Iterable[str], observed: float) -> None:
        """Derive the tasks whose pull requests a store read found changed, in name order but those citing a merged one
        first: their move is the one a merge waits for."""

        def merged(name: str) -> bool:
            urls = self._seen[name][2] if name in self._seen else ()
            return any((record := self._record(url)) and record["state"] == "MERGED" for url in urls)

        for name in sorted(names, key=lambda name: (not merged(name), name)):
            self._derive(name, observed)

    def _derive(self, name: str, observed: float) -> None:
        """Derive the task's waits, time the derivation, and note the facts it settled on for the checkpoint."""
        agent = self._feed.task(name, lean=True)
        if agent is None:
            return
        digest = self._digest(agent)
        self._hooked = self._unsettled = False
        started = self._clock()
        try:
            self._derive_waits(name, agent, observed)
        finally:
            self._timed_derive(agent["state"], self._hooked, self._clock() - started)
        if self._unsettled or name in self._held or name in self._pin_held:
            self._derived.pop(name, None)  # its hold or failure can end with no fact of the task changing
        else:
            self._derived[name] = digest

    def _timed_derive(self, lane: str, hooked: bool, seconds: float) -> None:
        with self._metrics:
            histogram = self._derive_seconds.setdefault((lane, hooked), _Histogram(SLOW_BUCKETS_S))
        histogram.observe(seconds)

    def _derive_waits(self, name: str, agent: dict[str, Any], observed: float) -> None:
        """Write the first move the task's lane waits on whose fact holds. A move already tried on these facts, or one the
        board refuses, leaves the next fact its turn: a Waiting task whose return to Review is refused still reaches Ready."""
        self.derivations[name] += 1
        if agent["state"] != self._feed.roles.working:
            self._idled.pop(name, None)
            self._restarts.pop(name, None)
        self._arm(name, agent)
        if agent["state"] in self._sweep_lanes and (reasons := self._stuck(agent)):
            self._note_hold(agent, reasons, FLAGGED)
        for fact, event in self._waits.get(agent["state"], {}).items():
            target = self._moves.get((agent["state"], event))
            held = self._facts.get(fact, lambda *_: None)(self, agent) if target else None
            if held is None:
                continue
            evidence, comment = held
            if fact in _ASKS and fact != "holder_idle" and self._answered(agent, comment):
                continue
            sent = (agent["state"], event, evidence)
            if self._tried.get(name) == sent:
                continue
            self._tried[name] = sent
            changes = self._stale(agent) if fact.startswith("deps_done") else {}
            if fact in _ASKS:
                changes = {"description": section_set(agent["description"], "Needs attention", comment)}
                if fact == "overdue" and self._missing(agent):
                    changes["dependencies"] = []  # Needs attention carries none; the reason names them
            if target == agent["state"]:
                if self._enqueued:
                    self._notice(
                        self._enqueued,
                        name,
                        "was ready but its pull request was not enqueued",
                        on_failure=lambda: self._tried.pop(name, None),  # tried again on the next derivation
                    )
                return
            merged = self._merged_at(agent) if fact in _MERGE_FACTS else None
            if self._write(name, target, comment, observed, source=agent["state"], stale=changes, merged=merged):
                if fact == "holder_idle":
                    self._clear(name, target)
                if self._verifying and fact == "pr_merged_planned":
                    self._woken[name] = self._clock()
                    self._notice(self._verifying, name, "entered post-merge QA but its holder was not told")
                return

    def _merged_at(self, agent: dict[str, Any]) -> float | None:
        """When the latest of the pull requests that proved `agent`'s work merged."""
        merges = (
            _epoch(record["mergedAt"])
            for url in self._proof_prs(agent)
            if (record := self._record(url)) and record["state"] == "MERGED" and record["mergedAt"]
        )
        return max((at for at in merges if at is not None), default=None)

    def holder_settled(self, name: str) -> None:
        """A session settled idle. The first idle of an In Progress task's holder runs the `idle` hook to resume it to
        checkpoint; the second confirms it and releases its claim in place and starts a session on the task, up to
        `IDLE_RESTARTS` times, after which it derives the task, whose `holder_idle` fact then holds. A hook that fails
        found the holder at work, and that idle is not counted."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            if self._idle is None or agent is None or agent["state"] != self._feed.roles.working:
                self._idled.pop(name, None)
                self._restarts.pop(name, None)
                self._busy_since.pop(name, None)
                return
            count = self._idled.get(name, 0)
        try:
            self._idle(name, "confirm" if count else "checkpoint")
        except Exception as error:
            logger.info("task actor: %s settled idle but its holder was not reached: %s", name, error)
            with self._lock:
                self._busy_since.setdefault(name, self._clock())
            return
        with self._lock:
            self._busy_since.pop(name, None)
            restart = bool(count) and self._restarts.get(name, 0) < IDLE_RESTARTS
        if restart and self._restart(name):
            return
        with self._lock:
            self._idled[name] = count + 1
            if count:
                self._derive(name, self._clock())

    def _restart(self, name: str) -> bool:
        """Release the claim of a holder idle again after its checkpoint request, leaving the task In Progress with a
        comment naming why, and start a session on it. A release or start that fails ends the restarts, so the idle is
        asked about instead."""
        if self._release is None or self._read is None:
            return False
        try:
            session = (self._read(name) or {}).get("session")
            if not session or not self._release(name, self._feed.roles.working, session=session, actor=ACTOR).ok:
                return False
            with self._lock:
                self._restarts[name] = tried = self._restarts.get(name, 0) + 1
                self._idled.pop(name, None)
            self._edit(name, {}, f"{IDLE_RELEASE}; a session is started on it again ({tried} of {IDLE_RESTARTS}).", actor=ACTOR)
            self._idle(name, "restart")
        except Exception as error:
            logger.warning("task actor: the idle holder of %s was not restarted: %s", name, error)
            with self._lock:
                self._restarts[name] = IDLE_RESTARTS
            return False
        return True

    def _holder_idle(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The idle count and the Needs attention question once the holder settled idle again after being resumed."""
        count = self._idled.get(agent["id"], 0)
        if count < 2:
            return None
        return count, (
            "holder_idle: the session holding this task went idle again after it was told to checkpoint, so its claim "
            "is cleared. Resume it, or return it to Ready?"
        )

    def _clear(self, name: str, lane: str) -> None:
        """End the claim of a task `holder_idle` just parked: the session is idle and no longer holds it."""
        self._idled.pop(name, None)
        if self._release is None or self._read is None:
            return
        try:
            session = (self._read(name) or {}).get("session")
            if session:
                self._release(name, lane, session=session, actor=ACTOR)
        except Exception as error:
            logger.warning("task actor: the claim of %s was not cleared: %s", name, error)

    def _answered(self, agent: dict[str, Any], ask: str) -> bool:
        """Whether the operator already answered this very ask: an `Operator answer` comment follows the last time the
        task carried `ask`, so parking the task on it again would put the question to them twice. A new ask (another
        pull request, another reason) is a new question."""
        if self._read is None:
            return False
        try:
            comments = (self._read(agent["id"]) or {}).get("comments") or []
        except Exception as error:
            logger.warning("task actor: cannot read the comments of %s: %s", agent["id"], error)
            return False
        texts = [str(comment.get("text") or "") for comment in comments]
        asked = [index for index, text in enumerate(texts) if text.strip() == ask.strip()]
        return bool(asked) and any(_ANSWER_COMMENT.match(text) for text in texts[asked[-1] + 1 :])

    def _write(
        self,
        name: str,
        target: str,
        comment: str,
        observed: float,
        source: str,
        stale: Mapping[str, Any] = {},
        merged: float | None = None,
    ) -> bool:
        written = self._apply(name, {"status": target, **stale}, comment)
        if written.ok and self._recovering:
            logger.error(
                "task actor: start recovery moved %s %s -> %s, a move its lane's events missed", name, source, target
            )
        if written.ok:
            self._landed(self._clock() - observed)
            if merged is not None:  # timed at the lane write, ahead of the hooks that tell the board and the holder
                self._merge_move.observe(max(0.0, self._wall() - merged))
            roles = self._feed.roles
            if self._tell and source == roles.working and target == roles.waiting:
                self._notice(self._tell, name, "was parked but its holder was not told")
            if self._released and source == roles.waiting and target == roles.ready:
                self._notice(self._released, name, "was released but its holder was not told")
            if self._returned and target == roles.working:
                self._notice(self._returned, name, "was sent back but its holder was not told")
            if self._closed and target == roles.done:
                self._notice(self._closed, name, "was closed but the board was not told")
            return True
        logger.warning("task actor: %s was not moved to %s: %s", name, target, written.output)
        if written.transient:  # not a refusal: the task stays in its lane and the next pass tries the move again
            self._unsettled = True
            self._tried.pop(name, None)
            self._exited.pop((BOARD, name), None)  # a Board exit goes again on the next pass
            return False
        if target == self._feed.roles.ready:
            if written.lint:
                self._hold_for_repair(name, written.output)
            else:
                self._park(name, written.output)
        elif target == self._feed.roles.done:
            self._hold_done(name, written.output)
        elif target == self._review and source == self._feed.roles.working:
            self._hold_review(name, written.output)
        with self._metrics:
            self._refusals += 1
        return False

    def _hold_done(self, name: str, refusal: str) -> None:
        """Record a refused Done move on the task and hand its holder the refusal through `delivered`: the move is not
        tried again until the task's facts change, so without the note and the wake a merged task sits in its lane."""
        reason = refusal.rstrip(".")
        written = self._apply(name, {}, f"{DONE_HELD} {reason}.")
        if not written.ok:
            logger.warning("task actor: the Done refusal of %s was not commented: %s", name, written.output)
        if self._delivered:
            try:
                self._delivered(name, f"merged but Done refused: {reason}")
            except Exception:  # the note stands; a board hook is a notice, not part of the write
                logger.exception("task actor: %s was refused Done but its holder was not told", name)

    def _hold_review(self, name: str, refusal: str) -> None:
        """Hand a working task's holder the refusal of its move to Review through `delivered`: the move is not tried
        again until the task's facts change, so without the wake a ready pull request with an open thread sits In
        Progress with no one told."""
        if self._delivered:
            try:
                self._delivered(name, f"Review refused: {refusal.rstrip('.')}")
            except Exception:  # a board hook is a notice, not part of the write
                logger.exception("task actor: %s was refused Review but its holder was not told", name)

    def _count_error_passes(self, name: str, evaluated: list[dict[str, Any]]) -> None:
        """Count the passes whose Start Criteria stayed in error; the second in a row re-gates the task."""
        errors = [each for each in evaluated if each["status"] == "error"]
        if not errors:
            self._error_passes.pop(name, None)
            return
        self._error_passes[name] = self._error_passes.get(name, 0) + 1
        if self._error_passes[name] == 2:
            self._regate(name, errors)

    def _regate(self, name: str, errors: list[dict[str, Any]]) -> None:
        """Comment the errors on a task whose criteria cannot be evaluated and file an unattended Ready task to re-park
        it on criteria that can. No operator question and no Needs attention: the task stays in its lane."""
        reasons = "; ".join(f"{each['id']}: {each.get('error') or 'error'}" for each in errors)
        written = self._apply(name, {}, f"{REGATE} {reasons}.")
        if not written.ok:
            logger.warning("task actor: the re-gate of %s was not commented: %s", name, written.output)
        if self._create is None:
            return
        priority = (self._feed.task(name, lean=True) or {}).get(
            "priority"
        ) or "medium"  # the re-gate is as urgent as the task it unblocks
        try:
            filed = self._create(
                f"Re-gate {name}: re-park it on Start Criteria that can be evaluated",
                {
                    "description": f"{REGATE} {reasons}.\n\nRe-park {name} on Start Criteria the evaluator can answer, then move it back to Waiting.",
                    "acceptanceCriteria": [f"{name} is back in Waiting on Start Criteria the evaluator can answer"],
                    "labels": ["kind-execute", "size-1", "mode-unattended"],
                    "priority": priority,
                    "type": "chore",
                },
                actor=ACTOR,
            )
        except Exception as error:  # a board that raises refuses like one that answers no
            filed = Written(False, str(error))
        if not filed.ok:
            logger.warning("task actor: the re-gate task for %s was not filed: %s", name, filed.output)
            return
        ready = self._apply(filed.output, {"status": self._feed.roles.ready}, f"Re-gate of {name}.")
        if not ready.ok:
            logger.warning("task actor: the re-gate task %s was not released to Ready: %s", filed.output, ready.output)

    def _hold_for_repair(self, name: str, refusal: str) -> None:
        """Leave a task whose release the board's lint refused in its lane and comment the lint's reason, no operator
        question: any editor of the record repairs it, and the actor tries the release again when the record changes."""
        self._lint_held[name] = _lint_record(self._feed.task(name, lean=True))
        written = self._apply(name, {}, f"{LINT_REFUSED} {refusal.rstrip('.')}.")
        if not written.ok:
            logger.warning("task actor: the lint refusal of %s was not commented: %s", name, written.output)

    def _notice(
        self, hook: Callable[[str], None], name: str, missed: str, on_failure: Callable[[], None] | None = None
    ) -> None:
        """Queue the board's `parked`, `released` or `closed` hook for a task the actor just moved, to run after the
        move releases the actor's lock; a failure is logged, then `on_failure` runs."""
        self._hooked = True

        def run() -> None:
            try:
                hook(name)
            except Exception:  # the move stands; a board hook is a notice, not part of the write
                logger.exception("task actor: %s %s", name, missed)
                if on_failure is not None:
                    on_failure()

        with self._noticing:
            if self._noticing_ended:
                return  # a stopped actor drains the notices it queued and takes no more
            self._notices.put(run)
            if self._notifier is None:
                self._notifier = threading.Thread(target=self._run_notices, name="task-actor-hooks", daemon=True)
                self._notifier.start()

    def _run_notices(self) -> None:
        while (notice := self._notices.get()) is not None:
            notice()

    def _end_notices(self) -> None:
        """Run the notices already queued, then join the notifier; a stop calls it."""
        with self._noticing:
            self._noticing_ended = True
            notifier = self._notifier
            self._notices.put(None)
        if notifier is not None:
            notifier.join(timeout=_NOTICE_JOIN_S)

    def _park(self, name: str, refusal: str) -> None:
        """Write a task whose release to Ready was refused to Needs attention, with the refusal as its reason."""
        if self._parked.get(name) == refusal:
            return
        self._parked[name] = refusal
        reason = f"{refusal.rstrip('.')}. Clear it so the task can return to Ready?"
        description = section_set(self._feed.task(name, lean=True)["description"], "Needs attention", reason)
        written = self._apply(name, {"status": self._feed.roles.attention, "description": description}, reason)
        if not written.ok:
            logger.warning("task actor: %s was not parked in Needs attention: %s", name, written.output)

    def _apply(self, name: str, changes: Mapping[str, Any], comment: str) -> Written:
        with self._feed.recording:  # the board's poll finds the lane recorded under the actor, not as external
            written = self._edit_retrying(name, changes, comment)
            if written.ok and written.lane:
                self._feed.record_written(name, written.lane, written.at or time.time(), (ACTOR, "", ""))
        return written

    def _edit_retrying(self, name: str, changes: Mapping[str, Any], comment: str) -> Written:
        """The board's edit, retried with backoff while SQLite reports the database locked; a lock that outlasts the
        retries is `transient`, a failure of the database and no refusal of the change."""
        for delay in (*LOCK_BACKOFF_S, None):
            try:
                return self._edit(name, changes, comment, actor=ACTOR)
            except Exception as error:  # a board that raises refuses like one that answers no
                if "database is locked" not in str(error):
                    return Written(False, str(error))
                if delay is None:
                    return Written(False, str(error), transient=True)
                time.sleep(delay)
        raise AssertionError("unreachable")

    def _landed(self, seconds: float) -> None:
        with self._metrics:
            at = next((i for i, bound in enumerate(BUCKETS_S) if seconds <= bound), len(BUCKETS_S))
            for i in range(at, len(self._buckets)):
                self._buckets[i] += 1
            self._sum += seconds

    def _pr_terminal(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The merge evidence when the task cites pull requests and every one has ended, else None. A check task that
        cites only other tasks' pull requests has no delivery of its own to wait for: its checked criteria close it.
        Review proves its work on `_proof_prs`; every other lane still waits on its own pull requests only."""
        own = self._own_prs(agent)
        if not own and agent["prs"] and agent["type"] == "check":
            proof = f"no pull request of its own; cites {', '.join(agent['prs'])}"
            return proof, f"{MERGE_EVIDENCE} {proof}"
        parts = []
        for url in self._proof_prs(agent):
            record = self._record(url)
            if record is None or record["state"] not in _TERMINAL:
                return None
            if record["state"] == "MERGED" and not record["mergedAt"]:
                return None  # merged on an event's word alone: the next read of GitHub settles it
            link = f"PR #{record['number']}" if record["repo"] == self._board_repo else url
            if record["state"] == "MERGED" and not landed(self._store, record):
                # merged into an integration branch not yet on main: the work is not delivered
                self._note_hold(agent, (f"{link} merged into {record['baseRefName']}, not main",), DONE_HELD)
                return None
            part = f"{record['repo']}#{record['number']} {record['state'].lower()}"
            if record["mergeSha"]:
                part += f" as {record['mergeSha']}"
            parts.append(f"{part} ({link})")
        if not parts:
            return None
        proof = "; ".join(parts)
        return proof, f"{MERGE_EVIDENCE} {proof}"

    def _planned(self, agent: dict[str, Any]) -> bool | None:
        """Whether the task's record carries a Verify plan; None when the board's read raises, which settles neither
        route until the task is derived again."""
        if self._read is None:
            return False
        try:
            record = self._read(agent["id"])
        except Exception as error:
            logger.warning("task actor: cannot read the Verify plan of %s: %s", agent["id"], error)
            return None
        return bool(record and record.get("verifyPlan"))

    def _merged(self, agent: dict[str, Any], planned: bool) -> tuple[str, str] | None:
        """The merge evidence when every pull request the task cites has ended and at least one merged, and the task's
        Verify plan is present exactly when `planned`, else None: a delivery closed unmerged is no proof of the work. A
        closed one beside a merged one holds the task, since the board refuses a merge proof while a cited PR is not
        merged: the hold comment names it for the holder to drop."""
        terminal = self._pr_terminal(agent)
        records = [self._record(url) for url in self._proof_prs(agent)]
        merged = any(record and record["state"] == "MERGED" for record in records)
        closed = [record for record in records if record and record["state"] != "MERGED"]
        if terminal and merged and closed:
            cited = ", ".join(f"{record['repo']}#{record['number']}" for record in closed)
            reason = f"{cited} closed unmerged; drop it with `backlog-task update --remove-ref` to close the task"
            self._note_hold(agent, (reason,), DONE_HELD)
            return None
        return terminal if terminal and merged and self._planned(agent) is planned else None

    def _pr_closed_unmerged(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The closed pull requests and the Needs attention question when every pull request the task cites has ended and
        none merged: its delivery is gone and no merge will ever close it."""
        terminal = self._pr_terminal(agent)
        merged = any((record := self._record(url)) and record["state"] == "MERGED" for url in self._proof_prs(agent))
        if not terminal or merged:
            return None
        return terminal[0], (
            f"Every pull request it cites closed unmerged: {terminal[0]}. Close it as superseded, or redeliver it?"
        )

    def _pr_closed_unmerged_complete(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The closed pull requests when `_pr_closed_unmerged` holds and every criterion is checked: the work was done
        without a merge (a no-op), so nothing is left to ask the operator."""
        closed = self._pr_closed_unmerged(agent)
        ticks = tuple(criterion["checked"] for criterion in agent.get("criteria", ()))
        if not closed or not ticks or not all(ticks):
            return None
        return closed[0], f"Every pull request it cites closed unmerged and every criterion is checked: {closed[0]}."

    def _pr_merged(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """`_merged` for a task with no Verify plan."""
        return self._merged(agent, planned=False)

    def _pr_merged_planned(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """`_merged` for a task with a Verify plan."""
        return self._merged(agent, planned=True)

    def _pr_merged_unfinished(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The merge evidence and what is left when the task's pull requests merged, with or without a Verify plan, and
        the board reports work unfinished, else None. A command that fails reports its error: the task returns to its
        holder, never closes."""
        merged = self._pr_merged(agent) or self._pr_merged_planned(agent)
        if merged is None or self._unfinished is None:
            return None
        try:
            left = tuple(self._unfinished(agent["id"]))
        except Exception as error:
            logger.warning("task actor: cannot read the unfinished work of %s: %s", agent["id"], error)
            left = (f"the board's unfinished work cannot be read: {error}",)
        if not left:
            return None
        proof, comment = merged
        return (proof, left), f"{comment} Unfinished: {'; '.join(left)}."

    def _pr_ready(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The ready or merged pull requests when the task cites one that is, else None. A task sent back from Review
        stays put while its ready pull request keeps the head it was sent back on: a new head or a run of `review` is the
        session's answer. An open pull request is ready only once the rollup of its current head says every required check
        passed (`checks_verdict`): a required check not posted is not green, a push re-arms the gate, and a repository
        whose ruleset requires none rolls up passed as soon as the pull request is not a draft."""
        parts = []
        held = self._sent_back.get(agent["id"], {})
        # In the working lane a PR merged before the task's latest entry is shipped work (a post-merge send back).
        floor = (agent.get("entered") or 0.0) if agent["state"] == self._feed.roles.working else 0.0
        for url in self._own_prs(agent):
            record = self._record(url)
            if record is None:
                continue
            merged = record["state"] == "MERGED" and record["mergedAt"]
            if merged and (_epoch(record["mergedAt"]) or 0.0) < floor:
                continue
            reviewed = held.get(url) == record["headRefOid"]
            green = checks_verdict(record["state"], record["checks"], record["headRefOid"], record["rollup"]) == "pass"
            if merged or (record["state"] == "OPEN" and not record["isDraft"] and green and not reviewed):
                parts.append(f"{record['repo']}#{record['number']} {'merged' if merged else 'ready'}")
        if not parts:
            return None
        proof = "; ".join(parts)
        return proof, f"Pull request ready: {proof}"

    def _open_pulls(
        self, agent: dict[str, Any], said: str, problem: Callable[[dict[str, Any]], bool]
    ) -> tuple[str, str] | None:
        """The open pull requests of the task's own delivery that `problem` holds of, with the comment `said` names them
        in, else None. The head commit is in the evidence, so a push that fails or conflicts again is a new fact."""
        parts = []
        for url in self._own_prs(agent):
            record = self._record(url)
            if record is not None and record["state"] == "OPEN" and problem(record):
                parts.append(f"{record['repo']}#{record['number']} at {record['headRefOid'][:12]}")
        if not parts:
            return None
        proof = "; ".join(parts)
        return proof, f"{said}: {proof}."

    def _pr_failing(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The open pull requests whose required checks failed, with the question the task's reason ends in, else None."""
        failing = self._open_pulls(agent, "Pull request checks failed", lambda record: record["checks"] == "failing")
        return failing and (failing[0], f"{failing[1]} {ATTENTION_QUESTION}")

    def _pr_draft(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The open pull requests that are drafts, else None."""
        return self._open_pulls(agent, "Pull request is a draft", lambda record: record["isDraft"])

    def _pr_conflicting(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The open pull requests that conflict with their base, else None."""
        return self._open_pulls(
            agent, "Pull request conflicts with its base", lambda record: record["mergeable"] == "CONFLICTING"
        )

    def _pr_unfinished(self, agent: dict[str, Any], alive: bool) -> tuple[str, str] | None:
        """The first of the failing, draft and conflicting facts that holds, once the task's holder is running (`alive`) or
        is not. A holder the probe cannot reach leaves the task where it is for the next pass."""
        held = self._pr_failing(agent) or self._pr_draft(agent) or self._pr_conflicting(agent)
        if held is None:
            return None
        try:
            running = bool(self._alive and self._alive(agent["id"]))
        except Exception as error:
            logger.warning("task actor: the holder of %s was not probed: %s", agent["id"], error)
            return None
        if running != alive:
            return None
        return held[0], f"{held[1]} {'Sent back to its session' if alive else 'Returned to Ready for a new session'}."

    def _pr_unfinished_alive(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The not-green pull request of a task whose holding session is running."""
        return self._pr_unfinished(agent, True)

    def _pr_unfinished_dead(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The not-green pull request of a task no running session holds."""
        return self._pr_unfinished(agent, False)

    def _deps_done(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The dependencies once every one is done and merged, an empty tuple when the task has none, and no Start
        Criteria gate it."""
        dependencies = tuple(agent["dependencies"])
        self._pin_held.discard(agent["id"])
        self._held.discard(agent["id"])
        if self._unmet(agent) or criteria.authored(agent["description"]):
            return None
        if waiting := self._gate.waiting_on(agent):
            self._pin_held.add(agent["id"])
            self._note_hold(agent, (waiting,))
            return None
        if reasons := self._held_by(agent["id"]):
            self._held.add(agent["id"])
            self._note_hold(agent, reasons)
            return None
        comment = "Every dependency has merged."
        if stale := self._early(agent):
            comment = (
                f"Stale dependency {', '.join(stale)}: it stays open for criteria this task does not need. {comment}"
            )
        return dependencies, comment

    def _deps_done_with_pr(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """`deps_done` for a task that cites a ready or merged pull request, which a state returns to Review rather than Ready."""
        return self._deps_done(agent) if self._pr_ready(agent) else None

    def _held_by(self, name: str) -> tuple[str, ...]:
        """Why the board adapter withholds the task's `deps_done`; a hold that raises holds it with that error."""
        if self._holds is None:
            return ()
        self._hooked = True
        try:
            return tuple(self._holds(name))
        except Exception as error:
            self._unsettled = True
            logger.warning("task actor: cannot read the holds of %s: %s", name, error)
            return (f"the board's holds cannot be read: {error}",)

    def _note_hold(self, agent: dict[str, Any], reasons: tuple[str, ...], prefix: str = HELD) -> None:
        """Comment the hold's reasons on the task under `prefix`, once until they or its lane change."""
        name, sent = agent["id"], (agent["state"], "hold", reasons)
        if self._tried.get(name) == sent:
            return
        self._tried[name] = sent
        logger.info("task actor: %s is held: %s", name, "; ".join(reasons))
        try:
            written = self._edit(name, {}, _hold_comment(prefix, reasons), actor=ACTOR)
        except Exception as error:
            written = Written(False, str(error))
        if not written.ok:
            logger.warning("task actor: the hold of %s was not written: %s", name, written.output)
            with self._metrics:
                self._refusals += 1

    def _arm(self, name: str, agent: dict[str, Any]) -> None:
        """Arm the deadline wait of a task in a lane that waits on `overdue`, when its deadline is still ahead; drop it
        from the wait otherwise. Every derivation re-arms, so a re-park, a new `expect_by` or a dependency's lane
        change moves the deadline."""
        self._deadlines.cancel(name)
        if agent["state"] not in self._timed_lanes:
            self._dates.pop(name, None)
            return
        self._dates[name] = tuple(criteria.expect_dates(agent["description"]))
        deadline = self._deadline(agent)
        if deadline and deadline[0] > self._wall():
            self._deadlines.arm(name, deadline[0])

    def _deadline(self, agent: dict[str, Any]) -> tuple[float, str] | None:
        """When the task's service level expectation ends, in epoch seconds, and what it is counted from; None while the
        task is exempt (gated only on dependencies, each still In Progress or Review) or has no entry time.
        The SLE is the latest `expect_by` plus two days, else seven days from entering the lane."""
        if not agent.get("entered"):
            return None
        if self._missing(agent):
            return agent["entered"], "a dependency is not on the board"
        if not criteria.authored(agent["description"]) and self._moving(agent):
            return None
        dates = [stamp for stamp in map(_epoch, criteria.expect_dates(agent["description"])) if stamp]
        if dates:
            return max(dates) + _GRACE_DAYS * _DAY_S, f"expect_by {_stamp(max(dates))} plus {_GRACE_DAYS} days"
        return agent["entered"] + _SLE_DAYS * _DAY_S, f"{_SLE_DAYS} days from entering Waiting"

    def _moving(self, agent: dict[str, Any]) -> bool:
        """Whether the task has open dependencies and each is In Progress or Review: work is under way on its gate."""
        roles = self._feed.roles
        open_ = [dependency for dependency in agent["dependencies"] if not self._cleared(dependency)]
        return bool(open_) and all(
            (self._feed.task(dependency, lean=True) or {}).get("state") in (roles.working, roles.review)
            for dependency in open_
        )

    def _overdue(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The deadline and the Needs attention question when the task is past its service level expectation."""
        deadline = self._deadline(agent)
        now = self._wall()
        if not deadline or deadline[0] > now:
            return None
        if missing := self._missing(agent):
            gone = "; ".join(f"{dependency} is not on the board" for dependency in missing)
            listed = ", ".join(agent["dependencies"])
            return deadline[0], (
                f"{gone}, so nothing releases this task. Its dependencies ({listed}) are cleared with this move. "
                "Re-park it on the right tasks, or close it?"
            )
        if self._evaluate is not None and criteria.authored(agent["description"]) and agent["id"] not in self._results:
            return (
                None  # the gate is not read yet: its result derives the task again, and a gate that holds comes first
            )
        gate = [*self._unmet(agent), *(each["id"] for each in criteria.authored(agent["description"]))]
        days = int((now - agent["entered"]) // _DAY_S)
        return deadline[0], (
            f"Waiting {days} days, past its service level expectation ({deadline[1]}); still gated on "
            f"{', '.join(gate) or 'its wait'}. Release it, re-park it with a new expect_by, or close it?"
        )

    def _criteria(self, agent: dict[str, Any]) -> tuple[tuple[tuple[str, str], ...], list[str]] | None:
        """The task's last evaluated `(id, status)` pairs and the ids not met, when its criteria have a result; a board
        with no evaluator command leaves each `not evaluated`, which is no result."""
        result = self._results.get(agent["id"])
        if not criteria.authored(agent["description"]) or not result or not result[1]:
            return None
        if any(status == criteria.NOT_EVALUATED for _, status in result[1]):
            return None
        return result[1], [criterion for criterion, status in result[1] if status != "met"]

    def _criteria_met(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The results when every Start Criterion was evaluated met and no dependency is open, which would hold it back."""
        if self._unmet(agent):
            return None
        found = self._criteria(agent)
        return (found[0], "Every Start Criterion passes.") if found and not found[1] else None

    def _criteria_unmet(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The results when a Start Criterion was evaluated unmet or could not be evaluated."""
        found = self._criteria(agent)
        return (found[0], f"Start Criteria not met: {', '.join(found[1])}.") if found and found[1] else None

    def _deps_unresolved(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The dependencies that are not done, when there are any."""
        open_ = self._unmet(agent)
        return (open_, f"Not done: {', '.join(open_)}.") if open_ else None

    def _unmet(self, agent: dict[str, Any]) -> tuple[str, ...]:
        """The dependencies that are neither done nor early: still open for what the task waits on."""
        early = self._early(agent)
        return tuple(
            dependency
            for dependency in agent["dependencies"]
            if not self._cleared(dependency) and dependency not in early
        )

    def _early(self, agent: dict[str, Any]) -> tuple[str, ...]:
        """The open dependencies whose every criterion the task's record says it needs (`dependencyNeeds`, `TASK-N#K`)
        is checked: the fact the task waited on holds, whatever the dependency still has open. A dependency with no
        need names the whole task; a record the board cannot read names none."""
        open_ = [dependency for dependency in agent["dependencies"] if not self._cleared(dependency)]
        if not open_ or self._read is None:
            return ()
        try:
            needs = (self._read(agent["id"]) or {}).get("dependencyNeeds") or ()
        except Exception as error:
            logger.warning("task actor: cannot read the dependency needs of %s: %s", agent["id"], error)
            return ()
        wanted: dict[str, list[int]] = {}
        for task, number in map(_need_of, needs):
            wanted.setdefault(task, []).append(number)
        return tuple(
            dependency for dependency in open_ if dependency in wanted and self._checked(dependency, wanted[dependency])
        )

    def _checked(self, dependency: str, numbers: list[int]) -> bool:
        """Whether every criterion `numbers` names (1-based) of `dependency` is checked."""
        ticks = tuple(
            criterion["checked"] for criterion in (self._feed.task(dependency, lean=True) or {}).get("criteria", ())
        )
        return all(0 < number <= len(ticks) and ticks[number - 1] for number in numbers)

    def _stale(self, agent: dict[str, Any]) -> dict[str, list[str]]:
        """The record changes that drop the early dependencies and their needs, none when there are none."""
        early = self._early(agent)
        if not early:
            return {}
        needs = (self._read(agent["id"]) or {}).get("dependencyNeeds") or ()
        return {
            "dependencies": [dependency for dependency in agent["dependencies"] if dependency not in early],
            "dependencyNeeds": [need for need in needs if _need_of(need)[0] not in early],
        }

    _facts: dict[str, Callable[[TaskActor, dict[str, Any]], tuple[Any, str] | None]] = {
        "pr_terminal": _pr_terminal,
        "pr_merged": _pr_merged,
        "pr_closed_unmerged": _pr_closed_unmerged,
        "pr_closed_unmerged_complete": _pr_closed_unmerged_complete,
        "pr_merged_planned": _pr_merged_planned,
        "pr_merged_unfinished": _pr_merged_unfinished,
        "pr_ready": _pr_ready,
        "pr_failing": _pr_failing,
        "pr_draft": _pr_draft,
        "pr_conflicting": _pr_conflicting,
        "pr_unfinished_alive": _pr_unfinished_alive,
        "pr_unfinished_dead": _pr_unfinished_dead,
        "deps_done": _deps_done,
        "deps_done_with_pr": _deps_done_with_pr,
        "deps_unresolved": _deps_unresolved,
        "criteria_met": _criteria_met,
        "criteria_unmet": _criteria_unmet,
        "overdue": _overdue,
        "holder_idle": _holder_idle,
    }
