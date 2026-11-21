"""The task actor: a task advances itself on the facts its lane waits on.

A machine state's `waits` name a fact kind and the event that leaves the state when the fact holds
(`machine_definition.WAIT_FACTS`). The actor keeps a `PR -> tasks` and a `task -> dependents` index, so one change
touches only the tasks naming it, and when a task's pull request state, its own lane or a dependency's changes it
re-derives that task's waits and writes the first that holds through the board's task editor as `starpulse/task-actor`.
The board's rules and the machine's guards judge the write like any other. A write the board refuses is logged and
counted, and not tried again until the task's facts change. A move to Done the board refuses (a Definition of Done item
left open) is commented on the task as `Held from Done: <reason>`; the last item checked tries the move again. A release to Ready the board refuses (a
declared guard, the validate hook or any other refusal) leaves the task in its lane with the refusal as a comment and no
operator question, because no operator move clears a task record alone, and the release is tried again when the task's
description, profile, labels or dependencies change. A start
re-derives every open task once, which is the recovery for a change that happened while the server was down.

A lifecycle machine whose phase state links a skill machine with `exits` (`submachines[].exits`) advances that phase
too: when the skill machine reaches an exit state the actor calls `advance(machine, task, event)` with the exit's event,
once per visit to the phase, and only for the skill machine the task's current phase links. A link that lists `routes`
(phase state to event) sends instead the event for the phase that follows it in the `sequences` entry of the task's
type (`decide` for a kind-decide task, `default` for a type it does not name), when one is listed; the exit's own event serves every other sequence.
The Board's phase is a task's lane, and its links count only when the actor writes every event they exit on (the Verify
machine's `passed` and `missed` close and send back a Verifying task); a skill placement from before the task entered
the lane is the last visit's and advances nothing.

A Waiting task parked on event subjects (the `kind: event` entries of its Start Criteria) is released by the first
event of any of them: the actor keeps a `subject -> tasks` index, `event_seen(subject)` is the follower's call for each
machine event the bridge names, and a task parking on a subject asks `latest(subject)` whether its last event already
happened, so a wait already met releases at once. No evaluator is polled. The board may hold a task's `deps_done`
with reasons, written once as a comment; a task created re-derives every held task.

Nothing derives a lane on a period. A task moves when a fact its lane watches changes: its own record, a dependency's
lane or checked criteria, a pull request, an event it waits on, or its deadline. Each derivation of a task in a lane that
waits on `deps_done` comments once, as `Flagged in Waiting: <reason>`, when a dependency nothing will finish (the board
holds no such task). A dependency Done or Archived is met. The start derivation reads every open
task not unchanged since the actor's checkpoint once as recovery and logs each move it makes as a defect: a move the
events should have made before it. The checkpoint (`CHECKPOINT` worker state) keeps the digest of the facts each task was
last derived on, saved while the actor runs and again on a clean stop; a start derives only the tasks whose digest
differs, and every open task when no checkpoint is readable or the lanes' waits and moves changed since it.
"""

import hashlib
import json
import logging
import queue
import re
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from starpulse.board.adapters.holder_idle import HARNESS_MACHINE, HolderUnreachable
from starpulse.board.model import criteria
from starpulse.board.model.acceptance import open_criteria, resolved
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.markdown import attention_reason, operator_answered, section_set
from starpulse.board.model.rollup import checks_verdict
from starpulse.board.model.seam import (
    COMMENT_CAP,
    FLAGGED,
    HELD,
    MERGE_EVIDENCE,
    TaskEditor,
    TaskReader,
    Written,
)
from starpulse.event_log import events as machine_events
from starpulse.event_log.deadlines import Deadlines
from starpulse.event_log.wake import StopEvent, save_on_change
from starpulse.pulls.adapters.inbound.task_memory import TaskMemory
from starpulse.pulls.adapters.inbound.unblock import PinGate
from starpulse.pulls.adapters.outbound.pull_requests import landed, own_prs, pull_record, uncited
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
#: The machine whose phase is the work an In Progress task is in; a refusal wake is its event.
IN_PROGRESS = "in-progress"
#: What the task actor comments when the board refuses a task's release to Ready, before the refusal.
LINT_REFUSED = "Release to Ready refused, repair the record to release it:"
#: The question that ends the `## Needs attention` reason of a task the actor moves there on a pull request fact.
ATTENTION_QUESTION = "Fix it on the task branch and redeliver, or rescope?"


#: The pull request states that end a pull request.
_TERMINAL = ("MERGED", "CLOSED")
REFUSALS_METRIC = "starpulse_task_actor_refusals_total"
PIN_HELD_METRIC = "starpulse_task_actor_pin_held"
RECOVERY_FINISHED_METRIC = "starpulse_task_actor_recovery_finished"
MERGED_WAITING_METRIC = "starpulse_task_actor_merged_review_waiting"
DERIVE_METRIC = "starpulse_task_actor_derive_seconds"
HOLDER_RESUME = "HOLDER_RESUME"
DONE_HELD = "Held from Done:"
#: Resumes or revives a fault with no progress between gets before the next one moves the task to Needs attention.
_ONE_TRY = 1
#: Nudges an idle holder with an open criterion gets before the next idle moves its task to Needs attention.
_NUDGES = 3
#: Settles in a row whose resume failed before the task moves to Needs attention.
_FAILED_RESUMES = 3
_DEPLOY_FAILED = re.compile(r"^Reopened from Done: Deploy of \S+ to .+? failed", re.M)
#: Seconds between two progress lines of the start recovery.
_PROGRESS_S = 30.0
#: Seconds the exposition waits for the actor lock before it leaves out the series that need it.
_LOCK_WAIT_S = 2.0
#: Seconds the merged Review tasks count is kept, so a scrape loop never makes the scan over the open tasks a load.
_WAITING_TTL_S = 5.0
LATENCY_METRIC = "starpulse_task_actor_latency_seconds"
#: The upper bounds of the latency histogram's buckets, in seconds; the count past the last is the `+Inf` bucket's.
BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
PROJECTION_METRIC = "starpulse_task_actor_projection_seconds"
HANDOFF_METRIC = "starpulse_task_actor_handoff_seconds"
MERGE_MOVE_METRIC = "starpulse_task_merge_move_seconds"
RECEIPT_DONE_METRIC = "starpulse_task_receipt_done_seconds"
#: The facts whose write moves a task because its pull requests ended; the merge-to-move histogram observes them.
_MERGE_FACTS = frozenset({"pr_terminal", "pr_merged", "pr_merged_unfinished"})
#: Most seconds start recovery waits for the saves and changes pending before it takes its next task, so steady traffic
#: slows recovery down but never stops it.
_YIELD_S = 2.0
#: The worker state holding the digest of the facts each task was last derived on, and of the waits and moves it was
#: derived under, so a start derives only the tasks that changed since.
CHECKPOINT = "pulls.task_actor_checkpoint"
#: Bumped when a fact function reads something new or reads it differently: a checkpoint of another revision is unread.
_FACTS_REVISION = 3
#: Seconds between two saves of the checkpoint while the actor runs.
#: Seconds after a task's derived facts change before the checkpoint is saved.
_CHECKPOINT_DEBOUNCE_S = 10.0
_NOTICE_JOIN_S = 10.0
#: The bounds of the projection and handoff histograms: a pin walk takes seconds, and the 10 s bound is the measure.
SLOW_BUCKETS_S = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
#: A Waiting task's service level expectation: seconds from entering Waiting, or past its latest `expect_by`.
_DAY_S = 86_400.0
#: Seconds to wait before each retry of a write that found the board database locked.
LOCK_BACKOFF_S = (0.1, 0.4, 1.6)

#: The facts whose event parks a task in Needs attention: the comment is also its `## Needs attention` reason, a question.
_ASKS = ("overdue", "pr_failing", "operator_pushback")
#: The opening of the comment `backlog-task update --pushback` records.
_PUSHBACK = "Operator pushback:"

#: The skill machine whose lens states are a wait on a verdict, and the machine of an alert whose end is `RESOLVED`.
_SLE_DAYS, _GRACE_DAYS = 7, 2
#: A comment recording the operator's answer: `backlog-task answer`'s line, or the audit comment of a relayed answer.
_ANSWER_COMMENT = re.compile(r"\W*Operator answer\b")


def _ignore(_task: str) -> None:
    return None


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


