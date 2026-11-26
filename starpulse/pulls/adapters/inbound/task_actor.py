"""The task actor: a task advances itself on the facts its lane waits on.

A machine state's `waits` name a fact kind and the event that leaves the state when the fact holds
(`machine_definition.WAIT_FACTS`). The actor keeps a `PR -> tasks` and a `task -> dependents` index, so one change
touches only the tasks naming it, and when a task's pull request state, its own lane or a dependency's changes it
re-derives that task's waits and writes the first that holds through the board's task editor as `starpulse/task-actor`.
The actor reads the board's rules and the machine's guards as facts first (`Board.judge`) and skips a move one does not
hold; the board writer accepts every move it makes. A move so refused is logged and counted, and not tried again until the
task's facts change. A move to Done the board refuses (a Definition of Done item
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
The Board's phase is a task's lane, and its links count only when the actor writes every event they exit on; a skill placement from before the task entered
the lane is the last visit's and advances nothing.

A Waiting task parked on event subjects (the `kind: event` entries of its Start Criteria) is released by the first
event of any of them: the actor keeps a `subject -> tasks` index, `event_seen(subject)` is the follower's call for each
machine event the bridge names, and a task parking on a subject asks `latest(subject, since)` whether its last event happened since the
park, so an event racing the park releases at once; a wait met before the park releases only for a subject whose entry says `accept_met: true`. No evaluator is polled. The board may hold a task's `deps_done`
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
import subprocess
import threading
import time
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from starpulse.board.adapters.holder_idle import DISPATCHED, HARNESS_MACHINE, HolderInGrace, HolderUnreachable
from starpulse.board.model import criteria
from starpulse.board.model.acceptance import open_criteria, resolved
from starpulse.board.model.board_feed import BoardFeed
from starpulse.board.model.markdown import (
    ANSWER_COMMENT,
    FREEZE_REQUEST,
    UNFREEZE_REQUEST,
    attention_reason,
    needs_attention_text,
    operator_answered,
    request_reason,
    requested_by,
    section_set,
)
from starpulse.board.model.rollup import checks_verdict
from starpulse.board.model.seam import (
    COMMENT_CAP,
    FLAGGED,
    HELD,
    OPERATOR,
    TaskEditor,
    TaskReader,
    Written,
)
from starpulse.event_log import events as machine_events
from starpulse.event_log import start_requests
from starpulse.event_log.deadlines import Deadlines
from starpulse.event_log.wake import StopEvent, save_on_change
from starpulse.pulls.adapters.inbound.task_facts import ActorFacts
from starpulse.pulls.adapters.inbound.task_memory import TaskMemory
from starpulse.pulls.adapters.inbound.unblock import PinGate
from starpulse.pulls.adapters.outbound.pull_requests import own_prs, pull_record, uncited
from starpulse.pulls.model.histogram import Histogram
from starpulse.pulls.model.pins import LiveBuild, Pins, Repo
from starpulse.pulls.model.task_actor import TaskTouched, Trigger, derivation
from starpulse.pulls.model.task_actor.derivation import (
    ATTENTION_QUESTION,
    DONE_HELD,
    FACTS,
    FAULT,
    FAULT_NEXT,
    TERMINAL,
)

if TYPE_CHECKING:  # annotation only: the pull store and the event log open the database stack
    from starpulse.event_log.event_log import EventLog
    from starpulse.pulls.adapters.outbound.pulls import PullStore
lazy from starpulse.event_log.claude_sessions import same_holder

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


REFUSALS_METRIC = "starpulse_task_actor_refusals_total"
#: The reason of a refusal no guard rule made: a hook, a store error or a raised exception.
OTHER_REFUSAL = "other"
PIN_HELD_METRIC = "starpulse_task_actor_pin_held"
RECOVERY_FINISHED_METRIC = "starpulse_task_actor_recovery_finished"
MERGED_WAITING_METRIC = "starpulse_task_actor_merged_review_waiting"
DERIVE_METRIC = "starpulse_task_actor_derive_seconds"
TOUCH_METRIC = "starpulse_task_actor_touches_total"
IDLE_HOLDERS_METRIC = "starpulse_task_actor_idle_holders"
IDLE_SECONDS_METRIC = "starpulse_task_actor_idle_holder_seconds"
READY_METRIC = "starpulse_task_actor_ready_tasks"
HOLDER_RESUME = "HOLDER_RESUME"
UNCITED_CHECKS = "UNCITED_CHECKS"
#: The deliver states after its pull request opened.
_DELIVERED = frozenset({"pr_opened", "ci_green", "pr_ready"})
#: Nudges or resumes a fault with no progress between gets before the next one moves the task to Needs attention.
_ONE_TRY = 1
#: Nudges an idle holder with an open criterion gets before the next idle moves its task to Needs attention.
_NUDGES = 3
#: Seconds between two progress lines of the start recovery.
_PROGRESS_S = 30.0
#: The prefix of the deadline key that settles a holder again once its deliver grace has ended.
_GRACE = "grace:"
#: Seconds after a settle refused inside the deliver grace that it is settled again: just past the grace (180).
_GRACE_S = 190.0
#: Seconds before a pull request GitHub could not yet answer for (`mergeable` gave None) is asked again.
_MERGEABLE_RETRY_S = 30.0
#: Seconds a settled `mergeable` answer outlives a move of the base tip alone: every open pull request is read again on each
#: merge to the default branch, which spent a third of the GitHub core budget in a merge-heavy hour. A new head is read at once.
_BASE_MOVE_REREAD_S = 600.0
#: Seconds a dispatched or resumed session has to report its start; a healthy dispatch reports within seconds.
_START_BOUND_S = 300.0
#: The prefix of the deadline key that checks a resume's start, apart from a task's own overdue deadline.
_STARTED = "started:"
#: Seconds the exposition waits for the actor lock before it leaves out the series that need it.
_LOCK_WAIT_S = 2.0
#: Seconds the merged Review tasks count is kept, so a scrape loop never makes the scan over the open tasks a load.
_WAITING_TTL_S = 5.0
#: The touch causes that name a source; any other cause names a task or a subject, so its trigger is the source.
_TOUCH_SOURCES = frozenset(
    {
        "record",
        "holds read",
        "waiting sweep",
        "deadline",
        "phase_resumed",
        "pull requests projected",
        "pull request store saved",
        "merge webhook",
        "main checks run",
        "session settled",
    }
)
#: Seconds before a `mergeable` lookup that gave no answer (still computing, or unreachable) is asked again.
_MERGEABLE_RETRY_S = 30.0
LATENCY_METRIC = "starpulse_task_actor_latency_seconds"
#: The upper bounds of the latency histogram's buckets, in seconds; the count past the last is the `+Inf` bucket's.
BUCKETS_S = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
PROJECTION_METRIC = "starpulse_task_actor_projection_seconds"
HANDOFF_METRIC = "starpulse_task_actor_handoff_seconds"
MERGE_MOVE_METRIC = "starpulse_task_merge_move_seconds"
PARK_RELEASE_METRIC = "starpulse_task_park_release_seconds"
RECEIPT_DONE_METRIC = "starpulse_task_receipt_done_seconds"
MERGE_RECEIPT_LOCK_METRIC = "starpulse_task_actor_merge_receipt_lock_seconds"
MERGE_LOCK_WAIT_METRIC = "starpulse_task_actor_merge_lock_wait_seconds"
MERGE_BOARD_WRITE_METRIC = "starpulse_task_actor_merge_board_write_seconds"
#: The facts whose write moves a task because its pull requests ended; the merge-to-move histogram observes them.
_MERGE_FACTS = frozenset({"pr_terminal", "pr_merged", "pr_merged_unfinished"})
#: Most seconds start recovery waits for the saves and changes pending before it takes its next task, so steady traffic
#: slows recovery down but never stops it.
_YIELD_S = 2.0
#: Most seconds start recovery waits for a merge webhook that waits for the lock, a hang guard: a merge is rare and moves
#: its task for an operator, so unlike steady traffic it is never outwaited.
_MERGE_YIELD_S = 30.0
#: The worker state holding the digest of the facts each task was last derived on, and of the waits and moves it was
#: derived under, so a start derives only the tasks that changed since.
CHECKPOINT = "pulls.task_actor_checkpoint"
#: Bumped when a fact function reads something new or reads it differently: a checkpoint of another revision is unread.
_FACTS_REVISION = 7
#: Seconds between two saves of the checkpoint while the actor runs.
#: Seconds after a task's derived facts change before the checkpoint is saved.
_CHECKPOINT_DEBOUNCE_S = 10.0
_NOTICE_JOIN_S = 10.0
#: The bounds of the projection and handoff histograms: a pin walk takes seconds, and the 10 s bound is the measure.
SLOW_BUCKETS_S = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
#: The bounds of the park-release histogram: a release takes seconds, and a late one hours.
PARK_RELEASE_BUCKETS_S = (1.0, 10.0, 60.0, 300.0, 900.0, 3600.0, 14400.0, 43200.0)
#: Seconds to wait before each retry of a write that found the board database locked.
LOCK_BACKOFF_S = (0.1, 0.4, 1.6)

#: The facts whose event parks a task in Needs attention: the comment is also its `## Needs attention` reason, a question.
_ASKS = (
    "overdue",
    "pr_failing",
    "pr_closed_unmerged",
    "ask_requested",
    "pr_unfinished_dead",
    "pr_merged_unfinished",
)

#: The facts a comment alone raises, which the view does not show.
_COMMENTED = frozenset(
    (
        "operator_pushback",
        "pr_closed_unmerged_complete",
        "wait_requested",
        "ask_requested",
        "archive_requested",
        "move_requested",
        "freeze_requested",
        "unfreeze_requested",
    )
)
#: The only facts a frozen task's lane waits on: the requests to freeze or lift the freeze.
_FREEZES = ("freeze_requested", "unfreeze_requested")
#: The clock a freeze's `at` is written on, the operator's.
_FREEZE_ZONE = ZoneInfo("America/Phoenix")


def _later(delay: float, fn: Callable[..., None], *args: Any) -> None:
    timer = threading.Timer(delay, fn, args=args)
    timer.daemon = True
    timer.start()


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


def _no_holds(_task: str) -> Sequence[str]:
    return ()


_LINTED = ("description", "profile", "title", "type", "milestone", "impact", "urgency", "tier", "source")


def _lint_record(agent: Mapping[str, Any]) -> tuple[Any, ...]:
    """The parts of a task's record the board's release refusals read, which a repair changes and a comment does not."""
    return (*(agent.get(field) for field in _LINTED), tuple(agent["labels"]), tuple(agent.get("dependencies", ())))


def _view(
    agent: Mapping[str, Any],
) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[bool, ...], str, tuple[tuple[str, str], ...]]:
    """The parts of a task's record the actor re-derives on: its lane, dependencies, pull requests, checked criteria,
    a digest of its final summary and its freeze. A Done task the feed publishes as a dot (`done_dot`) holds neither dependencies nor pull requests."""
    ticks = tuple(criterion["checked"] for criterion in agent.get("criteria", ()))
    return (
        agent["state"],
        tuple(agent.get("dependencies", ())),
        tuple(agent.get("prs", ())),
        ticks,
        hashlib.sha1((agent.get("final_summary") or "").strip().encode(), usedforsecurity=False).hexdigest()[:8],
        tuple(sorted((agent.get("frozen") or {}).items())),
    )


def _rules_digest(
    waits: Mapping[str, Mapping[str, str]], moves: Mapping[tuple[str, str], str], sequences: Mapping[str, Sequence[str]]
) -> str:
    """A digest of the lanes' waits, the moves and the phase sequences, which a checkpoint is valid under."""
    drawn = [_FACTS_REVISION, waits, {f"{lane}|{event}": target for (lane, event), target in moves.items()}, sequences]
    return hashlib.sha1(json.dumps(drawn, sort_keys=True, default=dict).encode(), usedforsecurity=False).hexdigest()[
        :16
    ]


def moves_of(machine: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """`{(lane, event): target lane}` for the transitions of a drawn machine (`snapshot.describe`), and the same moves
    under `(lane, "<event>:<target>")`, which tells an event that leads to several lanes which one a request names."""
    moves = {(move["source"], move["event"]): move["target"] for move in machine["transitions"]}
    return moves | {
        (move["source"], f"{move['event']}:{move['target']}"): move["target"] for move in machine["transitions"]
    }


#: How many of a hold's reasons its comment lists; the rest are counted.
HOLD_REASONS_LISTED = 3


def _hold_comment(prefix: str, reasons: Sequence[str]) -> str:
    """The comment for a hold: the first few `reasons` and a count of the rest, clipped to the comment cap."""
    text = f"{prefix} {'; '.join(reasons[:HOLD_REASONS_LISTED])}"
    if len(reasons) > HOLD_REASONS_LISTED:
        text += f" (and {len(reasons) - HOLD_REASONS_LISTED} more)"
    return f"{text}."[:COMMENT_CAP]


class TaskActor:
    """Moves each open task whose lane waits on a fact that holds, once per change of that fact.

    `waits` is `{lane: {fact kind: event}}` (`Compiled.waits`) and `moves` is `{(lane, event): target lane}`, from the
    Board machine's transitions. `edit` is the board's task editor. `repos`, `pin_rule` and `pins` are the `[release]`
    pin-bump rule (`unblock.PinGate`): a dependency in a pinned repository is merged on the parent's pin bump.
    `judge` is what the board's rules say of a move (`Board.judge`): the board writer lets every move of the actor
    land, so the actor reads a refusal there first and skips a move the rules hold back.
    `latest(subject, since)` says whether an event subject's last event happened at or after `since` (None: none has), and `holds` the reasons the board withholds a task's `deps_done` (`Board.holds`). `read` is the
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
        judge: TaskEditor,
        repos: Sequence[Repo] = (),
        pin_rule: str | None = None,
        pins: Pins | None = None,
        board_repo: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        latest: Callable[[str, float], bool] | None = None,
        latest_sha: Callable[[str], str | None] | None = None,
        unpublished: Callable[[str], str | None] = lambda _subject: None,
        holds: Callable[[str], Sequence[str]] = _no_holds,
        parked: Callable[[str], None] = _ignore,
        released: Callable[[str], None] = _ignore,
        closed: Callable[[str], None] = _ignore,
        archived: Callable[[str], None] = _ignore,
        frozen: Callable[[str], None] = _ignore,
        returned: Callable[[str], None] = _ignore,
        alive: Callable[[str], bool] = lambda _task: False,
        enqueued: Callable[[str], None] = _ignore,
        live: LiveBuild | None = None,
        advance: Callable[[str, str, str], None] | None = None,
        read: TaskReader = lambda _task: None,
        idle: Callable[[str, str], None] | None = None,
        end: Callable[[str, str], None] | None = None,
        end_lanes: Collection[str] = frozenset(),
        sequences: Mapping[str, Sequence[str]] = MappingProxyType({}),
        awaits: Sequence[str] = (),
        unfinished: Callable[[str], Sequence[str]] = lambda _task: (),
        submodules: Callable[[], Sequence[tuple[str, str]]] | None = None,
        log: EventLog | None = None,
        main_green: Callable[[], str | None] | None = None,
        owner_source: str = "",
        started: Callable[[str], bool] = lambda _task: False,
        mergeable: Callable[[str, int], str | None] = lambda _repo, _number: None,
        checks: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._main_green = main_green
        #: Reads a stored open pull request's head checks live and stores them; once per head, again after a failed read, for a
        #: record that holds no rollup, which only an event lost before it was stored leaves.
        self._checks = checks
        self._checked: dict[tuple[str, str], float | None] = {}
        #: GitHub's answer now whether a pull request merges; a push that clears a conflict sends no event for it.
        self._mergeable = mergeable
        #: Per pull request, the stored record's version, what `mergeable` answered for it and when: an answer is read once,
        #: a None (GitHub still computing, or out of reach) again after `_MERGEABLE_RETRY_S`.
        self._settled: dict[str, tuple[tuple[str, str | None], str | None, float]] = {}
        #: The pull request versions whose `mergeable` read is running off the lock, and the tries of each task's write the
        #: board refused as locked, whose next try waits off the lock.
        self._reading_pulls: set[tuple[str, tuple[str, str]]] = set()
        self._lock_tries: dict[str, int] = {}
        #: The session whose dispatch to a task is mid-write, so its retry runs only while that session still holds it.
        self._dispatching: dict[str, str] = {}
        #: Whether a session was ever dispatched to a task, given its id, which the start event answers.
        self._started = started
        self._owner_source = owner_source
        self._read = read
        self._idle = idle
        #: Ends a task's holder session once idle (`[bridge] end`), and the lanes where a task's session is ended.
        self._end = end
        self._end_lanes = end_lanes
        self._memory = TaskMemory(read, lambda name, memory: self._edit_retrying(name, {"actorMemory": memory}, ""))
        self._advance = advance
        #: The phases a task of each type goes through, in order (`[sequences]`); `default` serves an unnamed type.
        self._sequences = sequences
        #: The machines whose unfinished placement of a task holds its settled session (`awaits`).
        self._awaiting = tuple(awaits)
        self._unfinished = unfinished
        #: The parent's declared `(name, path)` submodules: with them and `board_repo`, a task citing pull requests has its
        #: unfinished work answered here, never by `unfinished`.
        self._submodules = submodules
        #: Each non-Board machine's links that exit on a skill machine's state, when there is somewhere to send the exit.
        self._links = _exit_links(feed.machines) if advance else {}
        self._feed = feed
        self._store = store
        self._edit = edit
        self._judge = judge
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
        self._latest_sha = latest_sha
        self._commits: dict[str, dict[str, str]] = {}  # a task -> the commit each subject it waits on must contain
        self._accepts: dict[str, frozenset[str]] = {}  # a task -> the subjects whose park accepts an event recorded before it
        self._unpublished = unpublished
        self._publisher: dict[str, tuple[str | None, float]] = {}
        self._holds = holds
        #: The reasons each task's board hook printed for the facts it names, read on `task-actor-holds` off the lock,
        #: and the tasks whose read is queued or running: a hook runs a command for seconds, and run under `_lock` it
        #: held back the move of every task behind it, a merge's above all.
        self._hold_reads: dict[str, tuple[str, tuple[str, ...], bool]] = {}
        self._reading: set[str] = set()
        self._reads: queue.SimpleQueue[tuple[str, str] | None] = queue.SimpleQueue()
        self._reader: threading.Thread | None = None
        self._tell = parked
        self._released = released
        self._closed = closed
        self._archived = archived
        self._frozen = frozen
        self._returned = returned
        self._alive = alive
        self._enqueued = enqueued
        #: The lanes that wait on their tasks' dependencies, whose derivation flags a wait nothing ends.
        self._sweep_lanes = {lane for lane, facts in waits.items() if "deps_done" in facts}
        #: The lanes that wait on a task's Start Criteria.
        self._gated_lanes = {
            lane for lane, facts in waits.items() if {"criteria_met", "criteria_met_started"} & facts.keys()
        }
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
        self._pins = pins
        self._board_repo = (
            board_repo  # the repository whose pull requests read as a bare `PR #N`; another repo links its URL
        )
        self._port = ActorFacts(self)
        self._lock = threading.RLock()
        #: Each open task's lane, dependencies and pull requests as the actor last saw them.
        self._seen: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], tuple[bool, ...]]] = {}
        self._by_pr: dict[str, set[str]] = {}
        #: What each pull request last read as, so a refresh that changed nothing derives nothing.
        self._pull_states: dict[str, tuple[str, str | None, bool, str, str, str, str, int]] = {}
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
        #: The task whose session settle is deriving it: its answered ask closes a checked task with no pull request left.
        self._settling = ""
        #: The board hooks of moves already written, run one at a time in the order written by their own thread: a
        #: hook runs a command for seconds, and run under `_lock` it held back the move of every task behind it.
        self._notices: queue.SimpleQueue[Callable[[], None] | None] = queue.SimpleQueue()
        self._noticing_ended = False
        self._noticing = threading.Lock()
        self._notifier: threading.Thread | None = None
        #: How long each derivation ran, by the lane the task was in and whether a board hook ran in it.
        self._derive_seconds: dict[tuple[str, bool], Histogram] = {}
        #: How often each source touched a task, by the lane it was in: a cause named in `_TOUCH_SOURCES`, else its trigger.
        self._touches: Counter[tuple[str, str]] = Counter()
        #: Tasks whose dependencies are done but wait for a pin bump, and the store revision last read for them.
        self._pin_held: set[str] = set()
        self._store_rev = store.rev
        #: The move last tried for each task, until the task changes lane: the same facts are not tried twice.
        self._tried: dict[str, tuple] = {}
        #: The fault each task last had written or refused, by (lane, reason): a fault is not written again on another trigger.
        self._faults: dict[str, tuple[str, str]] = {}
        self._unready_logged: dict[str, str] = {}
        #: The record each task's release was last refused on by the board, so a repaired record is tried again.
        self._lint_held: dict[str, tuple[Any, ...]] = {}
        #: The note of each task's standing Review refusal, until a change repairs it: the holder's resume carries it.
        self._refused: dict[str, str] = {}
        self._released_visit: set[str] = set()  # tasks released into the working lane and not yet out of it again
        self._metrics = threading.Lock()
        #: The writes the board refused, by the key of the rule that refused them (`OTHER_REFUSAL` for none).
        self._refusals: Counter[str] = Counter()
        #: How many writes landed within each bound of `BUCKETS_S`, then how many in all, and their seconds summed.
        self._buckets = [0] * (len(BUCKETS_S) + 1)
        self._sum = 0.0
        #: How long each projection of the pull request store ran, and how long a store save waited for the actor.
        self._projection = Histogram(SLOW_BUCKETS_S)
        self._handoff = Histogram(SLOW_BUCKETS_S)
        #: Seconds from a pull request's merge to the write that moved the task citing it.
        self._merge_move = Histogram(SLOW_BUCKETS_S)
        self._receipt_done = Histogram(BUCKETS_S)
        #: Seconds from the first event a Waiting task was released on to the write that moved it, and when each was heard.
        self._park_release = Histogram(PARK_RELEASE_BUCKETS_S)
        self._heard_at: dict[str, float] = {}
        #: Seconds a merge webhook waited for the lock, and the board write that moved the task it merged.
        self._merge_receipt_lock = Histogram(BUCKETS_S)
        self._merge_lock_wait = Histogram(BUCKETS_S)
        self._merge_board_write = Histogram(BUCKETS_S)
        #: How many merge webhooks wait for the lock or hold it; start recovery takes no task while one does.
        self._merging = 0
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
        #: Set once the start's derivation of every open task is done. A task or move change and a store
        #: save are handled from `indexed` on, while it runs.
        self.ready = threading.Event()
        #: Set once the start sweep has indexed the open tasks and read their pull requests, before it derives them.
        self.indexed = threading.Event()
        #: How many times each task's waits were derived, for the tests and a diagnosis.
        self.derivations: Counter[str] = Counter()

    def exposition(self) -> str:
        """Prometheus text of the writes the board refused, how long a fact took to become a landed write, and whether the
        actor is alive: whether start recovery finished and the merged Review tasks not yet Done."""
        with self._metrics:
            counts, total = list(self._buckets), self._sum
            refusals = sorted(self._refusals.items()) or [(OTHER_REFUSAL, 0)]
            timed = sorted(self._derive_seconds.items())
            touches = sorted(self._touches.items())
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
                *(f'{REFUSALS_METRIC}{{reason="{reason}"}} {count}' for reason, count in refusals),
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
                *self._park_release.lines(
                    PARK_RELEASE_METRIC, "Seconds from an event a parked task waited on to the write that released it."
                ),
                *self._receipt_done.lines(
                    RECEIPT_DONE_METRIC, "Seconds from receiving a merge webhook to the write that moved its task."
                ),
                *self._merge_receipt_lock.lines(
                    MERGE_RECEIPT_LOCK_METRIC,
                    "Seconds from receiving a merge webhook to holding the task actor's lock: the inbox save, the claim, the write and the lock wait.",
                ),
                *self._merge_lock_wait.lines(
                    MERGE_LOCK_WAIT_METRIC, "Seconds a merge webhook waited for the task actor's lock."
                ),
                *self._merge_board_write.lines(
                    MERGE_BOARD_WRITE_METRIC, "Seconds the board write that moved a merged pull request's task took."
                ),
                f"# HELP {DERIVE_METRIC} Seconds each derivation of a task's waits ran, by lane and whether a board hook ran.",
                f"# TYPE {DERIVE_METRIC} histogram",
                *derives,
                f"# HELP {TOUCH_METRIC} Times a source touched a task to derive it, by the lane the task was in.",
                f"# TYPE {TOUCH_METRIC} counter",
                *(f'{TOUCH_METRIC}{{lane="{lane}",source="{source}"}} {count}' for (lane, source), count in touches),
                f"# HELP {RECOVERY_FINISHED_METRIC} 1 once the start recovery derived every open task, else 0.",
                f"# TYPE {RECOVERY_FINISHED_METRIC} gauge",
                f"{RECOVERY_FINISHED_METRIC} {int(self.ready.is_set())}",
                *self._held_lines(held),
                "",
            ]
        )

    def _held_counts(self) -> tuple[int, int, tuple[int, float, int]] | None:
        """The series that read the actor's state under its lock (the tasks held for a pin) and the merged Review tasks,
        read after it is released. None when another thread holds the lock past `_LOCK_WAIT_S`: a scrape must answer
        then, since a held lock is what the recovery gauge reports."""
        if not self._lock.acquire(timeout=_LOCK_WAIT_S):
            return None
        try:
            pin_held = len(self._pin_held)
        finally:
            self._lock.release()
        return pin_held, self._merged_waiting(), self._idle_holders()  # the feed reads hold no lock

    def _idle_holders(self) -> tuple[int, float, int]:
        """The In Progress tasks whose session reads settled with no event awaited (a settle the actor left to a resume
        that did not wake it), the seconds the oldest has been so, and the Ready tasks waiting."""
        since, ready = [], 0
        for agent in self._feed.open_tasks():
            if agent["state"] == self._feed.roles.ready:
                ready += 1
            elif agent["state"] == self._feed.roles.working:
                placed = self._feed.machine_task(HARNESS_MACHINE, agent["id"])
                if placed and placed["state"] != "active" and not self._awaits(agent):
                    since.append(placed["active"])
        return len(since), max(time.time() - min(since), 0.0) if since else 0.0, ready

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
        if agent["state"] != self._review or agent.get("frozen"):
            return False  # a frozen task keeps its lane: its merge is no wait the actor owes a move
        records = [self._record(url) for url in derivation.proof_prs(self._port, agent)]
        return any(record and record["state"] == "MERGED" for record in records)

    @staticmethod
    def _held_lines(held: tuple[int, int, tuple[int, float, int]] | None) -> list[str]:
        if held is None:
            return []
        pin_held, waiting, (idle, idle_s, ready) = held
        return [
            f"# HELP {PIN_HELD_METRIC} Waiting tasks whose dependencies are done but wait for a pin bump to merge.",
            f"# TYPE {PIN_HELD_METRIC} gauge",
            f"{PIN_HELD_METRIC} {pin_held}",
            f"# HELP {MERGED_WAITING_METRIC} Review tasks with a merged pull request that have not reached Done, including one whose move was refused.",
            f"# TYPE {MERGED_WAITING_METRIC} gauge",
            f"{MERGED_WAITING_METRIC} {waiting}",
            f"# HELP {IDLE_HOLDERS_METRIC} In Progress tasks whose session is settled with no CI check or awaited machine to wait on.",
            f"# TYPE {IDLE_HOLDERS_METRIC} gauge",
            f"{IDLE_HOLDERS_METRIC} {idle}",
            f"# HELP {IDLE_SECONDS_METRIC} Seconds the longest such session has been settled; 0 when none.",
            f"# TYPE {IDLE_SECONDS_METRIC} gauge",
            f"{IDLE_SECONDS_METRIC} {idle_s:.0f}",
            f"# HELP {READY_METRIC} Tasks in the Ready lane.",
            f"# TYPE {READY_METRIC} gauge",
            f"{READY_METRIC} {ready}",
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
        if self._timed_lanes or self._idle is not None:
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
        """Wait, up to `_YIELD_S`, until no save, change or projection is pending, then until no merge webhook is."""
        with self._events:
            self._events.wait_for(lambda: not (self._pending or self._saved.is_set()), timeout=_YIELD_S)
            self._events.wait_for(lambda: not self._merging, timeout=_MERGE_YIELD_S)

    def _store_saved(self, saved: float) -> None:
        with self._lock:
            observed = self._clock()
            self._handoff.observe(observed - saved)
            self.touch(self._webhooks(self._read_pulls(), "pull request store saved"), observed)

    def _stuck(self, agent: dict[str, Any]) -> tuple[str, ...]:
        """The dependencies that will not finish on their own: the Board holds no such task."""
        missing = self._missing(agent)
        return tuple(
            f"{dependency} is not on the board" for dependency in agent["dependencies"] if dependency in missing
        )

    def _missing(self, agent: dict[str, Any]) -> tuple[str, ...]:
        return derivation.missing(self._port, agent)

    def _cleared(self, dependency: str) -> bool:
        return derivation.cleared(self._port, dependency)

    def _derive_overdue(self, name: str) -> None:
        """Derive a task again at its own deadline, so a Waiting task goes overdue with no event to wake it."""
        if name.startswith(_STARTED):
            self._resume_unstarted(name.removeprefix(_STARTED))
            return
        if name.startswith(_GRACE):
            self._settle_graced(name.removeprefix(_GRACE))
            return
        with self._lock:
            self.touch([TaskTouched(name, Trigger.ON_ALERT, "deadline")])

    def _resume_unstarted(self, name: str) -> None:
        """The bound on a dispatch's start fell: a harness trail still ending on the dispatch means its session never
        started, so the task moves to Needs attention naming the dispatch."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            placed = self._feed.machine_task(HARNESS_MACHINE, name)
            last = ((placed or {}).get("trail") or [{}])[-1]
            if agent is None or agent["state"] != self._feed.roles.working or last.get("event") != DISPATCHED:
                return
            session = (last.get("data") or {}).get("session", "")
            self._attend(
                name,
                f"a dispatch of session {session} reported no start within {_START_BOUND_S:.0f} s",
                "dispatch never started",
                "Start one by hand or rescope?",
                ("start a session on it by hand", "rescope the task"),
            )

    def reconcile_waiting(self) -> tuple[int, int]:
        """The sweeper's `waiting` pass: (the tasks in the lanes that wait on `deps_done`, those it released). A task whose
        dependencies are done and merged is released on the event that made them so; one found so on two passes in a row
        missed it, so it is derived again, and counted when that moved it on: a refused release does not count."""
        with self._lock:
            tasks = [agent for agent in self._feed.open_tasks() if agent["state"] in self._sweep_lanes]
            releasable = {agent["id"] for agent in tasks if derivation.deps_done(self._port, agent) is not None}
            unrepaired = {agent["id"] for agent in tasks if self._lint_held.get(agent["id"]) == _lint_record(agent)}
            missed = sorted(releasable & self._releasable - unrepaired)  # a refused release waits for its repair
            self._releasable = releasable
            for name in missed:
                self._tried.pop(name, None)
            self._unsettle(missed)  # the sweep exists for a task whose release no fact's change brought
            self.touch([TaskTouched(name, Trigger.ON_ALERT, "waiting sweep") for name in missed])
            ready = self._feed.roles.ready
            released = [
                name for name in missed if (moved := self._feed.task(name, lean=True)) and moved["state"] == ready
            ]
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
            if (
                self._idle is not None
            ):  # a settle while down is replayed by `follow_holder_idle`; `confirm` spares a busy holder
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
                with (
                    self._lock,
                    self._feed.pinned_rows(),
                ):  # the flag holds only under the lock, so no other thread's move reads it
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
            if self._exit_owed(name):  # a task owing none waited, live, behind the changes the lock served instead
                self._yield()
                with self._lock:
                    if stop is not None and stop.is_set():
                        break
                    self._exit_phase(name)
            report(done, len(swept))

    def _watch(self, name: str, agent: dict[str, Any]) -> bool:
        """Index the event subjects `agent` waits on in a gated lane; True when they differ from the last call's. A
        subject whose last event was recorded since the park counts as heard, so an event racing the park releases at
        once; one before the park counts only for a subject that `accept_met`."""
        gate = criteria.subjects(agent["description"]) if agent["state"] in self._gated_lanes else ()
        commits = criteria.commits(agent["description"]) if gate else {}
        accepted = criteria.accepting_met(agent["description"]) if gate else frozenset()
        if (
            gate == self._gates.get(name, ())
            and commits == self._commits.get(name, {})
            and accepted == self._accepts.get(name, frozenset())
        ):
            return False
        entered = derivation.entered(self._port, agent)
        heard = {
            subject
            for subject in gate
            if self._happened(subject, commits.get(subject), 0.0 if subject in accepted else entered)
        }
        logger.info("task actor: %s waits on %s, already heard %s", name, sorted(gate), sorted(heard))
        self._unwatch(name)
        self._gates[name] = gate
        if accepted:
            self._accepts[name] = accepted
        if commits:
            self._commits[name] = commits
        for subject in gate:
            self._until.setdefault(subject, set()).add(name)
        if heard:
            self._heard[name] = heard
        return True

    def _happened(self, subject: str, commit: str | None, since: float) -> bool:
        """Whether `subject`'s last event is recorded at or after `since`, and for a wait on `commit`, names a build
        containing it."""
        if commit is not None:
            return self._latest_sha is not None and self._contains(self._latest_sha(subject), self._merge_of(commit))
        return self._latest is not None and self._latest(subject, since)

    def _unwatch(self, name: str) -> None:
        for subject in self._gates.pop(name, ()):
            self._until[subject].discard(name)
            if not self._until[subject]:
                del self._until[subject]
        self._heard.pop(name, None)
        self._heard_at.pop(name, None)
        self._commits.pop(name, None)
        self._accepts.pop(name, None)

    def event_seen(self, subject: str, sha: str | None = None) -> None:
        """Derive the Waiting tasks parked on `subject` again: the first event on a subject they wait on releases them.

        A task parked for a commit is released only by an event whose `sha` build contains that commit."""
        with self._lock:
            names = sorted(
                name
                for name in self._until.get(subject, ())
                if (commit := self._commits.get(name, {}).get(subject)) is None
                or self._contains(sha, self._merge_of(commit))
            )
            logger.info("task actor: event %s matched Waiting tasks %s", subject, names or "none")
            for name in names:
                self._heard.setdefault(name, set()).add(subject)
                self._heard_at.setdefault(name, self._wall())
            self.touch([TaskTouched(name, Trigger.ON_ALERT, subject) for name in names])

    def _merge_of(self, commit: str) -> str | None:
        """`commit`, or for a task key the merge commit of that task's last merged pull request, None before one."""
        keys = self._feed.keys
        agent = self._feed.task(keys.canonical(commit) if keys else commit, lean=True)
        if agent is None:
            return commit
        records = (pull_record(self._store, url) for url in agent["prs"])
        return next((record["mergeSha"] for record in reversed(list(records)) if record and record["mergeSha"]), None)

    def _contains(self, sha: str | None, commit: str | None) -> bool:
        return bool(
            sha and commit and self._pins and self._board_repo and self._pins.reaches(self._board_repo, commit, sha)
        )

    def _index(self, agent: dict[str, Any]) -> None:
        """Take `agent`'s lane, dependencies, pull requests and checked criteria into the indexes."""
        name = agent["id"]
        for url in self._seen.get(name, ("", (), (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._seen[name] = _view(agent)
        left = self._memory.of(name).get("lane_entered", [""])[0]
        if left != agent["state"]:
            entered = agent.get("entered") or 0.0
            kept: dict[str, Any] = {"lane_entered": [agent["state"], entered]}
            roles = self._feed.roles
            # an answer out of Needs attention is no new delivery: work merged while parked stays shipped
            if agent["state"] == roles.working and left != roles.attention:
                kept["work_floor"] = entered
            elif agent["state"] not in (roles.working, roles.attention):
                kept["work_floor"] = None
            self._memory.keep(name, **kept)
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
                self.touch(self._dependency_touched(self._dependents(name), name), observed)
                return
            regated = self._watch(name, agent)
            repaired = name in self._lint_held and self._lint_held[name] != _lint_record(agent)
            if repaired:
                del self._lint_held[name]
                self._refused.pop(name, None)
            rearmed = agent["state"] in self._timed_lanes and tuple(
                criteria.expect_dates(agent["description"])
            ) != self._dates.get(name, ())
            waits = self._waits.get(agent["state"], {})
            pushable = bool(_COMMENTED.intersection(waits))  # a comment leaves the view as it was
            if before == (now := _view(agent)) and not (repaired or rearmed or regated or pushable):
                return
            if pushable and before == now:
                self._unsettle([name])  # a comment is no digest fact: a settled Waiting task derives again to read it
            self._index(agent)
            lane = before is None or before[0] != now[0]
            if now[0] != self._feed.roles.working:
                self._released_visit.discard(name)
            events = [TaskTouched(name, Trigger.ON_ENTRY, now[0])] if lane else []
            if before is not None and lane:
                events.append(TaskTouched(name, Trigger.ON_EXIT, before[0]))
            if not lane:
                events.append(TaskTouched(name, Trigger.ON_SUBSTATE_CHANGE, "record"))
            if before is None:  # a task created: a hold may have waited on it, a fact no digest holds
                events += self._dependency_touched(self._held - {name}, name)
                self._unsettle(self._held - {name})
            if before is None or before[0] != now[0]:
                self._tried.pop(name, None)
                working = self._feed.roles.working
                kept: dict[str, Any] = {} if now[0] == working else {"busy": None, "resumes": None}
                if before and before[0] == self._review and now[0] == working:
                    own = self._memory.has(name, "own_send_back")
                    held = self._memory.of(name).get("sent_back")  # the baseline the actor's feedback move recorded
                    kept |= {
                        "sent_back": None if own else held if isinstance(held, int) else self._replies(agent),
                        "own_send_back": None,
                    }
                elif before is not None or now[0] != working:
                    kept["sent_back"] = (
                        None  # a task first seen outside the working lane keeps no hold from an earlier run
                    )
                roles = self._feed.roles
                sent_back = before and before[0] == roles.working and self._memory.has(name, "sent_back")
                kept["parked_out"] = (
                    True if before and now[0] == roles.waiting and (sent_back or before[0] in (self._review, roles.attention)) else None
                )  # a park out of Review or Needs attention, or of a send-back: its release resumes the work, not the pull request
                kept["reviewed"] = self._heads(agent) if "phase_resumed" in self._waits.get(now[0], {}) else None
                self._memory.keep(name, **kept)
            if before is None or (before[0], before[3]) != (now[0], now[3]):
                events += self._dependency_touched(self._dependents(name), name)
            self.touch(events, observed)

    def _moved(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._exit_phase(data["id"])
            self._settle_awaited(data["id"])
            self._settle_busy(data)
            agent = self._feed.task(data["id"], lean=True)
            if agent and "phase_resumed" in self._waits.get(agent["state"], {}):
                self.touch([TaskTouched(data["id"], Trigger.ON_SUBSTATE_CHANGE, "phase_resumed")])

    def _exit_phase(self, task: str) -> None:
        """Send the exit event of the phase `task` is in when that phase's skill machine sits in the state its link exits
        on. A skill machine the current phase does not link never counts, so a late final event of an earlier phase's
        skill advances nothing."""
        exited = self._memory.of(task).get("exited") or {}
        for parent, links in self._links.items():
            if due := self._exit_due(parent, links, task, exited):
                phase, event, sent = due
                exited[parent] = sent
                target = self._moves.get((phase["state"], event)) if parent == BOARD else None
                if target:  # the Board's lane is the task's status: the exit is that write, not an event beside it
                    self._memory.keep(
                        task, exited=exited
                    )  # a transient refusal clears it (`_write`), so the next pass goes again
                    self._write(
                        task, target, f"{phase['state']} phase exited on {event}", self._clock(), phase["state"]
                    )
                    exited = self._memory.of(task).get("exited") or {}  # a transient refusal cleared the marker
                else:
                    self._advance(parent, task, event)  # a refused or lost send leaves no marker: the exit goes again
                    self._memory.keep(task, exited=exited)

    def _exit_owed(self, task: str) -> bool:
        """Whether `task` owes a phase exit, read without the lock: the sweep takes the lock only for a task that does."""
        exited = self._memory.of(task).get("exited") or {}
        return any(self._exit_due(parent, links, task, exited) for parent, links in self._links.items())

    def _exit_due(
        self, parent: str, links: Sequence[Mapping[str, Any]], task: str, exited: Mapping[str, Any]
    ) -> tuple[dict[str, Any], str, list[Any]] | None:
        """The phase `task` is in under `parent`, its exit event and the marker that exit leaves, when it is not sent yet."""
        phase = self._phase(parent, task)
        event = self._exit_event(links, phase, task) if phase else None
        if phase and event and exited.get(parent) != (sent := [phase["state"], phase["steps"], event]):
            return phase, event, sent
        return None

    def _phase(self, parent: str, task: str) -> dict[str, Any] | None:
        """The phase `task` is in under lifecycle machine `parent`: the machine's placement, or the Board's lane, whose
        visit is told apart by when the task entered it (`since`, which a skill placement must not precede)."""
        if parent != BOARD:
            return self._feed.machine_task(parent, task)
        agent = self._feed.task(task, lean=True)
        entered = derivation.entered(self._port, agent) if agent else 0.0
        return {"state": agent["state"], "steps": entered, "since": entered} if agent else None

    def _exit_event(self, links: Sequence[Mapping[str, Any]], phase: Mapping[str, Any], task: str) -> str | None:
        for link in links:
            placed = self._feed.machine_task(link["machine"], task) if link["state"] == phase["state"] else None
            if placed and placed["active"] >= phase.get("since", 0.0) and link["exits"].get(placed["state"]):
                return self._route(link, task) or link["exits"][placed["state"]]
        return None

    def _sequence(self, agent: Mapping[str, Any]) -> Sequence[str]:
        """The phases of `agent`: the row its `kind-<name>` label names (`decide`, `one-off`), else its type's row, else
        `default`; the same lookup as `temporal_runner.sequences.phases`, which this package cannot import."""
        kinds = (
            self._sequences.get(label.removeprefix("kind-"))
            for label in agent.get("labels", ())
            if label.startswith("kind-")
        )
        return (
            next(filter(None, kinds), None)
            or self._sequences.get(agent.get("type", "").lower())
            or self._sequences.get("default", ())
        )

    def _route(self, link: Mapping[str, Any], task: str) -> str | None:
        """The event of the link's route to the phase after it in the sequence of `task` (its `decide` row when kind-decide, else its type), when the link draws one."""
        sequence = self._sequence(self._feed.task(task, lean=True) or {})
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
        deadline = derivation.deadline(self._port, agent) if timed else None
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

    def _unsettle(self, names: Iterable[str]) -> None:
        """Drop the tasks' settled digests, so the next touch derives each, and the checkpoint keeps none of them."""
        for name in names:
            self._derived.pop(name, None)
        self._derived_moved.set()

    def _forget(self, name: str) -> None:
        self._derived.pop(name, None)
        self._derived_moved.set()
        for url in self._seen.pop(name, ("", (), (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._tried.pop(name, None)
        self._lint_held.pop(name, None)
        self._refused.pop(name, None)
        self._released_visit.discard(name)
        self._unready_logged.pop(name, None)
        self._deadlines.cancel(name)
        self._deadlines.cancel(_STARTED + name)
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
            self.touch(self._webhooks(touched, "pull requests projected"), observed)

    def merge_received(self, received_at: float) -> None:
        """Re-derive the tasks whose pull requests changed, on the caller's thread: the merge webhook received at
        `received_at` (wall time) moves its task without waiting on the save follower, a projection or older deliveries.
        Each merge's move it lands is timed from `received_at`. A failure is logged, never raised to the consumer."""
        observed = self._clock()
        with self._events:
            self._merging += 1
        try:
            with self._pressing(), self._lock:
                self._merge_lock_wait.observe(self._clock() - observed)
                self._merge_receipt_lock.observe(max(0.0, self._wall() - received_at))
                self._received = received_at
                try:
                    self.touch(self._webhooks(self._read_pulls(), "merge webhook"), observed)
                finally:
                    self._received = None
        except Exception:
            logger.exception("task actor: cannot derive the tasks of a merge webhook")
        finally:
            with self._events:
                self._merging -= 1
                self._events.notify_all()

    def main_checked(self) -> None:
        """Re-derive every open task whose checks read main's health (`_reads_main`), on the caller's thread: a finished
        checks run on main. The main-green read is taken again first. A failure is logged, never raised to the consumer."""
        observed = self._clock()
        try:
            with self._pressing(), self._lock:
                if forget := getattr(self._main_green, "forget", None):  # a stub green has no cache to drop
                    forget()
                names = [name for name in self._seen if self._reads_main(name)]
                self._unsettle(names)  # main's health is no fact a digest holds
                self.touch(self._webhooks(names, "main checks run"), observed)
        except Exception:
            logger.exception("task actor: cannot derive the tasks that read main's health")

    def _reads_main(self, name: str) -> bool:
        """Whether the task owns a failure or waits on a task that does: the two checks that read main's health."""
        return self._owns_failure(name) or any(map(self._owns_failure, self._seen[name][1]))

    def _read_pulls(self) -> set[str]:
        """The tasks citing a pull request, or holding one open that names them and they do not cite, whose state changed since it was last read."""
        touched: set[str] = set()
        watched = {url: set(names) for url, names in self._by_pr.items()}
        working = self._feed.roles.working
        for name, (lane, _, cited, *_) in self._seen.items():
            if lane == working and not cited:  # its holder hears an uncited pull request's checks settle
                for url in uncited(self._store, {"id": name, "prs": cited}, self._feed.keys):
                    watched.setdefault(url, set()).add(name)
        for url, names in watched.items():
            if self._pull_states.get(url) != (state := self._pull_state(url)):
                self._pull_states[url] = state
                touched |= names
        return touched

    def _record(self, url: str) -> dict[str, Any] | None:
        record = pull_record(self._store, url)
        if record and self._checks and self._unrolled(record) and self._check_due(key := (url, record["headRefOid"])):
            self._checked[key] = None
            threading.Thread(
                target=self._settle_checks, args=(url, record, self._checks), name="task-actor-checks", daemon=True
            ).start()
        if record and record["state"] == "OPEN":
            detail = (pull_record(self._store, url, detailed=True) or record).get("detail") or {}
            version = (record["headRefOid"], detail.get("baseOid"))
            settled = self._settled.get(url, ((), None, 0.0))
            base_moved_only = (
                settled[0][:1] == version[:1]
                and settled[1] in ("MERGEABLE", "CONFLICTING")
                and self._clock() - settled[2] < _BASE_MOVE_REREAD_S
            )
            if settled[0] != version and not base_moved_only:
                self._read_mergeable(url, version, record["repo"], record["number"])
                return {**record, "mergeable": "UNKNOWN"}  # a stored MERGEABLE may predate the base's tip: unsettled until GitHub answers
            if settled[1] is None and self._clock() - settled[2] >= _MERGEABLE_RETRY_S:
                self._read_mergeable(url, version, record["repo"], record["number"])
            if settled[1] in ("MERGEABLE", "CONFLICTING"):
                return {**record, "mergeable": settled[1]}
        return record

    def _check_due(self, key: tuple[str, str]) -> bool:
        """Whether the head's checks are unread, or the last read of them failed `_MERGEABLE_RETRY_S` ago; a read in flight or answered is not."""
        return (
            key not in self._checked
            or (failed := self._checked[key]) is not None
            and self._clock() - failed >= _MERGEABLE_RETRY_S
        )

    @staticmethod
    def _unrolled(record: dict[str, Any]) -> bool:
        return (
            record["state"] == "OPEN"
            and not record["isDraft"]
            and (record["rollup"] is None or not record["headRefOid"])
        )

    def _settle_checks(self, url: str, record: dict[str, Any], read: Callable[[dict[str, Any]], None]) -> None:
        failed = False
        try:
            read(record)
        except Exception as error:  # the head stays pending, read again after `_MERGEABLE_RETRY_S`
            logger.warning("task actor: cannot read the checks of %s: %s", url, error)
            failed = True

        def settle() -> None:
            if failed:
                self._checked[url, record["headRefOid"]] = self._clock()

        self._hand_in(url, "checks read", settle)

    def _hand_in(self, url: str, why: str, settle: Callable[[], None] = lambda: None) -> None:
        """Run `settle` and derive the tasks citing `url` once a read made off the lock has its answer."""
        try:
            with self._pressing(), self._lock:
                if self._noticing_ended:  # a move made after the notices close would miss its hook
                    return
                settle()
                self._pull_states[url] = self._pull_state(url)
                if not self._noticing_ended:  # a move made after the notices close would miss its hook
                    self.touch(self._webhooks(sorted(self._by_pr.get(url, ())), why))
        except Exception:  # touch derives under the lock and may raise
            logger.exception("task actor: cannot derive the tasks of %s on its %s", url, why)

    def _read_mergeable(self, url: str, version: tuple[str, str | None], repo: str, number: int) -> None:
        """Read GitHub's answer for the pull request on a thread of its own, so the lock never waits on the network; its
        hand-in derives the tasks citing it."""
        if (url, version) in self._reading_pulls:
            return
        self._reading_pulls.add((url, version))
        threading.Thread(
            target=self._settle_mergeable, args=(url, version, repo, number), name="task-actor-mergeable", daemon=True
        ).start()

    def _settle_mergeable(self, url: str, version: tuple[str, str | None], repo: str, number: int) -> None:
        try:
            answer = self._mergeable(repo, number)
        except (
            Exception
        ) as error:  # a read that fails leaves the stored answer to stand, as a read that says nothing does
            logger.warning("task actor: cannot read whether %s merges: %s", url, error)
            answer = None

        def settle() -> None:
            self._reading_pulls.discard((url, version))
            self._settled[url] = (version, answer, self._clock())

        self._hand_in(url, "mergeable read", settle)

    def _own_prs(self, agent: dict[str, Any]) -> list[str]:
        return own_prs(self._store, agent, self._feed.keys)

    def _unlinked(self, agent: dict[str, Any]) -> list[str]:
        """The unlinked substate: open pull requests naming the task that it does not cite yet. The task stays in its lane
        while any exist, never parked; the write of its reference changes the task's record, which re-derives it."""
        return uncited(self._store, agent, self._feed.keys)

    def _pull_state(self, url: str) -> tuple[str, str | None, bool, str, str, str, str, int]:
        record = self._record(url)
        if record is None:
            return "", None, False, "", "", "", "", 0
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
            record["threads"],
        )

    def _heads(self, agent: dict[str, Any]) -> dict[str, str]:
        """The head of each own pull request of the task the store holds."""
        records = {url: self._record(url) for url in self._own_prs(agent)}
        return {url: record["headRefOid"] for url, record in records.items() if record}

    def _replies(self, agent: dict[str, Any]) -> int | None:
        """How many holder replies the task's comments already hold: the send-back holds the task until one more. None
        when the comments cannot be read, a baseline of no replies no one counted."""
        return None if (texts := self._comments(agent)) is None else derivation.replies(texts)

    def touch(self, events: Iterable[TaskTouched], observed: float | None = None) -> set[str]:
        """The one entry every trigger source derives through, under the lock: derive each task touched once, in name
        order but those a webhook touched citing a merged pull request first, as their move is the one a merge waits
        for. Say which tasks moved to another lane."""
        events = list(events)
        observed = self._clock() if observed is None else observed
        webhook = {each.task for each in events if each.trigger == Trigger.ON_WEBHOOK}

        def merged(name: str) -> bool:
            urls = self._seen[name][2] if name in webhook and name in self._seen else ()
            return any((record := self._record(url)) and record["state"] == "MERGED" for url in urls)

        names = sorted({each.task for each in events}, key=lambda name: (not merged(name), name))
        with self._metrics:
            for each in events:
                lane = self._seen.get(each.task, ("",))[0]
                self._touches[lane, each.cause if each.cause in _TOUCH_SOURCES else each.trigger.value] += 1
        with self._feed.pinned_rows():
            return {name for name in names if not self._waiting_unchanged(name) and self._derive(name, observed)}

    def _waiting_unchanged(self, name: str) -> bool:
        """Whether a Waiting task's facts digest to what it was last derived on, so touching it again has nothing to derive."""
        return self._seen.get(name, ("",))[0] == self._feed.roles.waiting and self._unchanged(name)

    @staticmethod
    def _webhooks(names: Iterable[str], cause: str) -> list[TaskTouched]:
        return [TaskTouched(name, Trigger.ON_WEBHOOK, cause) for name in names]

    @staticmethod
    def _dependency_touched(names: Iterable[str], cause: str) -> list[TaskTouched]:
        return [TaskTouched(name, Trigger.ON_SUBSTATE_CHANGE, cause) for name in names]

    def _derive(self, name: str, observed: float) -> bool:
        """Derive the task's waits, time the derivation, and note the facts it settled on for the checkpoint. Say whether
        it moved the task to another lane."""
        self._feed.repin()
        agent = self._feed.task(name, lean=True)
        if agent is None:
            return False
        if name in self._seen and self._seen[name][0] != agent["state"]:
            self._changed({"id": name, "agent": agent})  # its change event, still queued behind the lock's other work
            return False
        digest = self._digest(agent)
        self._hooked = self._unsettled = False
        started = self._clock()
        try:
            moved = self._derive_waits(name, agent, observed, digest)
        except Exception as error:
            moved = self._fault(agent, "derive", error)
        finally:
            self._hold_reads.pop(name, None)  # each derivation takes a read of its own
            self._timed_derive(agent["state"], self._hooked, self._clock() - started)
        self._feed.repin()
        self._settle_awaited(name)
        held = name in self._held and agent["state"] != self._feed.roles.waiting  # a Waiting hold is read at its digest
        if self._unsettled or held or name in self._pin_held:
            self._derived.pop(name, None)  # its hold or failure can end with no fact of the task changing
        else:
            self._derived[name] = digest
        self._derived_moved.set()
        return moved

    def _timed_derive(self, lane: str, hooked: bool, seconds: float) -> None:
        with self._metrics:
            histogram = self._derive_seconds.setdefault((lane, hooked), Histogram(SLOW_BUCKETS_S))
        histogram.observe(seconds)

    def _derive_waits(self, name: str, agent: dict[str, Any], observed: float, digest: str) -> bool:
        """Write the first move the task's lane waits on whose fact holds, and say whether one was written. A move already
        tried on these facts (`digest`), or one the board refuses, leaves the next fact its turn: a Waiting task whose
        return to Review is refused still reaches Ready, and a move skipped is tried again once the facts digest changes. A
        transient refusal ends the pass instead: its facts are stale, so a later fact (a closed pull request's ask) must
        not win over the change that raced it (an archive request)."""
        self.derivations[name] += 1
        self._arm(name, agent)
        frozen = agent.get("frozen")
        if agent["state"] in self._sweep_lanes and not frozen and (reasons := self._stuck(agent)):
            self._note_hold(agent, reasons, FLAGGED)
        waits = self._waits.get(agent["state"], {})
        if frozen:  # a frozen task keeps its lane: only a request to freeze it again or to lift the freeze is read
            waits = {fact: event for fact, event in waits.items() if fact in _FREEZES}
        if "overdue" in waits and derivation.entered(self._port, agent) and derivation.dead(self._port, agent):
            # a dead wait with a known entry (so a deadline) pre-empts a release it would block
            waits = {"overdue": waits["overdue"]}
        for fact, event in waits.items():
            target = self._moves.get((agent["state"], event))
            try:
                held = FACTS.get(fact, lambda *_: None)(self._port, agent)
                if held is not None and fact in _ASKS and self._answered(agent, held[1]):
                    continue
            except Exception as error:
                return self._fault(agent, f"fact {fact}", error)
            if held is None:
                continue
            if fact == "deps_unresolved" and target and self._feed.roles.outranks(agent["state"], target):
                continue  # the lane outranks the one the dependency leads to: the task stays where it is
            evidence, comment = held
            if fact == "move_requested":
                target = self._moves.get((agent["state"], f"{event}:{derivation.requested_lane(evidence)}"))
            if target is None or (self._is_closed(target) and event != "ARCHIVE"):
                return self._fault(agent, f"move {event}", self._no_move(agent["state"], event, target))
            sent = (agent["state"], event, evidence, digest)
            if self._tried.get(name) == sent:
                continue
            self._tried[name] = sent
            changes = derivation.stale(self._port, agent) if fact.startswith("deps_done") else {}
            if fact in _ASKS:
                changes = {"description": section_set(agent["description"], "Needs attention", comment)}
                if fact == "overdue" and derivation.dead(self._port, agent):
                    changes["dependencies"] = []  # a dead wait: the reason names them
            if target == agent["state"]:  # a stay: a ready pull request is enqueued, any other fact holds the lane
                if fact in _FREEZES:
                    self._freeze(agent, fact, evidence)
                if fact == "pr_ready":
                    self._notice(
                        self._enqueued,
                        name,
                        "was ready but its pull request was not enqueued",
                        on_failure=lambda: self._tried.pop(name, None),  # tried again on the next derivation
                    )
                return False
            merged = derivation.merged_at(self._port, agent) if fact in _MERGE_FACTS else None
            feedback = fact == "operator_pushback"
            if self._write(
                name, target, comment, observed, source=agent["state"], stale=changes, merged=merged, feedback=feedback
            ):
                if feedback and not self._wake_holder(name, "FEEDBACK", comment.removeprefix(derivation.SENT_BACK).strip()):
                    logger.warning("task actor: the log refused the feedback wake of %s: its holder was not told", name)
                return True
            if self._tried.get(name) != sent:
                return False  # the file changed under a transient refusal: the next pass judges it anew, no later fact
        if agent["state"] == self._feed.roles.working:
            self._log_unready(agent)
            self._wake_uncited(name, agent)
        return False

    def _wake_uncited(self, name: str, agent: dict[str, Any]) -> None:
        """Wake the holder once per head and verdict when the checks settle on an open pull request that names the task
        and that it does not cite: the holder's topics come from cited pull requests, so no other event reaches it."""
        if self._own_prs(agent):
            return
        for url in self._unlinked(agent):
            if (record := self._record(url)) is None:
                continue
            verdict = checks_verdict(
                record["state"], record["checks"], record["headRefOid"], record["rollup"], record["requiredChecks"]
            )
            woken = f"{url}@{record['headRefOid']}:{verdict}"
            if verdict == "pending" or woken in (self._memory.of(name).get("uncited_woken") or ()):
                continue
            head, number = record["headRefOid"][:12], record["number"]
            reason = (
                f"Checks {'passed' if verdict == 'pass' else verdict} on pull request #{number} at {head}, which the "
                f"task does not cite: rerun deliver, which cites it and readies it"
            )
            if self._wake_holder(name, UNCITED_CHECKS, reason):
                self._memory.keep(name, uncited_woken=[woken])

    def _freeze(self, agent: dict[str, Any], fact: str, request: str) -> None:
        """Carry out a request to freeze the task or to lift its freeze, or answer it with one comment when the freeze or
        its requester forbids it. Freezing is open to the operator and any agent; lifting it to the operator and the
        requester the freeze names."""
        name, frozen = agent["id"], agent.get("frozen") or {}
        freezing = fact == "freeze_requested"
        who = requested_by(request) or "unknown"
        reason = request_reason(request, FREEZE_REQUEST if freezing else UNFREEZE_REQUEST)
        changes: dict[str, Any] = {}
        if freezing and frozen:
            text = f"Freeze refused: {name} is already frozen by {frozen['by']}: {frozen['reason']}."
        elif freezing:
            at = datetime.fromtimestamp(self._wall(), _FREEZE_ZONE).strftime("%Y-%m-%d %H:%M")
            changes = {"frozen": {"by": who, "at": at, "reason": reason}}
            text = f"Frozen by {who}: {reason}"
        elif not frozen:
            text = f"Unfreeze refused: {name} is not frozen."
        elif who not in (OPERATOR, frozen["by"]):
            text = f"Unfreeze refused: {name} is frozen by {frozen['by']}, and only they or the operator can lift it."
        else:
            changes = {"frozen": {}}
            text = f"Unfrozen by {who}: lifted the freeze by {frozen['by']}: {frozen['reason']}"
        written = self._apply(name, changes, text)
        if not written.ok:
            logger.warning("task actor: the %s of %s was not written: %s", fact, name, written.output)
            self._refused_by(written)
        elif changes:
            self._notice(self._frozen, name, "was written but the board was not told")

    def _log_unready(self, agent: dict[str, Any]) -> None:
        """Log once per change the condition that keeps a working task's open pull request from being ready."""
        reasons = derivation.unready(self._port, agent)
        if reasons is None:
            self._unready_logged.pop(agent["id"], None)
            return
        if self._unready_logged.get(agent["id"]) == reasons:
            return
        self._unready_logged[agent["id"]] = reasons
        logger.info("task actor: %s has a pull request that is not ready: %s", agent["id"], reasons)

    def working(self) -> list[str]:
        """The open tasks in the working or attention lane, whose holders `follow_holder_idle` checks for a settle or an end
        while down."""
        roles = self._feed.roles
        with self._lock:
            return [
                agent["id"] for agent in self._feed.open_tasks() if agent["state"] in (roles.working, roles.attention)
            ]

    def closed(self) -> list[str]:
        """The open tasks in an `end_lanes` lane but Ready, whose holders `follow_holder_idle` checks for a settle while down,
        so a move into the lane that the actor missed still ends the session."""
        ready = self._feed.roles.ready
        with self._lock:
            return [
                agent["id"]
                for agent in self._feed.open_tasks()
                if agent["state"] in self._end_lanes and agent["state"] != ready
            ]

    def unstarted(self) -> list[str]:
        """The open tasks in the ready lane, whose dispatch `follow_holder_idle` replays when the actor was down for it."""
        roles = self._feed.roles
        with self._lock:
            return [agent["id"] for agent in self._feed.open_tasks() if agent["state"] == roles.ready]

    def holder_settled(self, name: str, wait_ended: bool = False) -> None:
        """A session settled. A holder whose task has an open criterion (neither checked nor struck through) is nudged by
        `_nudge`, pull request or not. Any other In Progress task, a no-pull-request one included, whose holder is not busy (`confirm`) and that no event is awaited on
        has work left, so the `idle` hook nudges the same session with its phase machine's next step; the task stays In
        Progress and no clock runs. A settle an awaited event held runs again from the derivation that finds the wait
        ended, as the session that settled may never settle again, unless its holder is at work by then (a lens's end woke it): that
        holder settles anew. The one nudge is the only one: a settle after it with no progress (a phase or
        submachine event, a new head) moves the task to Needs attention with its session kept and its profile unchanged,
        except a settle that an ended wait on checks or an awaited machine queued, which resets the count. A task whose own pull requests have all ended is never nudged: it moves to Needs attention at once when no lifecycle rule
        takes it (a reopened task's earlier merge), freeing its session slot. A task citing none of its own while an open pull request names it (the `_unlinked` substate) is left as it is, neither nudged nor sent to Needs attention: deliver cites the pull request, and that write re-derives the task. A `confirm` that
        raises (the holder is busy) holds the task: the next move of a machine other than the harness settles it again, and the
        session's own activity ends the hold. A `nudge` that fails moves the task to Needs attention with the reason, as a
        holder whose nudge was lost settles no more; a holder no session can reach is resumed once as `holder_ended`
        resumes one."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            self._memory.keep(name, awaited=None, resume_held=None, unreachable=None, busy=None)
            if agent is None or agent["state"] != self._feed.roles.working:
                self._memory.keep(name, resumes=None)
                self._unwant(name)
                self._end_closed(name)
                return
            if self._idle is None:
                return
            if wait_ended and self._session_active(name):
                self._memory.keep(name, resumes=None)
                return
            if self._awaits(agent):
                self._memory.keep(name, awaited=True)
                return
            self._settling = name
            try:
                moved = self.touch([TaskTouched(name, Trigger.ON_IDLE, "session settled")])
            finally:
                self._settling = ""
            if moved:
                return  # the lane facts moved the task (a ready pull request to Review): there is nothing to resume
            answered = "kind-decide" in agent["labels"] and operator_answered(
                (self._feed.task(name) or {}).get("description", "")
            )
            own = self._own_prs(agent)
            if not own and self._unlinked(agent):
                return  # the delivery is open and the merge reconcile cites it: no input of the operator's is missing
            records = [self._record(url) for url in own]
            if own and all(record and record["state"] in TERMINAL for record in records):
                # a merge GitHub has not timed yet settles on its next read; else no lifecycle rule takes the task
                if derivation.pr_terminal(self._port, agent) is None and all(
                    record["mergedAt"] or record["state"] != "MERGED" for record in records
                ):
                    self._attend(
                        name,
                        "every pull request it cites has ended, yet none proves the work since it entered In Progress",
                        "settled with no pull request left to deliver",
                        "Which?",
                        ("deliver the reopened work on a new pull request", "close the task as done"),
                    )
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
        if answered and not opened:
            return  # the answer ends a decide task whose criteria are all met; one left is execute work to resume
        if opened:
            self._nudge(name, opened, ticks, wait_ended)
        else:
            self._nudge_step(name, progress, count)

    def lane_entered(self, name: str, lane: str) -> None:
        """A task entered `lane`: its holder's session ends when the lane is one of `end_lanes`, which the reaper does once
        the session is idle; a session busy now is ended by `holder_settled` when it settles."""
        if lane in self._end_lanes:
            self._end_session(name, lane)

    def _end_closed(self, name: str) -> None:
        """A holder of `name` settled or ended while the task sits in a closed lane: end its session."""
        if derivation.closed_lane(self._port, name, self._end_lanes):
            self._end_session(name)

    def _end_session(self, name: str, lane: str = "") -> None:
        """Run the end hook, given the lane the move entered so a reap that cannot read it ends the session all the same."""
        end = self._end
        if end is None:
            return

        def run() -> None:
            try:
                end(name, lane)
            except Exception:
                logger.exception("task actor: %s's closed-lane end failed", name)

        self._queue(run)

    def holder_entered(self, name: str) -> None:
        """A task moved from a parked lane to In Progress settles like an idle holder, except after the operator's answer:
        its claim told the holder through the task topic, and a resume on top costs the answering session a turn."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            texts = self._comments(agent) if agent else None
        if texts and ANSWER_COMMENT.match(texts[-1]):
            return
        self.holder_settled(name)

    def holder_ended(self, name: str, wait_ended: bool = False, unreachable: bool = False) -> None:
        """A task has no live session. A task in Needs attention, whose session the operator's answer waits on, is resumed
        once whatever work is left, and stays there, a failed resume included. A holder whose task still has work (an open
        criterion, or a pull request of its own not yet ended) is resumed once by the `idle` hook's `resume` verdict,
        the session-start service's one start (a transcript to reopen is resumed, none starts fresh), which moves the
        claim to the session; the task stays In Progress. The next loss with no progress (a criterion checked, a phase or
        head change) moves the task to Needs attention with its session kept, as does a resume that fails, naming why.
        An awaited event holds the resume until it ends. A task with no work left is the settle's (`holder_settled`),
        and a held resume whose holder is at work again by the time the wait ends is dropped. A nudge that reached no
        session (`unreachable`) resumes a task with no work left too: the settle has no one to nudge, and no later event
        comes."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            unreachable = unreachable or self._memory.has(name, "unreachable")  # a deferred resume keeps its reason
            self._memory.keep(name, resume_held=None, unreachable=None)
            roles = self._feed.roles
            parked = agent is not None and agent["state"] == roles.attention
            if agent is None or agent["state"] not in (roles.working, roles.attention):
                self._end_closed(name)
                self._unwant(name)
                return
            if self._idle is None:
                self._unwant(name)
                return
            if wait_ended and self._session_active(name):
                return
            items = agent.get("criteria", ())
            opened = open_criteria(items)
            if not parked:
                if not agent["prs"] and not opened and not unreachable:
                    return
                own = self._own_prs(agent)
                if (
                    agent["prs"]
                    and own
                    and all((record := self._record(url)) and record["state"] in TERMINAL for url in own)
                ):
                    return
                if self._awaits(agent):
                    logger.info("task actor: %s has no live session and its resume waits for an awaited event", name)
                    self._memory.keep(name, awaited=True, resume_held=True, unreachable=True if unreachable else None)
                    return
            held = ("parked", self._progress(agent))  # the one resume a task gets in Needs attention, counted apart
            key = (
                held
                if parked
                else (tuple(resolved(item) for item in items), self._progress(agent))
                if opened
                else self._progress(agent)
            )
            _, count = self._memory.resumes(name, key)
            if count >= _ONE_TRY:
                if parked:
                    return
                self._memory.keep(name, resumes=None)
                self._attend(
                    name,
                    "its session ended again after its one resume with no progress",
                    "keeps ending",
                    "Which?",
                )
                return
        if not self._admitted(name, "resume"):
            logger.info("task actor: %s has no live session and its resume waits for the scheduler's admission", name)
            if unreachable:
                with self._lock:
                    self._memory.keep(name, unreachable=True)
            return
        try:
            self._idle(name, "resume")
        except Exception as error:
            self._unwant(name)
            logger.warning("task actor: %s has no live session and could not be resumed: %s", name, error)
            with self._lock:
                now = self._feed.task(name, lean=True)
                if now and now["state"] == self._feed.roles.working:  # a parked task is already with the operator
                    self._attend(
                        name,
                        f"no session can start for it: {error}",
                        "could not be resumed",
                        "Start one by hand or rescope?",
                        ("start a session on it by hand", "rescope the task"),
                    )
            return
        self._unwant(name)
        with self._lock:
            self._memory.count(name, key, count + 1)
        self._deadlines.arm(_STARTED + name, self._wall() + _START_BOUND_S)

    def dispatched(self, name: str, session: str) -> None:
        """A session was dispatched to `name`: pin it as the task's holder, and move a Ready task, or a Needs attention one
        the operator answered, to In Progress. A task another session holds keeps that holder, since its lease ends only
        with its own session (`session_ended`)."""

        with self._lock:
            agent = self._feed.task(name, lean=True)
            roles = self._feed.roles
            if agent is None or not session or agent["state"] not in (roles.ready, roles.attention, roles.working):
                return
            holder = str((self._read(name) or {}).get("assignee") or "")
            if holder and not same_holder(holder, session):
                logger.info(
                    "task actor: %s stays with %s, which a dispatch of %s did not displace", name, holder, session
                )
                return
            self._deadlines.arm(_STARTED + name, self._wall() + _START_BOUND_S)
            moving = agent["state"] != roles.working
            if holder and not moving:
                return
            changes = {"status": roles.working, "assignee": session} if moving else {"assignee": session}
            comment = f"Dispatched: {session} holds it."
            refusal = self._judged(name, changes, comment) if moving else Written(True, name)
            self._dispatching[name] = session
            written = (
                refusal
                if not refusal.ok
                else self._apply(name, changes, comment, again=lambda: self._redispatch(name, session), session=session)
            )
            if not (written.transient and name in self._lock_tries):
                self._dispatching.pop(name, None)
        if not written.ok:
            logger.warning("task actor: a dispatch of %s to %s was not pinned: %s", session, name, written.output)

    def _redispatch(self, name: str, session: str) -> None:
        """The retry of a dispatch whose write the board refused as locked: it runs again from the task and session as they
        stand, and not at all once the session ended."""
        with self._lock:
            if self._dispatching.get(name) == session:
                self.dispatched(name, session)

    def session_ended(self, name: str, session: str) -> None:
        """The harness ended `session`: the lease of `name` it holds ends, and the task keeps its lane, since started work
        never returns to Ready."""

        with self._lock:
            if self._dispatching.get(name) == session:
                del self._dispatching[name]
            holder = str((self._read(name) or {}).get("assignee") or "")
            if not same_holder(holder, session):
                return
            written = self._apply(name, {"assignee": ""}, "", again=lambda: self.session_ended(name, session))
        if not written.ok:
            logger.warning("task actor: the lease of %s on %s was not ended: %s", session, name, written.output)

    def start_failed(self, only: str = "") -> None:
        """The scheduler could not start a Ready task: park it in Needs attention with the reason, then take the failure
        back. A task that left Ready meanwhile keeps its lane. A retry after a locked board names its `only` task, so a
        lock that persists never multiplies the scan's timers."""
        if self._log is None:
            return
        for name, reason in start_requests.failed(self._log).items():
            if only and name != only:
                continue
            with self._lock:
                agent = self._feed.task(name, lean=True)
                if (
                    agent is not None
                    and agent["state"] == self._feed.roles.ready
                    and not self._attend(
                        name,
                        reason,
                        "could not be started",
                        "Start a session on it?",
                        ("start it by hand", "rescope the task"),
                        again=lambda name=name: self.start_failed(name),
                    )
                ):
                    # the backoffs ran out with no timer armed: a lock that long retries
                    if name not in self._lock_tries:
                        _later(max(LOCK_BACKOFF_S, default=0.0), self.start_failed, name)
                    continue  # the failure stays until the retry parks the task
            start_requests.forgive(self._log, name)

    def _admitted(self, name: str, verb: str) -> bool:
        """Whether the scheduler's admission gate lets `name`'s `verb` start now. A start it has not yet admitted is kept as
        a want, and the gate's admit wakes `admitted`, so a refused start waits for room and no clock retries it."""
        if self._log is None or start_requests.is_admitted(self._log, name, verb):
            return True
        start_requests.want(self._log, name, verb)
        return False

    def _unwant(self, name: str) -> None:
        if self._log is not None:
            start_requests.withdraw(self._log, name)

    def admitted(self) -> None:
        """The gate admitted a start: send each wanted one it has admitted, the resume from `holder_ended` and the nudge
        from `holder_settled`, which derive again whether it is still needed. An admission that sends nothing (the work
        is gone) is spent, so its want goes."""
        if self._log is None:
            return
        for name, row in start_requests.wanted(self._log).items():
            if start_requests.is_admitted(self._log, name, row["verb"]):
                self._queue(lambda name=name, row=row: self._start_admitted(name, row))

    def _start_admitted(self, name: str, row: dict[str, Any]) -> None:
        if self._log is None or start_requests.wanted(self._log).get(name) != row:
            return  # withdrawn or replaced while the admission was queued: it no longer asks for this start
        if row["verb"] == "resume":
            self.holder_ended(name)
        else:
            self.holder_settled(name)
        if start_requests.wanted(self._log).get(name) == row:
            self._unwant(name)

    def _nudge_step(self, name: str, progress: tuple[Any, ...], count: int) -> None:
        if not self._confirmed(name):
            return
        refusal = self._refused.get(name)
        if refusal and count >= _ONE_TRY:
            return  # the holder was told the refusal; the task stays In Progress until a change repairs it
        if count >= _ONE_TRY:
            with self._lock:
                now = self._feed.task(name, lean=True)
                if now and now["state"] == self._feed.roles.working:
                    self._memory.keep(name, resumes=None)
                    self._attend(name, "it settled idle again after its one nudge with no progress")
            return
        if refusal:
            latest = (self._comments({"id": name}) or [""])[-1].strip()
            if latest != refusal:
                self._apply(name, {}, refusal)  # the nudge reads the latest comment: make the refusal the latest
        if not self._nudge_sent(name):
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
                if isinstance(error, HolderInGrace):  # no event ends the grace: its end is the deadline's
                    self._deadlines.arm(_GRACE + name, self._wall() + _GRACE_S)
            return False
        with self._lock:
            return not self._session_active(name)  # a settle read after the session woke again: its next settle comes

    def _nudge_sent(self, name: str) -> bool:
        """Send the holder's nudge, once: one that fails is the holder's loss, which `_nudge_failed` answers, since a
        holder whose nudge was lost settles no more and no later settle comes; a timeout is wanted again, not lost."""
        if not self._admitted(name, "nudge"):
            return False
        try:
            self._idle(name, "nudge")
        except subprocess.TimeoutExpired as error:  # the board is restarting: ask the gate again, never park
            logger.info("task actor: %s settled but its holder's nudge timed out: %s", name, error)
            if self._log is None:
                self._nudge_failed(name, error)
            else:
                self._unwant(name)
                start_requests.want(self._log, name, "nudge")
            return False
        except Exception as error:
            logger.info("task actor: %s settled but its holder was not nudged: %s", name, error)
            self._nudge_failed(name, error)
            return False
        self._unwant(name)
        return True

    def _nudge(self, name: str, opened: list[tuple[int, str]], ticks: tuple[bool, ...], wait_ended: bool) -> None:
        """Nudge an idle holder whose criteria are open; its hook's message names them. The `_NUDGES + 1`th idle with no
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
        if not self._nudge_sent(name):
            return
        with self._lock:
            self._memory.count(name, ticks, count + 1)

    def _nudge_failed(self, name: str, error: Exception) -> None:
        """A holder no session can reach is resumed once, as `holder_ended` resumes one, which parks the task only when no
        session can start; any other failure parks it with the reason; a task no longer In Progress needs neither."""
        with self._lock:
            agent = self._feed.task(name, lean=True)
            if agent is None or agent["state"] != self._feed.roles.working:
                return
            if not isinstance(error, HolderUnreachable):
                self._attend(name, f"its holder's nudge failed: {error}", "could not be nudged")
                return
        self.holder_ended(name, unreachable=True)

    def _attend(
        self,
        name: str,
        why: str,
        what: str = "was resumed with no progress",
        ask: str = "Which?",
        options: Sequence[str] = ("resume it by hand", "rescope the task"),
        again: Callable[[], None] | None = None,
    ) -> bool:
        """Park `name` in Needs attention; False only when the board's lock held the write up and `again` will run."""
        agent = self._feed.task(name, lean=True)
        attention = self._feed.roles.attention
        if agent is None or attention is None:
            return True
        conflicting = derivation.pr_conflicting(self._port, agent)
        reason = attention_reason(
            f"{name} {what}",
            why,
            options,
            f"{conflicting[1]} Rebase it on origin/main first. {ask}" if conflicting else ask,
        )
        written = self._apply(
            name,
            {"status": attention, "description": section_set(agent["description"], "Needs attention", reason)},
            reason,
            again=again,
        )
        return not written.transient

    def _settle_busy(self, data: dict[str, Any]) -> None:
        name = data["id"]
        if not self._memory.has(name, "busy"):
            return
        if data.get("machine") != HARNESS_MACHINE:
            self._memory.keep(name, busy=None)
            self._queue(lambda: self.holder_settled(name))
        elif (data.get("agent") or {}).get("state") == "active":  # the session works again, so a settle will follow
            self._memory.keep(name, busy=None)

    def _settle_graced(self, name: str) -> None:
        if self._memory.has(name, "busy"):
            self._memory.keep(name, busy=None)
            self._queue(lambda: self.holder_settled(name))

    def _settle_awaited(self, name: str) -> None:
        memory = self._memory.of(name)
        if "awaited" not in memory:
            return
        agent = self._feed.task(name, lean=True)
        if agent is None:
            self._memory.keep(name, awaited=None)
        elif not self._awaits(agent):
            self._memory.keep(name, awaited=None)
            if "resume_held" in memory:
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
        fail or merge), a pull request of its own the store holds no record of yet (the record landing), a task citing
        none whose deliver machine opened its pull request (the cite or the record landing), or an unfinished
        placement in an awaited machine (`awaits`): a lens a link of the phase it is in runs, until its exit state (a
        placement left while the task is in no such phase holds nothing), else a machine no link names, until a final
        state."""
        name = agent["id"]
        own = self._own_prs(agent)
        for url in own:
            state, _, _, _, mergeable, checks, _, _ = self._pull_state(url)
            if not state or state == "OPEN" and checks == "pending" and mergeable != "CONFLICTING":
                return True  # no state: the pulls consumer lags the delivery; a conflicting head runs no checks
        delivery = self._feed.machine_task("deliver", name)
        if not own and delivery and delivery["state"] in _DELIVERED:  # its cite and record lag
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
            return self._texts(agent)
        except Exception as error:
            logger.warning("task actor: cannot read the comments of %s: %s", agent["id"], error)
            return None

    def _texts(self, agent: dict[str, Any]) -> list[str]:
        comments = (self._read(agent["id"]) or {}).get("comments") or []
        return [str(comment.get("text") or "") for comment in comments]

    def _answered(self, agent: dict[str, Any], ask: str) -> bool:
        """Whether the operator already answered this very ask: an `Operator answer` comment follows the last time the
        task carried `ask`, so parking the task on it again would put the question to them twice. A new ask (another
        pull request, another reason) is a new question."""
        texts = self._texts(agent)
        asked = [index for index, text in enumerate(texts) if text.strip() == ask.strip()]
        return bool(asked) and any(ANSWER_COMMENT.match(text) for text in texts[asked[-1] + 1 :])

    def _write(
        self,
        name: str,
        target: str,
        comment: str,
        observed: float,
        source: str,
        stale: Mapping[str, Any] = {},
        merged: float | None = None,
        feedback: bool = False,
    ) -> bool:
        changes = {"status": target, **stale}
        refusal = self._judged(name, changes, comment)
        if feedback and refusal.ok:
            if (replied := self._replies({"id": name})) is None:
                self._tried.pop(name, None)  # no baseline, no send-back: judged anew on the next pass
                return False
            self._memory.keep(name, sent_back=replied)  # before the move, so a reply sent after it is a new one
        begun = self._clock()
        written = refusal if not refusal.ok else self._apply(name, changes, comment, refusal.version)
        if feedback and not written.ok:
            self._memory.keep(name, sent_back=None)
        if merged is not None and self._received is not None and refusal.ok:
            self._merge_board_write.observe(self._clock() - begun)
        if written.ok and self._recovering:
            logger.error(
                "task actor: start recovery moved %s %s -> %s, a move its lane's events missed", name, source, target
            )
        if written.ok:
            if target == self._review:
                self._refused.pop(name, None)  # the refusal is repaired: a send-back must not resume on it
            if source == self._review and target == self._feed.roles.working and not feedback:
                self._memory.keep(name, own_send_back=True)
            self._landed(self._clock() - observed)
            if merged is not None:  # timed at the lane write, ahead of the hooks that tell the board and the holder
                self._merge_move.observe(max(0.0, self._wall() - merged))
                if self._received is not None:
                    self._receipt_done.observe(max(0.0, self._wall() - self._received))
            roles = self._feed.roles
            if source == roles.working and target == roles.waiting:
                self._notice(self._tell, name, "was parked but its holder was not told")
            if source == roles.waiting and (heard_at := self._heard_at.pop(name, None)) is not None:
                lag = max(0.0, self._wall() - heard_at)
                self._park_release.observe(lag)
                logger.info("task actor: %s released to %s %.1f s after its event", name, target, lag)
            if source == roles.waiting and target == roles.working:
                self._released_visit.add(name)
            if source == roles.waiting and target in (roles.ready, roles.review, roles.working):
                self._notice(
                    self._released,
                    name,
                    "was released but its holder was not told",
                    on_failure=(lambda: self._attend_unstarted(name)) if target == roles.working else None,
                )
            if target == roles.working and source != roles.waiting:  # a Waiting holder hibernated: it needs a start
                self._notice(
                    self._returned,
                    name,
                    "was sent back but its holder was not told",
                    on_failure=lambda: self.holder_ended(name, unreachable=True),
                )
            if target == roles.done:
                self._notice(self._closed, name, "was closed but the board was not told")
            if self._is_closed(target):
                self._notice(self._archived, name, "was archived but the board was not told")
            return True
        logger.warning("task actor: %s was not moved to %s: %s", name, target, written.output)
        moved = False
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
        elif target == self._review and source in (self._feed.roles.working, self._feed.roles.attention):
            self._hold_review(name, written.output)
        elif not written.lint and target != self._moves.get((source, "ACTOR_FAULT")):
            faulted = self._feed.task(name, lean=True)
            moved = faulted is not None and self._fault(faulted, f"move {source} to {target}", written.output)
        self._refused_by(written)
        return moved

    def _refused_by(self, written: Written) -> None:
        with self._metrics:
            self._refusals[written.rule or OTHER_REFUSAL] += 1

    def _is_closed(self, target: str) -> bool:
        roles = self._feed.roles
        return roles.roles.get(target) == "final" and target != roles.done

    def _no_move(self, lane: str, event: str, target: str | None) -> str:
        return (
            f"{lane} has no move for {event}" if target is None else f"{event} moves {lane} to {target}, a closed lane"
        )

    def _fault(self, agent: dict[str, Any], step: str, error: object) -> bool:
        """Park the task in Needs attention through `ACTOR_FAULT`, naming the failed `step` and `error` as its reason, and
        say whether it moved. A task already there keeps its lane and gets the reason ahead of its earlier text. A fault
        is written once: not again on another trigger, and a board write of it that fails is logged and counted only."""
        name, lane = agent["id"], agent["state"]
        reason = f"{FAULT} {step}: {error}"
        dependencies = tuple(agent.get("dependencies", ()))
        if dependencies:  # a fault drops the wait: the reason names them
            reason += f" (was waiting on {', '.join(dependencies)})"
        if self._faults.get(name) == (lane, reason):
            return False
        self._faults[name] = (lane, reason)
        logger.error("task actor: fault on %s at %s: %s", name, step, error)
        target = self._moves.get((lane, "ACTOR_FAULT"))
        if target is None:
            return False
        kept = needs_attention_text(agent["description"])
        if kept.startswith(FAULT):  # an earlier fault and its next step are replaced, the operator's ask under it stays
            kept = kept.partition("\n")[2].partition("\n")[2].strip()
        text = "\n\n".join(filter(None, (f"{reason}\n{FAULT_NEXT}", kept)))
        changes: dict[str, Any] = {"description": section_set(agent["description"], "Needs attention", text)}
        if target != lane:
            changes["status"] = target
            if dependencies:
                changes["dependencies"] = []
        written = self._apply(name, changes, reason)
        if not written.ok:
            logger.warning("task actor: the fault of %s was not written: %s", name, written.output)
            self._refused_by(written)
            return False
        if target != lane:
            self._faults.pop(name, None)
        return target != lane

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
        self._refused[name] = note
        if note in self._comment_texts(name):
            return
        if not self._wake_holder(name, "REVIEW_REFUSED", reason):
            return  # the wake and the note are both tried again on the next change
        written = self._apply(name, {}, note)
        if not written.ok:
            logger.warning("task actor: the Review refusal of %s was not commented: %s", name, written.output)

    def _comment_texts(self, name: str) -> set[str]:
        try:
            comments = (self._read(name) or {}).get("comments") or []
        except Exception as error:  # an unread board comments again, which a repeat costs less than a lost refusal
            logger.warning("task actor: cannot read the comments of %s: %s", name, error)
            return set()
        return {str(comment.get("text") or "").strip() for comment in comments}

    def _wake_holder(self, name: str, event: str, reason: str) -> bool:
        """Publish `event` on the task's topic, which the holder's consumer carries (`task.<id>.review_refused`); False
        when the log refused it."""
        if self._log is None:
            return True
        return (
            machine_events.publish(IN_PROGRESS, event, actor=ACTOR, task=name, data={"reason": reason}, log=self._log)
            is not None
        )

    def _attend_unstarted(self, name: str) -> None:
        with self._lock:
            agent = self._feed.task(name, lean=True)
            if agent is None or agent["state"] != self._feed.roles.working or name not in self._released_visit:
                return
            self._attend(
                name,
                "no session could be started for it",
                "left Waiting but no session started",
                "Start a session on it?",
                ("start it by hand", "rescope the task"),
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
        self._reads.put(None)

    def _holds_of(self, name: str) -> tuple[str, ...] | None:
        """The reasons the board withholds the task's `deps_done`, as its hook printed them for the task's present facts;
        None while that read runs off the lock, whose result derives the task again. Each derivation takes a read of its
        own, as the hook reads more than the facts digest, and every hold fact of that derivation shares it."""
        agent = self._feed.task(name, lean=True)
        if self._holds is _no_holds or agent is None:
            return self._read_holds(name)[0]
        digest = self._digest(agent)
        found = self._hold_reads.get(name)  # kept to the derivation's end: its other hold facts read the same result
        if found and found[0] == digest:
            self._unsettled |= found[2]
            return found[1]
        self._unsettled = True
        if name not in self._reading:
            self._reading.add(name)
            self._reads.put((name, digest))
            if self._reader is None:
                self._reader = threading.Thread(target=self._read_holds_off_lock, name="task-actor-holds", daemon=True)
                self._reader.start()
        return None

    def _read_holds(self, name: str) -> tuple[tuple[str, ...], bool]:
        """The hook's reasons, and whether it failed: a failure holds the task with its error."""
        try:
            return tuple(self._holds(name)), False
        except Exception as error:
            logger.warning("task actor: cannot read the holds of %s: %s", name, error)
            return (f"the board's holds cannot be read: {error}",), True

    def _read_holds_off_lock(self) -> None:
        while (read := self._reads.get()) is not None:
            name, digest = read
            reasons, failed = self._read_holds(name)
            try:
                with self._pressing(), self._lock:
                    self._reading.discard(name)
                    if not self._noticing_ended:  # a move made after the notices close would miss its hook
                        self._hold_reads[name] = (digest, reasons, failed)
                        self._unsettle((name,))  # a read someone asked for is derived once, settled facts or not
                        self.touch([TaskTouched(name, Trigger.ON_ALERT, "holds read")])
            except Exception:  # touch derives under the lock and may raise; a dead reader is never restarted
                logger.exception("task actor: cannot derive %s on its holds", name)

    def _apply(
        self,
        name: str,
        changes: Mapping[str, Any],
        comment: str,
        over: str = "",
        again: Callable[[], None] | None = None,
        session: str = "",
    ) -> Written:
        # the board-files pass finds the lane recorded under the actor; no other task's write holds this one up
        with self._feed.recording_of(name):
            written = self._edit_retrying(name, changes, comment, over, again)
            if written.ok and written.lane:
                self._feed.record_written(name, written.lane, written.at or time.time(), (ACTOR, session, ""))
        return written

    def _judged(self, name: str, changes: Mapping[str, Any], comment: str) -> Written:
        try:
            return self._judge(name, changes, comment)
        except Exception as error:  # a board that raises refuses like one that answers no
            return Written(False, str(error))

    def _edit_retrying(
        self,
        name: str,
        changes: Mapping[str, Any],
        comment: str,
        over: str = "",
        again: Callable[[], None] | None = None,
    ) -> Written:
        """The board's edit; while SQLite reports the database locked, its next try waits off the actor lock (a timer
        runs `again`, the operation that failed, or derives the task again when lane facts rebuild it, after each of
        `LOCK_BACKOFF_S`), and a lock that outlasts them is `transient`, a failure of
        the database and no refusal of the change."""
        try:
            written = self._edit(name, changes, comment, actor=ACTOR, over=over)
        except Exception as error:  # a board that raises refuses like one that answers no
            if "database is locked" not in str(error):
                self._lock_tries.pop(name, None)
                return Written(False, str(error))
            tries = self._lock_tries.get(name, 0)
            self._lock_tries[name] = tries + 1
            if tries < len(LOCK_BACKOFF_S):
                _later(LOCK_BACKOFF_S[tries], again or self._derive_overdue, *(() if again else (name,)))
            else:
                self._lock_tries.pop(name, None)
            return Written(False, str(error), transient=True)
        self._lock_tries.pop(name, None)
        return written

    def _landed(self, seconds: float) -> None:
        with self._metrics:
            at = next((i for i, bound in enumerate(BUCKETS_S) if seconds <= bound), len(BUCKETS_S))
            for i in range(at, len(self._buckets)):
                self._buckets[i] += 1
            self._sum += seconds

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
            self._refused_by(written)

    def _arm(self, name: str, agent: dict[str, Any]) -> None:
        """Arm the deadline wait of a task in a lane that waits on `overdue`, when its deadline is still ahead; drop it
        from the wait otherwise. Every derivation re-arms, so a re-park, a new `expect_by` or a dependency's lane
        change moves the deadline."""
        self._deadlines.cancel(name)
        if agent["state"] != self._feed.roles.working:
            self._deadlines.cancel(_STARTED + name)  # a resume's start bound ends with its working visit
        if agent["state"] not in self._timed_lanes:
            self._dates.pop(name, None)
            return
        self._dates[name] = tuple(criteria.expect_dates(agent["description"]))
        deadline = derivation.deadline(self._port, agent)
        if deadline and deadline[0] > self._wall():
            self._deadlines.arm(name, deadline[0])

    def _owns_failure(self, task_id: str) -> bool:
        if not (self._owner_source and self._main_green):
            return False
        return str((self._read(task_id) or {}).get("source") or "").startswith(self._owner_source)