_LINTED = ("description", "profile", "title", "type", "milestone", "impact", "urgency", "tier", "source")


def _lint_record(agent: Mapping[str, Any]) -> tuple[Any, ...]:
    """The parts of a task's record the board's release refusals read, which a repair changes and a comment does not."""
    return (*(agent.get(field) for field in _LINTED), tuple(agent["labels"]), tuple(agent.get("dependencies", ())))


def _view(agent: Mapping[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[bool, ...]]:
    """The parts of a task's record the actor re-derives on: its lane, dependencies, pull requests and checked criteria.
    A Done task the feed publishes as a dot (`done_dot`) holds neither dependencies nor pull requests."""
    ticks = tuple(criterion["checked"] for criterion in agent.get("criteria", ()))
    return agent["state"], tuple(agent.get("dependencies", ())), tuple(agent.get("prs", ())), ticks


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


def _by_claim(
    fact: Callable[[TaskActor, dict[str, Any]], Any], *, claimed: bool
) -> Callable[[TaskActor, dict[str, Any]], Any]:
    """`fact` for the tasks a session claimed or for the rest, so a claimed task never falls through to Ready."""
    return lambda actor, agent: fact(actor, agent) if bool(agent["assignee"]) == claimed else None


class TaskActor:
    """Moves each open task whose lane waits on a fact that holds, once per change of that fact.

    `waits` is `{lane: {fact kind: event}}` (`Compiled.waits`) and `moves` is `{(lane, event): target lane}`, from the
    Board machine's transitions. `edit` is the board's task editor. `repos`, `pin_rule` and `pins` are the `[release]`
    pin-bump rule (`unblock.PinGate`): a dependency in a pinned repository is merged on the parent's pin bump.
    `latest` says whether an event subject's last event already happened (None: none has), and `holds` the reasons the board withholds a task's `deps_done` (`Board.holds`). `read` is the
    board's task reader (`Board.read`).
    `unfinished` is the work a task whose pull requests merged still has (`Board.unfinished`). `main_green` is the SHA of main's latest passed Validate (None: none passed, or no source),
    and `owner_source` the `source` prefix of the tasks that pass closes while nothing waits on them (empty: none).
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
        latest: Callable[[str], bool] | None = None,
        holds: Callable[[str], Sequence[str]] = lambda _task: (),
        parked: Callable[[str], None] = _ignore,
        released: Callable[[str], None] = _ignore,
        closed: Callable[[str], None] = _ignore,
        returned: Callable[[str], None] = _ignore,
        alive: Callable[[str], bool] = lambda _task: False,
        enqueued: Callable[[str], None] = _ignore,
        live: LiveBuild | None = None,
        advance: Callable[[str, str, str], None] | None = None,
        read: TaskReader = lambda _task: None,
        idle: Callable[[str, str], None] | None = None,
        sequences: Mapping[str, Sequence[str]] = MappingProxyType({}),
        awaits: Sequence[str] = (),
        unfinished: Callable[[str], Sequence[str]] = lambda _task: (),
        log: EventLog | None = None,
        main_green: Callable[[], str | None] | None = None,
        owner_source: str = "",
    ) -> None:
        self._main_green = main_green
        self._owner_source = owner_source
        self._read = read
        self._idle = idle
        self._memory = TaskMemory(read, lambda name, memory: self._edit_retrying(name, {"actorMemory": memory}, ""))
        self._advance = advance
        #: The phases a task of each type goes through, in order (`[sequences]`); `default` serves an unnamed type.
        self._sequences = sequences
        #: The machines whose unfinished placement of a task holds its settled session (`awaits`).
        self._awaiting = tuple(awaits)
        self._unfinished = unfinished
        #: Each non-Board machine's links that exit on a skill machine's state, when there is somewhere to send the exit.
        self._links = _exit_links(feed.machines) if advance else {}
        self._feed = feed
        self._store = store
        self._edit = edit
        self._waits = waits
        #: The lane that waits on a pull request's end, whatever the board names it.
        self._review = feed.roles.review
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
        self._latest = latest
        self._holds = holds
        self._tell = parked
        self._released = released
        self._closed = closed
        self._returned = returned
        self._alive = alive
        self._enqueued = enqueued
        #: The lanes that wait on their tasks' dependencies, whose derivation flags a wait nothing ends.
        self._sweep_lanes = {lane for lane, facts in waits.items() if "deps_done" in facts}
        #: The lanes that wait on a task's Start Criteria.
        self._gated_lanes = {lane for lane, facts in waits.items() if "criteria_met" in facts}
        #: The event subjects each gated task waits on, and for each subject the tasks waiting on it.
        self._gates: dict[str, tuple[str, ...]] = {}
        self._until: dict[str, set[str]] = {}
        #: The subjects of each gated task's gate that an event, or a last event at its park, has announced.
        self._heard: dict[str, set[str]] = {}
        #: Whether the start derivation is running, which only recovers moves the events missed.
        self._recovering = False
        #: Tasks whose `deps_done` the board holds; a task created re-derives them.
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
        self._log = log
        #: Digest of the waits, moves and sequences the checkpoint is valid under.
        self._rules = _rules_digest(waits, moves, sequences)
        #: The digest of the facts each task was last derived on, read back from the checkpoint; a task whose facts
        #: still digest to it needs no derivation at start.
        self._derived: dict[str, str] = self._restored_checkpoint()
        self._kept: dict[str, str] = dict(self._derived)
        #: Set when `_derived` changes, so the checkpoint saver writes it after a debounce.
        self._derived_moved = threading.Event()
        #: Whether the derivation running now called a board hook, or could not settle (a transient write failure, a
        #: hold it could not read), which keeps its digest out of the checkpoint.
        self._hooked = False
        self._unsettled = False
        self._probing = False
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
        #: The record each task's release was last refused on by the board, so a repaired record is tried again.
        self._lint_held: dict[str, tuple[Any, ...]] = {}
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
        self._receipt_done = _Histogram(BUCKETS_S)
        #: The wall time the merge webhook `merge_received` derives was received at; None outside it.
        self._received: float | None = None
        #: How many store saves, task or move changes and projections wait for the lock or hold it; start recovery takes
        #: its next task only when none does. `_events` is notified each time one ends.
        self._pending = 0
        self._events = threading.Condition(threading.Lock())
        #: Set by a store save; `_saved_at` is the clock when the oldest unread save happened.
        self._saved = threading.Event()
        self._saved_at = 0.0
        #: Set after each turn of the actor loop, for the writer of its metrics and views.
        self.turned = threading.Event()
        #: The merged Review tasks, and the monotonic clock it was counted at.
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
        actor is alive: whether start recovery finished and the merged Review tasks not yet Done."""
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
                *self._receipt_done.lines(
                    RECEIPT_DONE_METRIC, "Seconds from receiving a merge webhook to the write that moved its task."
                ),
                f"# HELP {DERIVE_METRIC} Seconds each derivation of a task's waits ran, by lane and whether a board hook ran.",
                f"# TYPE {DERIVE_METRIC} histogram",
                *derives,
                f"# HELP {RECOVERY_FINISHED_METRIC} 1 once the start recovery derived every open task, else 0.",
                f"# TYPE {RECOVERY_FINISHED_METRIC} gauge",
                f"{RECOVERY_FINISHED_METRIC} {int(self.ready.is_set())}",
                *self._held_lines(held),
                "",
            ]
        )

    def _held_counts(self) -> tuple[int, int] | None:
        """The series that read the actor's state under its lock (the tasks held for a pin) and the merged Review tasks,
        read after it is released. None when another thread holds the lock past `_LOCK_WAIT_S`: a scrape must answer
        then, since a held lock is what the recovery gauge reports."""
        if not self._lock.acquire(timeout=_LOCK_WAIT_S):
            return None
        try:
            pin_held = len(self._pin_held)
        finally:
            self._lock.release()
        return pin_held, self._merged_waiting()  # the feed reads hold no lock

    def _merged_waiting(self) -> int:
        counted_at, waiting = self._waiting
        if time.monotonic() - counted_at >= _WAITING_TTL_S:
            waiting = sum(self._merged_review(agent) for agent in self._feed.open_tasks())
            self._waiting = (time.monotonic(), waiting)
        return waiting

    def _merged_untried(self, agent: dict[str, Any]) -> bool:
        """Whether a Review task has a merged proof pull request and the actor has tried no move for it."""
        return agent["id"] not in self._tried and self._merged_review(agent)

    def _merged_review(self, agent: dict[str, Any]) -> bool:
        """Whether a Review task has a merged proof pull request, whatever move was tried or refused."""
        if agent["state"] != self._review:
            return False
        records = [self._record(url) for url in self._proof_prs(agent)]
        return any(record and record["state"] == "MERGED" for record in records)

    @staticmethod
    def _held_lines(held: tuple[int, int] | None) -> list[str]:
        if held is None:
            return []
        pin_held, waiting = held
        return [
            f"# HELP {PIN_HELD_METRIC} Waiting tasks whose dependencies are done but wait for a pin bump to merge.",
            f"# TYPE {PIN_HELD_METRIC} gauge",
            f"{PIN_HELD_METRIC} {pin_held}",
            f"# HELP {MERGED_WAITING_METRIC} Review tasks with a merged pull request that have not reached Done, including one whose move was refused.",
            f"# TYPE {MERGED_WAITING_METRIC} gauge",
            f"{MERGED_WAITING_METRIC} {waiting}",
        ]

    def start(self, stop: StopEvent) -> threading.Thread:
        """Follow the feed on a daemon thread until `stop` is set."""
        thread = threading.Thread(target=self._run, args=(stop,), name="task-actor", daemon=True)
        thread.start()
        if self._sweep_lanes:
            self._feed.reconcilers["waiting"] = self.reconcile_waiting
        threading.Thread(target=self._follow_store, args=(stop,), name="task-actor-store", daemon=True).start()
        if self._log is not None:
            threading.Thread(
                target=self._keep_checkpoint, args=(stop,), name="task-actor-checkpoint", daemon=True
            ).start()
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

    def _stuck(self, agent: dict[str, Any]) -> tuple[str, ...]:
        """The dependencies that will not finish on their own: the Board holds no such task."""
        missing = self._missing(agent)
        return tuple(
            f"{dependency} is not on the board" for dependency in agent["dependencies"] if dependency in missing
        )

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
            unrepaired = {agent["id"] for agent in tasks if self._lint_held.get(agent["id"]) == _lint_record(agent)}
            missed = sorted(releasable & self._releasable - unrepaired)  # a refused release waits for its repair
            self._releasable = releasable
            for name in missed:
                self._tried.pop(name, None)
            self._derive_all(missed, self._clock())
            ready = self._feed.roles.ready
            released = [name for name in missed if (moved := self._feed.task(name, lean=True)) and moved["state"] == ready]
        return len(tasks), len(released)

    def _run(self, stop: StopEvent) -> None:
        self._feed.wait_replayed()
        changes = self._feed.follow_changes()
        with self._lock:
            observed = self._clock()
            tasks = self._feed.open_tasks()
            for agent in tasks:
                self._index(agent)
            self._read_pulls()
            if self._idle is not None:  # a settle while down is replayed by `follow_holder_idle`; `confirm` spares a busy holder
                for agent in tasks:
                    if agent["state"] == self._feed.roles.working and self._awaits(agent):
                        self._memory.keep(agent["id"], awaited=True)
            open_ids = {agent["id"] for agent in tasks}
            self._derived = {name: digest for name, digest in self._derived.items() if name in open_ids}
            self._derived_moved.set()
        self.indexed.set()
        recovery = threading.Thread(
            target=self._recovered, args=(tasks, observed, stop), name="task-actor-recovery", daemon=True
        )
        recovery.start()  # a task or move change, a phase exit above all, is handled while recovery derives the rest

        def stopped() -> None:
            changes.put(("stop", {}))  # a stop wakes the wait below, which then sees it

        stop.listen(stopped)
        try:
            while not stop.is_set():
                self.turned.set()
                kind, data = changes.get()
                if kind in ("task", "move"):
                    handle = self._changed if kind == "task" else self._moved
                    try:
                        with self._pressing():
                            handle(data)
                    except Exception:  # one change must not end the actor
                        logger.exception("task actor: cannot handle the change of %s", data.get("id"))
        finally:
            stop.unlisten(stopped)
            recovery.join(timeout=_NOTICE_JOIN_S)  # a move recovery makes after the notices close would miss its hook
            self._end_notices()

    def _recovered(self, tasks: Sequence[dict[str, Any]], observed: float, stop: StopEvent) -> None:
        self._recover(tasks, observed, stop)
        self.ready.set()

    def _recover(self, tasks: Sequence[dict[str, Any]], observed: float, stop: StopEvent | None = None) -> None:
        """Move each Review task whose pull request merged, then send each phase's missed exit, then derive every other
        open task whose facts differ from the checkpoint's (all of them when none is readable). A merge or a verdict that
        landed while the actor was down is the move an operator waits on, so neither waits for the derive of the whole
        board, which takes minutes. Each task is handled under its own hold of the lock, so a store save or a task
        change is handled between two tasks instead of waiting for the pass to end."""
        started = self._clock()
        report = self._reporter(started)
        names = sorted(agent["id"] for agent in tasks)
        with self._lock:
            merged = [
                agent["id"] for agent in sorted(tasks, key=lambda agent: agent["id"]) if self._merged_untried(agent)
            ]

        def derive(batch: Sequence[str], offset: int) -> int:
            moved = 0
            for done, name in enumerate(batch, offset + 1):
                if stop is not None and stop.is_set():
                    break  # a stopped actor closes its notices: a move made after would miss its hook
                self._yield()
                with self._lock:  # the flag holds only under the lock, so no other thread's move reads it
                    if stop is not None and stop.is_set():
                        break  # the stop came while this pass waited for the lock
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
        self._exit_all(tasks, lambda done, total: report("exited the phases of", done, total), stop)
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
            now = self._clock()
            if now - last >= _PROGRESS_S:
                last = now
                logger.info("task actor: start recovery %s %d of %d after %.0fs", stage, done, total, now - started)

        return report

    def _exit_all(
        self,
        tasks: Sequence[Mapping[str, Any]],
        report: Callable[[int, int], None] = lambda done, total: None,
        stop: StopEvent | None = None,
    ) -> None:
        """Send the exit event each of `tasks`, and each open task a phase machine places, is due, taking the lock once
        per task and stopping at the first task a stopped actor reaches. A phase machine keeps every placement it made (tens of thousands, nearly all of closed tasks), and
        `_exit_phase` reads every parent for the task it takes, so each open task is swept once and a closed task's
        placement not at all."""
        open_ids = {agent["id"] for agent in self._feed.open_tasks()}
        names = {agent["id"] for agent in tasks} if BOARD in self._links else set()
        for parent in self._links.keys() - {BOARD}:
            names.update(
                name for name in self._feed.machine_task_ids(parent) if self._feed.current_id(name) in open_ids
            )
        swept = sorted(names)
        for done, name in enumerate(swept, 1):
            if stop is not None and stop.is_set():
                break  # a stopped actor closes its notices: an exit made after would miss its hook
            self._yield()
            with self._lock:
                if stop is not None and stop.is_set():
                    break
                self._exit_phase(name)
            report(done, len(swept))

    def _watch(self, name: str, agent: dict[str, Any]) -> bool:
        """Index the event subjects `agent` waits on in a gated lane; True when they differ from the last call's. A
        subject whose last event is already recorded counts as heard, so a wait met before the park releases at once."""
        gate = criteria.subjects(agent["description"]) if agent["state"] in self._gated_lanes else ()
        if gate == self._gates.get(name, ()):
            return False
        heard = {subject for subject in gate if self._latest is not None and self._latest(subject)}
        self._unwatch(name)
        self._gates[name] = gate
        for subject in gate:
            self._until.setdefault(subject, set()).add(name)
        if heard:
            self._heard[name] = heard
        return True

    def _unwatch(self, name: str) -> None:
        for subject in self._gates.pop(name, ()):
            self._until[subject].discard(name)
            if not self._until[subject]:
                del self._until[subject]
        self._heard.pop(name, None)

    def event_seen(self, subject: str) -> None:
        """Derive the Waiting tasks parked on `subject` again: the first event on a subject they wait on releases them."""
        with self._lock:
            names = sorted(self._until.get(subject, ()))
            for name in names:
                self._heard.setdefault(name, set()).add(subject)
            self._derive_all(names, self._clock())

    def _index(self, agent: dict[str, Any]) -> None:
        """Take `agent`'s lane, dependencies, pull requests and checked criteria into the indexes."""
        name = agent["id"]
        for url in self._seen.get(name, ("", (), (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._seen[name] = _view(agent)
        if self._memory.of(name).get("lane_entered", [""])[0] != agent["state"]:
            self._memory.keep(name, lane_entered=[agent["state"], agent.get("entered") or 0.0])
        self._watch(name, agent)
        for url in agent.get("prs", ()):
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
            regated = self._watch(name, agent)
            repaired = name in self._lint_held and self._lint_held[name] != _lint_record(agent)
            if repaired:
                del self._lint_held[name]
                self._tried.pop(name, None)
            rearmed = agent["state"] in self._timed_lanes and tuple(
                criteria.expect_dates(agent["description"])
            ) != self._dates.get(name, ())
            pushable = "operator_pushback" in self._waits.get(agent["state"], {})  # a comment leaves the view as it was
            if before == (now := _view(agent)) and not (repaired or rearmed or regated or pushable):
                return
            self._index(agent)
            if now[0] == self._feed.roles.working:  # a refused move is tried again on the changed record
                self._tried.pop(name, None)
            touched = {name}
            if before is None:  # a task created: a hold may have waited on it
                touched |= self._held
            if before is None or before[0] != now[0]:
                self._tried.pop(name, None)
                working = self._feed.roles.working
                kept: dict[str, Any] = {} if now[0] == working else {"busy": None, "resumes": None}
                if before and before[0] == self._review and now[0] == working:
                    own = self._memory.has(name, "own_send_back")
                    kept |= {"sent_back": None if own else self._heads(agent), "own_send_back": None}
                elif before is not None or now[0] != working:
                    kept["sent_back"] = None  # a task first seen outside the working lane keeps no hold from an earlier run
                self._memory.keep(name, **kept)
            if before is None or (before[0], before[3]) != (now[0], now[3]):
                touched |= self._dependents(name)
            self._derive_all(touched, observed)

    def _moved(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._exit_phase(data["id"])
            self._settle_awaited(data["id"])
            self._settle_busy(data)
            agent = self._feed.task(data["id"], lean=True)
            if agent and "phase_resumed" in self._waits.get(agent["state"], {}):
                self._derive(data["id"], self._clock())

    def _exit_phase(self, task: str) -> None:
        """Send the exit event of the phase `task` is in when that phase's skill machine sits in the state its link exits
        on. A skill machine the current phase does not link never counts, so a late final event of an earlier phase's
        skill advances nothing."""
        exited = self._memory.of(task).get("exited") or {}
        for parent, links in self._links.items():
            phase = self._phase(parent, task)
            event = self._exit_event(links, phase, task) if phase else None
            if phase and event and exited.get(parent) != (sent := [phase["state"], phase["steps"], event]):
                exited[parent] = sent
                self._memory.keep(task, exited=exited)
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
        entered = self._entered(agent) if agent else 0.0
        return {"state": agent["state"], "steps": entered, "since": entered} if agent else None

    def _entered(self, agent: dict[str, Any]) -> float:
        """When `agent` entered the Board lane it holds, as read at the move: the feed's `entered` is its newest event of
        any kind, which a comment after a verdict moves past the verdict's time."""
        lane, at = self._memory.of(agent["id"]).get("lane_entered") or ("", 0.0)
        return at if lane == agent["state"] else agent.get("entered") or 0.0

    def _exit_event(self, links: Sequence[Mapping[str, Any]], phase: Mapping[str, Any], task: str) -> str | None:
        for link in links:
            placed = self._feed.machine_task(link["machine"], task) if link["state"] == phase["state"] else None
            if placed and placed["active"] >= phase.get("since", 0.0) and link["exits"].get(placed["state"]):
                return self._route(link, task) or link["exits"][placed["state"]]
        return None

    def _route(self, link: Mapping[str, Any], task: str) -> str | None:
        """The event of the link's route to the phase after it in the sequence of `task` (its `decide` row when kind-decide, else its type), when the link draws one."""
        agent = self._feed.task(task, lean=True) or {}
        # the same lookup as `temporal_runner.sequences.phases`, which this package cannot import
        decide = self._sequences.get("decide") if "kind-decide" in agent.get("labels", ()) else None
        sequence = decide or self._sequences.get(agent.get("type", "").lower()) or self._sequences.get("default", ())
        following = sequence[sequence.index(link["state"]) + 1 :][:1] if link["state"] in sequence else ()
        return link.get("routes", {}).get(following[0]) if following else None

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
            self._derived_moved.set()
        else:
            self._kept = facts

    def _keep_checkpoint(self, stop: StopEvent) -> None:
        """Save the checkpoint `_CHECKPOINT_DEBOUNCE_S` after its facts change, and once more on a stop."""
        save_on_change(stop, self._derived_moved, self.checkpoint, _CHECKPOINT_DEBOUNCE_S)

    def _unchanged(self, name: str) -> bool:
        """Whether the task's facts digest to what it was last derived on; when they do, arm its deadline, the one thing
        a derivation leaves in memory that nothing else rebuilds at start."""
        agent = self._feed.task(name, lean=True)
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
            other = self._feed.task(dependency, lean=True)
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
            sorted(self._heard.get(name, ())),
        )
        return hashlib.sha1(repr(facts).encode(), usedforsecurity=False).hexdigest()[:16]

    def _forget(self, name: str) -> None:
        self._derived.pop(name, None)
        self._derived_moved.set()
        for url in self._seen.pop(name, ("", (), (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._tried.pop(name, None)
        self._lint_held.pop(name, None)
        self._deadlines.cancel(name)
        self._dates.pop(name, None)
        self._unwatch(name)

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

    def merge_received(self, received_at: float) -> None:
        """Re-derive the tasks whose pull requests changed, on the caller's thread: the merge webhook received at
        `received_at` (wall time) moves its task without waiting on the save follower, a projection or older deliveries.
        Each merge's move it lands is timed from `received_at`. A failure is logged, never raised to the consumer."""
        observed = self._clock()
        try:
            with self._pressing(), self._lock:
                self._received = received_at
                try:
                    self._derive_pulled(self._read_pulls(), observed)
                finally:
                    self._received = None
        except Exception:
            logger.exception("task actor: cannot derive the tasks of a merge webhook")

    def _read_pulls(self) -> set[str]:
        """The tasks citing a pull request whose state changed since it was last read."""
        touched: set[str] = set()
        for url, names in self._by_pr.items():
            if self._pull_states.get(url) != (state := self._pull_state(url)):
                self._pull_states[url] = state
                touched |= names
                for name in names:
                    if self._seen[name][0] == self._feed.roles.working:  # a refused move is tried on the new state
                        self._tried.pop(name, None)
        return touched

    def _record(self, url: str) -> dict[str, Any] | None:
        return pull_record(self._store, url)

    def _own_prs(self, agent: dict[str, Any]) -> list[str]:
        return own_prs(self._store, agent)

    def _proof_prs(self, agent: dict[str, Any]) -> list[str]:
        """The pull requests whose ends prove a task's work. In Review, a task with no own pull request merged or open
        takes every cited one: another task's delivery may have superseded its own, which closed unmerged or never
        existed. An own pull request still open keeps a merged reference from standing for the task's delivery."""
        own = self._own_prs(agent)
        if agent["state"] != self._review:
            return own
        if any((record := self._record(url)) and record["state"] != "CLOSED" for url in own):
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
            checks_verdict(
                record["state"], record["checks"], record["headRefOid"], record["rollup"], record["requiredChecks"]
            ),
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
        if agent is None or (name in self._seen and self._seen[name][0] != agent["state"]):
            return  # a lane change not yet handled: its change event derives, after it sets any send-back hold
        digest = self._digest(agent)
        self._hooked = self._unsettled = False
        started = self._clock()
        try:
            self._derive_waits(name, agent, observed)
        finally:
            self._timed_derive(agent["state"], self._hooked, self._clock() - started)
        self._settle_awaited(name)
        if self._unsettled or name in self._held or name in self._pin_held:
            self._derived.pop(name, None)  # its hold or failure can end with no fact of the task changing
        else:
            self._derived[name] = digest
        self._derived_moved.set()

    def view(self, name: str) -> dict[str, Any] | None:
        """The actor's view of one task: the lane the feed and the actor each hold, the pull requests it saw, the move it
        last tried, and the evidence of each fact its lane waits on (None when the fact does not hold). Writes nothing.
        The feed is read before the actor lock is taken, so a contended feed never holds a move."""
        agent = self._feed.task(name, lean=True)
        if agent is None:
            return None
        with self._lock:
            seen = self._seen.get(name)
            tried = self._tried.get(name)
            self._probing = True
            try:
                facts = {
                    fact: (held[0] if (held := self._facts.get(fact, lambda *_: None)(self, agent)) else None)
                    for fact in self._waits.get(agent["state"], {})
                }
            finally:
                self._probing = False
            return {
                "task": name,
                "feed_lane": agent["state"],
                "seen_lane": seen[0] if seen else None,
                "seen_prs": list(seen[2]) if seen else [],
                "tried": dict(zip(("lane", "event", "evidence"), tried, strict=False)) if tried else None,
                "facts": facts,
            }

    def views(self) -> dict[str, Any]:
        """The `view` of each open task in Review, by name: the lane whose merged task waits on the operator unseen."""
        names = [agent["id"] for agent in self._feed.open_tasks() if agent["state"] == self._review]
        return {name: found for name in names if (found := self.view(name))}

    def _timed_derive(self, lane: str, hooked: bool, seconds: float) -> None:
        with self._metrics:
            histogram = self._derive_seconds.setdefault((lane, hooked), _Histogram(SLOW_BUCKETS_S))
        histogram.observe(seconds)

    def _derive_waits(self, name: str, agent: dict[str, Any], observed: float) -> None:
        """Write the first move the task's lane waits on whose fact holds. A move already tried on these facts, or one the
        board refuses, leaves the next fact its turn: a Waiting task whose return to Review is refused still reaches Ready."""
        self.derivations[name] += 1
        self._arm(name, agent)
        if agent["state"] in self._sweep_lanes and (reasons := self._stuck(agent)):
            self._note_hold(agent, reasons, FLAGGED)
        for fact, event in self._waits.get(agent["state"], {}).items():
            target = self._moves.get((agent["state"], event))
            held = self._facts.get(fact, lambda *_: None)(self, agent) if target else None
            if held is None:
                continue
            evidence, comment = held
            if fact in _ASKS and self._answered(agent, comment):
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
                self._notice(
                    self._enqueued,
                    name,
                    "was ready but its pull request was not enqueued",
                    on_failure=lambda: self._tried.pop(name, None),  # tried again on the next derivation
                )
                return
            merged = self._merged_at(agent) if fact in _MERGE_FACTS else None
            if self._write(name, target, comment, observed, source=agent["state"], stale=changes, merged=merged):
                return

    def _merged_at(self, agent: dict[str, Any]) -> float | None:
        """When the latest of the pull requests that proved `agent`'s work merged."""
        merges = (
            _epoch(record["mergedAt"])
            for url in self._proof_prs(agent)
            if (record := self._record(url)) and record["state"] == "MERGED" and record["mergedAt"]
        )
        return max((at for at in merges if at is not None), default=None)

    def working(self) -> list[str]:
        """The open tasks in the working lane, whose holders `follow_holder_idle` checks for a settle while down."""
        with self._lock:
            return [agent["id"] for agent in self._feed.open_tasks() if agent["state"] == self._feed.roles.working]

    def holder_settled(self, name: str, wait_ended: bool = False) -> None:
        """A session settled. A holder whose task has an open criterion (neither checked nor struck through) is nudged by
        `_nudge`, pull request or not. Any other In Progress task, a no-pull-request one included, whose holder is not busy (`confirm`) and that no event is awaited on
        has work left, so the `idle` hook resumes the same session with its phase machine's next step; the task stays In
        Progress and no clock runs. A settle an awaited event held runs again from the derivation that finds the wait
        ended, as the session that settled may never settle again, unless its holder is at work by then (a lens's end woke it): that
        holder settles anew. The one resume is the only one: a settle after it with no progress (a phase or
        submachine event, a new head) moves the task to Needs attention with its session kept and its profile unchanged,
        except a settle that an ended wait on checks or an awaited machine queued, which resets the count. A task whose own pull requests have all ended is never resumed. A task citing none of its own while an open pull request names it (`uncited`) is left as it is, neither resumed nor sent to Needs attention: the merge reconcile cites the pull request. A `confirm` that
        raises (the holder is busy) holds the task: the next move of a machine other than the harness settles it again, and the
        session's own activity ends the hold. A `resume` that fails is sent again at once until `_FAILED_RESUMES` fail, when the
        task moves to Needs attention, as a holder whose resume was lost settles no more; a holder no session can reach is
        revived as `holder_ended` revives one, and parks when no session can be reopened."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            self._memory.keep(name, awaited=None, revive_held=None, busy=None)
            if agent is None or agent["state"] != self._feed.roles.working:
                self._memory.keep(name, resumes=None)
                return
            if self._idle is None:
                return
            if wait_ended and self._session_active(name):
                self._memory.keep(name, resumes=None)
                return
            if self._awaits(agent):
                self._memory.keep(name, awaited=True)
                return
            answered = "kind-decide" in agent["labels"] and operator_answered(
                (self._feed.task(name) or {}).get("description", "")
            )
            own = self._own_prs(agent)
            if not own and uncited(self._store, agent):
                return  # the delivery is open and the merge reconcile cites it: no input of the operator's is missing
            if own and all((record := self._record(url)) and record["state"] in _TERMINAL for url in own):
                return
            items = agent.get("criteria", ())
            if opened := open_criteria(items):
                ticks = tuple(resolved(item) for item in items)
            else:
                progress = self._progress(agent)
                same, count = self._memory.resumes(name, progress)
                if not same or wait_ended:  # an awaited CI result is the wake, not a settle with no progress
                    count = 0
                    # kept even when `confirm` finds the holder busy
                    self._memory.keep(name, resumes=self._memory.tally(progress, 0))
        if answered:
            return
        if opened:
            self._nudge(name, opened, ticks, wait_ended)
        else:
            self._resume(name, progress, count)

    def holder_entered(self, name: str) -> None:
        """A task moved from a parked lane to In Progress settles like an idle holder, except after the operator's answer:
        its claim told the holder through the task topic, and a resume on top costs the answering session a turn."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            texts = self._comments(agent) if agent else None
        if texts and _ANSWER_COMMENT.match(texts[-1]):
            return
        self.holder_settled(name)

    def holder_ended(self, name: str, wait_ended: bool = False) -> None:
        """A session's process ended. A holder whose task still has work (an open criterion, or a pull request of its own
        not yet ended) is revived once by the `idle` hook's `revive` verdict, which reopens the session in place and moves the
        claim to it; the task stays In Progress. The next loss with no progress (a criterion checked, a phase or head
        change) moves the task to Needs attention with its session kept, as does a revive that fails, naming why. An awaited event holds the revival until it ends. A
        task with no work left is the settle's (`holder_settled`), and a held revival whose holder is at work again by the time the
        wait ends is dropped."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            self._memory.keep(name, revive_held=None)
            if agent is None or agent["state"] != self._feed.roles.working or self._idle is None:
                return
            if wait_ended and self._session_active(name):
                return
            items = agent.get("criteria", ())
            opened = open_criteria(items)
            if not agent["prs"] and not opened:
                return
            own = self._own_prs(agent)
            if (
                agent["prs"]
                and own
                and all((record := self._record(url)) and record["state"] in _TERMINAL for url in own)
            ):
                return
            if self._awaits(agent):
                self._memory.keep(name, awaited=True, revive_held=True)
                return
            key = (tuple(resolved(item) for item in items), self._progress(agent)) if opened else self._progress(agent)
            _, count = self._memory.resumes(name, key)
            if count >= _ONE_TRY:
                self._memory.keep(name, resumes=None)
                self._attend(
                    name,
                    "its session ended again after its one revive with no progress",
                    "keeps ending",
                    "Which?",
                )
                return
        try:
            self._idle(name, "revive")
        except Exception as error:
            logger.warning("task actor: %s's session ended and could not be revived: %s", name, error)
            with self._lock:
                now = self._feed.task(name, lean=True)
                if now and now["state"] == self._feed.roles.working:
                    self._attend(
                        name,
                        f"no session can start for it: {error}",
                        "could not be revived",
                        "Start one by hand or rescope?",
                        ("start a session on it by hand", "rescope the task"),
                    )
            return
        with self._lock:
            self._memory.count(name, key, count + 1)

    def _resume(self, name: str, progress: tuple[Any, ...], count: int) -> None:
        if not self._confirmed(name):
            return
        if count >= _ONE_TRY:
            with self._lock:
                now = self._feed.task(name, lean=True)
                if now and now["state"] == self._feed.roles.working:
                    self._memory.keep(name, resumes=None)
                    self._attend(name, "it settled idle again after its one resume with no progress")
            return
        if not self._resume_sent(name):
            return
        with self._lock:
            self._memory.keep(name, resumes=self._memory.tally(progress, _ONE_TRY))

    def _session_active(self, name: str) -> bool:
        placed = self._feed.machine_task(HARNESS_MACHINE, name)
        return bool(placed) and placed["state"] == "active"

    def _confirmed(self, name: str) -> bool:
        try:
            self._idle(name, "confirm")
        except Exception as error:
            logger.info("task actor: %s settled but its holder was not confirm: %s", name, error)
            with self._lock:
                self._memory.keep(name, busy=True)
            return False
        return True

    def _switch_raised(self, name: str) -> None:
        """At an idle holder's resume, a profile changed since its last one is typed into the holder by the `idle` hook's
        `switch`, which records the outcome on the task. The first resume only notes the profile, as a session runs on
        the one it started on; the note outlives a park, so a profile raised while the task waits on the operator
        reaches the holder once it is back."""
        profile = (self._feed.task(name, lean=True) or {}).get("profile")
        with self._lock:
            before = (self._memory.of(name).get("profile") or [profile])[0]
            if before == profile:
                self._memory.keep(name, profile=[profile])  # a list, which holds a task with no profile too
                return
        try:
            self._idle(name, "switch")
        except Exception as error:
            logger.info("task actor: %s profile switch to %s failed: %s", name, profile, error)
            return  # the note keeps the profile it was last switched to, so the next resume tries again
        with self._lock:
            self._memory.keep(name, profile=[profile])

    def _resume_sent(self, name: str) -> bool:
        """Send the holder's resume. One that fails is sent again at once, no clock, until `_resume_failed` parks the
        task: a holder whose resume was lost settles no more, so no later settle comes to send it."""
        self._switch_raised(name)
        failed = 0
        while True:
            try:
                self._idle(name, "resume")
                return True
            except Exception as error:
                logger.info("task actor: %s settled but its holder was not resume: %s", name, error)
                failed += 1
                if not self._resume_failed(name, error, failed):
                    return False

    def _nudge(self, name: str, opened: list[tuple[int, str]], ticks: tuple[bool, ...], wait_ended: bool) -> None:
        """Resume an idle holder whose criteria are open; its hook's message names them. The `_NUDGES + 1`th idle with no
        criterion checked or struck through in between moves the task to Needs attention with them as the question. A holder
        still busy (`confirm` raises) settles again and costs no nudge, and the wake of an ended wait restarts the count."""
        if not self._confirmed(name):
            return
        with self._lock:
            _, count = self._memory.resumes(name, ticks)
            if wait_ended:  # an awaited CI result is the wake, not a settle with no progress
                count = 0
            if count >= _NUDGES:
                self._memory.keep(name, resumes=None)
                listing = "; ".join(f"#{number} {text}" for number, text in opened)
                self._attend(
                    name,
                    f"it settled idle after {_NUDGES} nudges with no criterion checked or struck through",
                    "has open criteria",
                    ask=f"Open: {listing}. Which will you resolve, strike through or rescope?",
                )
                return
        if not self._resume_sent(name):
            return
        with self._lock:
            self._memory.count(name, ticks, count + 1)

    def _resume_failed(self, name: str, error: Exception, failed: int) -> bool:
        """Whether the resume is sent again: a holder no session can reach is revived as `holder_ended` revives one, which
        parks the task only when no session can start; any other failure does on the `_FAILED_RESUMES`th in a row; a task
        no longer In Progress needs none."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            if agent is None or agent["state"] != self._feed.roles.working:
                return False
            if not isinstance(error, HolderUnreachable):
                if failed < _FAILED_RESUMES:
                    return True
                self._attend(
                    name, f"its holder's resume failed {failed} times in a row: {error}", "could not be resumed"
                )
                return False
        self.holder_ended(name)
        return False

    def _attend(
        self,
        name: str,
        why: str,
        what: str = "was resumed with no progress",
        ask: str = "Which?",
        options: Sequence[str] = ("resume it by hand", "rescope the task"),
    ) -> None:
        agent = self._feed.task(name, lean=True)
        attention = self._feed.roles.attention
        if agent is None or attention is None:
            return
        reason = attention_reason(
            f"{name} {what}",
            why,
            options,
            ask,
        )
        self._apply(
            name,
            {"status": attention, "description": section_set(agent["description"], "Needs attention", reason)},
            reason,
        )

    def _settle_busy(self, data: dict[str, Any]) -> None:
        name = data["id"]
        if not self._memory.has(name, "busy"):
            return
        if data.get("machine") != HARNESS_MACHINE:
            self._memory.keep(name, busy=None)
            self._queue(lambda: self.holder_settled(name))
        elif (data.get("agent") or {}).get("state") == "active":  # the session works again, so a settle will follow
            self._memory.keep(name, busy=None)

    def _settle_awaited(self, name: str) -> None:
        memory = self._memory.of(name)
        if "awaited" not in memory:
            return
        agent = self._feed.task(name, lean=True)
        if agent is None:
            self._memory.keep(name, awaited=None)
        elif not self._awaits(agent):
            self._memory.keep(name, awaited=None)
            if "revive_held" in memory:
                self._queue(lambda: self.holder_ended(name, wait_ended=True))
            else:
                self._queue(lambda: self.holder_settled(name, wait_ended=True))

    def _progress(self, agent: dict[str, Any]) -> tuple[Any, ...]:
        """What a task's progress reads: each submachine placement and the time of its last step, and the head of each own
        pull request; the harness machine's session events are the settles themselves, and a `HOLDER_RESUME` is the
        resume itself, so they are none."""
        name = agent["id"]
        placed = (
            (machine, each["state"], self._last_step(each))
            for machine in sorted(self._feed.machines)
            if machine not in (BOARD, HARNESS_MACHINE) and (each := self._feed.machine_task(machine, name))
        )
        return (*placed, *sorted(self._heads(agent).items()))

    @staticmethod
    def _last_step(placement: dict[str, Any]) -> float | None:
        return next((step["at"] for step in reversed(placement["trail"]) if step["event"] != HOLDER_RESUME), None)

    def _awaits(self, agent: dict[str, Any]) -> bool:
        """Whether an event ends the wait of a settled task: its open pull request's checks still pending (a CI pass,
        fail or merge), or an unfinished placement in an awaited machine (`awaits`): a lens a link of the phase it is in
        runs, until its exit state (a placement left while the task is in no such phase holds nothing), else a machine
        no link names, until a final state."""
        name = agent["id"]
        for url in self._own_prs(agent):
            state, *_, checks, _ = self._pull_state(url)
            if state == "OPEN" and checks == "pending":
                return True
        for machine in self._awaiting:
            placed = self._feed.machine_task(machine, name)
            if not placed:
                continue
            named = [
                (parent, link) for parent, links in self._links.items() for link in links if link["machine"] == machine
            ]
            if named:
                if any(
                    (phase := self._phase(parent, name))
                    and link["state"] == phase["state"]
                    and placed["active"] >= phase.get("since", 0.0)
                    and not link["exits"].get(placed["state"])
                    for parent, link in named
                ):
                    return True
            elif not any(
                each["id"] == placed["state"] and each["final"]
                for each in self._feed.machines.get(machine, {}).get("states", ())
            ):
                return True
        return False

    def _comments(self, agent: dict[str, Any]) -> list[str] | None:
        """The texts of the task's comments, oldest first, None when the read fails."""
        try:
            comments = (self._read(agent["id"]) or {}).get("comments") or []
        except Exception as error:
            logger.warning("task actor: cannot read the comments of %s: %s", agent["id"], error)
            return None
        return [str(comment.get("text") or "") for comment in comments]

    def _answered(self, agent: dict[str, Any], ask: str) -> bool:
        """Whether the operator already answered this very ask: an `Operator answer` comment follows the last time the
        task carried `ask`, so parking the task on it again would put the question to them twice. A new ask (another
        pull request, another reason) is a new question."""
        if (texts := self._comments(agent)) is None:
            return False
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
            if source == self._review and target == self._feed.roles.working:
                self._memory.keep(name, own_send_back=True)
            self._landed(self._clock() - observed)
            if merged is not None:  # timed at the lane write, ahead of the hooks that tell the board and the holder
                self._merge_move.observe(max(0.0, self._wall() - merged))
                if self._received is not None:
                    self._receipt_done.observe(max(0.0, self._wall() - self._received))
            roles = self._feed.roles
            if source == roles.working and target == roles.waiting:
                self._notice(self._tell, name, "was parked but its holder was not told")
            if source == roles.waiting and target in (roles.ready, roles.review):
                self._notice(self._released, name, "was released but its holder was not told")
            if target == roles.working:
                self._notice(
                    self._returned,
                    name,
                    "was sent back but its holder was not told",
                    on_failure=lambda: self._return_unwoken(name),
                )
            if target == roles.done:
                self._notice(self._closed, name, "was closed but the board was not told")
            return True
        logger.warning("task actor: %s was not moved to %s: %s", name, target, written.output)
        if written.transient:  # not a refusal: the task stays in its lane and the next pass tries the move again
            self._unsettled = True
            self._tried.pop(name, None)
            exited = self._memory.of(name).get("exited") or {}  # a Board exit goes again on the next pass
            exited.pop(BOARD, None)
            self._memory.keep(name, exited=exited or None)
            return False
        if target == self._feed.roles.ready:
            self._hold_for_repair(name, written.output)
        elif target == self._feed.roles.done:
            self._hold_done(name, written.output)
        elif target == self._review and source == self._feed.roles.working:
            self._hold_review(name, written.output)
        with self._metrics:
            self._refusals += 1
        return False

    def _hold_done(self, name: str, refusal: str) -> None:
        """Record a refused Done move on the task and wake its holder with the refusal: the move is not tried again
        until the task's facts change, so without the note and the wake a merged task sits in its lane."""
        reason = refusal.rstrip(".")
        written = self._apply(name, {}, f"{DONE_HELD} {reason}.")
        if not written.ok:
            logger.warning("task actor: the Done refusal of %s was not commented: %s", name, written.output)
        self._wake_holder(name, "DONE_REFUSED", reason)

    def _hold_review(self, name: str, refusal: str) -> None:
        """Comment the refusal of a working task's move to Review on the task and wake its holder with it, once per
        refusal and pull request head: the move is tried again when the task's record or its pull request changes, so
        without the note and the wake a pull request with green checks sits In Progress with the reason only in the
        service log. The note names the head, so a restart, a lane round trip or a refusal that returns does not
        repeat what the task's comments already hold."""
        agent = self._feed.task(name, lean=True)
        reason = refusal.rstrip(".")
        heads = ", ".join(sorted(head[:12] for head in self._heads(agent).values()))
        note = (
            f"Review refused: {reason}. The task actor tries the move again when the task or its pull request changes; "
            f"do not retry it{f' (head {heads})' if heads else ''}"
        )
        self._lint_held[name] = _lint_record(agent)  # an edit that repairs it is a change
        if note in self._comment_texts(name):
            return
        written = self._apply(name, {}, note)
        if not written.ok:
            logger.warning("task actor: the Review refusal of %s was not commented: %s", name, written.output)
        self._wake_holder(name, "REVIEW_REFUSED", reason)

    def _comment_texts(self, name: str) -> set[str]:
        try:
            comments = (self._read(name) or {}).get("comments") or []
        except Exception as error:  # an unread board comments again, which a repeat costs less than a lost refusal
            logger.warning("task actor: cannot read the comments of %s: %s", name, error)
            return set()
        return {str(comment.get("text") or "").strip() for comment in comments}

    def _wake_holder(self, name: str, event: str, reason: str) -> None:
        """Publish `event` on the task's topic, which the holder's consumer carries (`task.<id>.review_refused`)."""
        if self._log is not None:
            machine_events.publish(IN_PROGRESS, event, actor=ACTOR, task=name, data={"reason": reason}, log=self._log)

    def _return_unwoken(self, name: str) -> None:
        """A send-back whose holder no wake reached goes to Ready for a new session, unless the holder has since moved it."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            if agent is None or agent["state"] != self._feed.roles.working:
                return
            self._write(
                name,
                self._feed.roles.ready,
                "Returned to Ready: it was sent back to its session but its holder could not be woken.",
                self._clock(),
                source=agent["state"],
            )

    def _hold_for_repair(self, name: str, refusal: str) -> None:
        """Leave a task whose release the board refused in its lane and comment the refusal, no operator
        question: any editor of the record repairs it, and the actor tries the release again when the record changes."""
        self._lint_held[name] = _lint_record(self._feed.task(name, lean=True))
        written = self._apply(name, {}, f"{LINT_REFUSED} {refusal.rstrip('.')}.")
        if not written.ok:
            logger.warning("task actor: the release refusal of %s was not commented: %s", name, written.output)

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

        self._queue(run)

    def _queue(self, run: Callable[[], None]) -> None:
        """Run `run` on the notifier thread, after the actor's lock is released, in the order queued."""
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

    def _apply(self, name: str, changes: Mapping[str, Any], comment: str) -> Written:
        # the board-files pass finds the lane recorded under the actor; no other task's write holds this one up
        with self._feed.recording_of(name):
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
                # adr-exempt: retry
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
        Review proves its work on `_proof_prs`; every other lane still waits on its own pull requests only. In the
        working lane the latest merge must follow the task's latest entry."""
        own = self._own_prs(agent)
        if not own and agent["prs"] and agent["type"] == "check":
            if not all(criterion["checked"] for criterion in agent.get("criteria", ())):
                return None
            proof = f"no pull request of its own; cites {', '.join(agent['prs'])}"
            return proof, f"{MERGE_EVIDENCE} {proof}"
        parts = []
        proved = self._proof_prs(agent)
        for url in proved:
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
        merged_at = self._merged_at(agent)
        if (
            agent["state"] == self._feed.roles.working
            and merged_at is not None
            and merged_at < (agent.get("entered") or 0.0)
            and not self._deploy_reopened(agent)
        ):
            return None  # the merge predates the task's latest entry: a reopened task's earlier delivery proves nothing
        # the board's guard wants the evidence to name every cited pull request: a reference is named as one, not proof
        if references := [url for url in agent["prs"] if url not in proved]:
            parts.append(f"cites as a reference, not proof: {', '.join(references)}")
        proof = "; ".join(parts)
        return proof, f"{MERGE_EVIDENCE} {proof}"

    def _pr_merged(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The merge evidence when every pull request the task cites has ended and at least one merged, else None: a
        delivery closed unmerged is no proof of the work. A closed one beside a merged one stays cited for the audit
        trail and is named closed in the evidence, which the board's proof guard asks to name every cited one."""
        terminal = self._pr_terminal(agent)
        records = [self._record(url) for url in self._proof_prs(agent)]
        merged = any(record and record["state"] == "MERGED" for record in records)
        return terminal if terminal and merged else None

    def _pr_closed_unmerged(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The closed pull requests and the archive reason when every pull request the task cites has ended and none
        merged: its delivery is gone and the close is the answer: the task archives as superseded, and a redelivery is a new task."""
        terminal = self._pr_terminal(agent)
        records = [self._record(url) for url in self._proof_prs(agent)]
        if not terminal or any(not record or record["state"] != "CLOSED" for record in records):
            return None
        return terminal[0], f"superseded: {', '.join(self._proof_prs(agent))} closed unmerged"

    def _pr_closed_unmerged_complete(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The closed pull requests when `_pr_closed_unmerged` holds and every criterion is checked: the work was done
        without a merge (a no-op), so nothing is left to ask the operator."""
        closed = self._pr_closed_unmerged(agent)
        ticks = tuple(criterion["checked"] for criterion in agent.get("criteria", ()))
        if not closed or not ticks or not all(ticks):
            return None
        return closed[0], f"Every pull request it cites closed unmerged and every criterion is checked: {closed[0]}."

    def _pr_merged_unfinished(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The merge evidence and what is left when the task's pull requests merged and the board reports work
        unfinished, else None. A command that fails reports its error: the task returns to its
        holder, never closes."""
        merged = self._pr_merged(agent)
        if merged is None:
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

    def _deploy_reopened(self, agent: dict[str, Any]) -> bool:
        """Whether the task's latest reopen from Done was a failed deploy of its merge. A read that fails leaves the pass
        unsettled, so the next one asks again."""
        if (texts := self._comments(agent)) is None:
            self._unsettled = True
            return False
        reopens = [text for text in texts if text.startswith("Reopened from Done: ")]
        return bool(reopens) and _DEPLOY_FAILED.search(reopens[-1]) is not None

    def _pr_ready(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The ready or merged pull requests when the task cites one that is, else None. A task sent back from Review
        stays put while its ready pull request keeps the head it was sent back on: a new head or a run of `review` is the
        session's answer. An open pull request is ready only when it does not conflict with its base and the rollup of
        its current head says every required check passed (`checks_verdict`): a required check not posted is not green,
        a push re-arms the gate, and a repository whose ruleset requires none rolls up passed as soon as the pull
        request is not a draft."""
        parts = []
        sent_back = self._memory.of(agent["id"]).get("sent_back")
        held = sent_back or {}
        # In the working lane a PR merged before the task's latest entry is shipped work (a post-merge send back).
        floor = (agent.get("entered") or 0.0) if agent["state"] == self._feed.roles.working else 0.0
        if floor and sent_back is None and self._deploy_reopened(agent):
            floor = 0.0  # a failed deploy sent shipped work back: the merge closes it through Review, never an operator's send-back from Review
        for url in self._own_prs(agent):
            record = self._record(url)
            if record is None:
                continue
            merged = record["state"] == "MERGED" and record["mergedAt"]
            if merged and (_epoch(record["mergedAt"]) or 0.0) < floor:
                continue
            reviewed = held.get(url) == record["headRefOid"]
            green = (
                checks_verdict(
                    record["state"], record["checks"], record["headRefOid"], record["rollup"], record["requiredChecks"]
                )
                == "pass"
            )
            open_ready = not record["isDraft"] and record["mergeable"] != "CONFLICTING" and green and not reviewed
            if merged or (record["state"] == "OPEN" and open_ready):
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
        failing = self._open_pulls(
            agent,
            "Pull request checks failed",
            lambda record: (
                checks_verdict(
                    record["state"], record["checks"], record["headRefOid"], record["rollup"], record["requiredChecks"]
                )
                == "failing"
            ),
        )
        return failing and (
            failing[0],
            attention_reason(
                failing[1],
                "its required checks fail on the pull request head",
                ("fix it on the task branch and redeliver", "rescope the task"),
                ATTENTION_QUESTION,
            ),
        )

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
            running = self._alive(agent["id"])
        except Exception as error:
            self._unsettled = True
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

    def _phase_resumed(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The time and comment of the newest step of a phase in `[sequences]` the task's session took after the task
        entered its lane: the session going back to work is the event that sends the task back."""
        entered = self._entered(agent)
        steps = [
            (at, phase)
            for phase in sorted({phase for sequence in self._sequences.values() for phase in sequence})
            if (placed := self._feed.machine_task(phase, agent["id"]))
            and (at := self._resumed_at(phase, placed, entered)) is not None
        ]
        if not steps:
            return None
        at, phase = max(steps)
        return at, f"Its session resumed the {phase} phase. Sent back to In Progress."

    @staticmethod
    def _resumed_at(phase: str, placed: dict[str, Any], entered: float) -> float | None:
        # A delivery run that began before the task entered its lane is the holder finishing the run that put it there,
        # so its steps never count: a run ends with its `DELIVER_FINISHED`, and only one that begins after `entered` is
        # work resuming.
        if phase != "deliver":
            return placed["active"] if placed["active"] > entered else None
        began: float | None = None
        newest = None
        for step in placed["trail"]:
            began = step["at"] if began is None else began
            if began > entered:
                newest = step["at"]
            if step["event"] == "DELIVER_FINISHED":
                began = None
        return newest

    def _operator_pushback(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The words of the operator's pushback when it is the task's newest comment: the move it causes, or the
        answer to it, is a newer comment, so a task that returns to its lane carries no old pushback. Words that
        ask nothing get the question Needs attention requires."""
        if (texts := self._comments(agent)) is None:
            self._unsettled = True
            return None
        newest = texts[-1].strip() if texts else ""
        if not newest.startswith(_PUSHBACK):
            return None
        words = newest.removeprefix(_PUSHBACK).strip()
        return newest, words if "?" in words else f"{words}\n\nWhat change does it call for?"

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
        """Why the board withholds the task's `deps_done`; a hold that raises holds it with that error."""
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
        if self._probing or self._tried.get(name) == sent:
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
            return deadline[0], attention_reason(
                f"{gone}, so nothing releases this task. Its dependencies ({listed}) are cleared with this move",
                "its dependencies are not on the board, so none can release it",
                ("re-park it on the right tasks", "close it"),
                "Re-park it on the right tasks, or close it?",
            )
        gate = [*self._unmet(agent), *(each["id"] for each in criteria.authored(agent["description"]))]
        days = int((now - agent["entered"]) // _DAY_S)
        return deadline[0], attention_reason(
            f"Waiting {days} days, past its service level expectation ({deadline[1]})",
            f"it is still gated on {', '.join(gate) or 'its wait'}",
            ("release it", "re-park it on a new wait", "close it"),
            "Release it, re-park it on a new wait, or close it?",
        )

    def _criteria_met(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The subjects heard when an event the task is parked on arrived and no dependency is open, which would hold it back."""
        heard = sorted(self._heard.get(agent["id"], ()))
        if not heard or self._unmet(agent):
            return None
        return tuple(heard), f"Event {', '.join(heard)} arrived."

    def _deps_unresolved(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The dependencies that are not done, when there are any."""
        open_ = self._unmet(agent)
        return (open_, f"Not done: {', '.join(open_)}.") if open_ else None

    def _owner_stale(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The green main SHA and the closing note when the task owns a failure (`owner_source`), main's Validate passed,
        and no open task lists it as a dependency; a red main names no signature, so it closes nothing."""
        if not self._owns_failure(agent["id"]):
            return None
        waited_on = any(
            agent["id"] in (name.split("#")[0] for name in each["dependencies"]) for each in self._feed.open_tasks()
        )
        sha = None if waited_on else self._main_green()
        if not sha:
            return None
        return sha, f"Closed: main's Validate passed at {sha} and no open task waits on this failure."

    def _unmet(self, agent: dict[str, Any]) -> tuple[str, ...]:
        """The dependencies that are neither done nor early: still open for what the task waits on."""
        early = self._early(agent)
        return tuple(
            dependency
            for dependency in agent["dependencies"]
            if not self._cleared(dependency) and dependency not in early and not self._owner_green(dependency)
        )

    def _owner_green(self, dependency: str) -> bool:
        """Whether the dependency owns a failure (`owner_source`) and main's Validate passed: the failure no longer holds
        a task waiting on it, whatever lane the owner is in."""
        return self._owns_failure(dependency) and bool(self._main_green())

    def _owns_failure(self, task_id: str) -> bool:
        if not (self._owner_source and self._main_green):
            return False
        return str((self._read(task_id) or {}).get("source") or "").startswith(self._owner_source)

    def _early(self, agent: dict[str, Any]) -> tuple[str, ...]:
        """The open dependencies whose every criterion the task's record says it needs (`dependencyNeeds`, `TASK-N#K`)
        is checked: the fact the task waited on holds, whatever the dependency still has open. A dependency with no
        need names the whole task; a record the board cannot read names none."""
        open_ = [dependency for dependency in agent["dependencies"] if not self._cleared(dependency)]
        if not open_:
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
        "pr_merged_unfinished": _pr_merged_unfinished,
        "pr_ready": _pr_ready,
        "pr_failing": _pr_failing,
        "pr_draft": _pr_draft,
        "pr_conflicting": _pr_conflicting,
        "pr_unfinished_alive": _pr_unfinished_alive,
        "pr_unfinished_dead": _pr_unfinished_dead,
        "phase_resumed": _phase_resumed,
        "operator_pushback": _operator_pushback,
        "deps_done": _by_claim(_deps_done, claimed=False),
        "deps_done_with_pr": _deps_done_with_pr,
        "deps_done_started": _by_claim(_deps_done, claimed=True),
        "criteria_met_started": _by_claim(_criteria_met, claimed=True),
        "deps_unresolved": _deps_unresolved,
        "criteria_met": _by_claim(_criteria_met, claimed=False),
        "owner_stale": _owner_stale,
        "overdue": _overdue,
    }
