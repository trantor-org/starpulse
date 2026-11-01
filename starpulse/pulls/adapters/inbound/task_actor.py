"""The task actor: a task advances itself on the facts its lane waits on.

A machine state's `waits` name a fact kind and the event that leaves the state when the fact holds
(`machine_definition.WAIT_FACTS`). The actor keeps a `PR -> tasks` and a `task -> dependents` index, so one change
touches only the tasks naming it, and when a task's pull request state, its own lane or a dependency's changes it
re-derives that task's waits and writes the first that holds through the board's task editor as `starpulse/task-actor`.
The board's rules and the machine's guards judge the write like any other. A write the board refuses is logged and
counted, and not tried again until the task's facts change. A release to Ready that the board's lint refuses (a
declared guard or the validate hook) leaves the task in its lane with the lint's reason as a comment and no operator
question, and the release is tried again when the task's description, profile, labels or dependencies change; any
other refused release parks the task in Needs attention with the refusal as its reason, once per refusal. A start
re-derives every open task once, which is the recovery for a change that happened while the server was down.

A lifecycle machine whose phase state links a skill machine with `exits` (`submachines[].exits`) advances that phase
too: when the skill machine reaches an exit state the actor calls `advance(machine, task, event)` with the exit's event,
once per visit to the phase, and only for the skill machine the task's current phase links. A link that lists `routes`
(phase state to event) sends instead the event for the phase that follows it in the `sequences` entry of the task's
type (`default` for a type it does not name), when one is listed; the exit's own event serves every other sequence.

A task whose lane waits on its Start Criteria is evaluated on a thread of its own when it has no result or its result is
older than `fresh_s`, and re-derived when the result changes; a criterion that cannot be evaluated is exported, not
retried before then. The board adapter may hold a task's `deps_done` with reasons, written once as a comment; a task
created re-derives every held task.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import UTC, datetime
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from starpulse.board import criteria
from starpulse.board.board_feed import BoardFeed
from starpulse.board.model.markdown import section_set
from starpulse.board.model.seam import HELD, MERGE_EVIDENCE, TaskCreator, TaskEditor, TaskReader, Written
from starpulse.pulls.adapters.inbound.unblock import PinGate
from starpulse.pulls.adapters.outbound.pull_requests import landed, own_prs, pull_record
from starpulse.pulls.model.pins import LiveBuild, Pins, Repo

if TYPE_CHECKING:  # annotation only: the pull store opens the database stack
    from starpulse.pulls.adapters.outbound.pulls import PullStore

logger = logging.getLogger(__name__)

__all__ = ["ACTOR", "LINT_REFUSED", "TaskActor", "moves_of"]

#: The actor every write of the task actor names.
ACTOR = "starpulse/task-actor"
#: What the task actor comments when the board's lint refuses a task's release to Ready, before the refusal.
LINT_REFUSED = "Release to Ready refused by the task lint, repair the record to release it:"
#: What the task actor comments on a task whose Start Criteria stayed in error for two passes, before the errors.
REGATE = "Start Criteria could not be evaluated for two passes, an agent re-gates the task:"
#: The machine event a delivery run publishes when it ends, its verdict in the event's data.
DELIVER_FINISHED = "DELIVER_FINISHED"
#: The pull request states that end a pull request.
_TERMINAL = ("MERGED", "CLOSED")
#: The repository the board renders a bare `PR #N` against; another repo's pull request links its own URL.
_BOARD_REPO = "trantor-org/trantor"
REFUSALS_METRIC = "starpulse_task_actor_refusals_total"
CRITERIA_ERRORS_METRIC = "starpulse_task_actor_criteria_errors"
PIN_HELD_METRIC = "starpulse_task_actor_pin_held"
DONE_HELD = "Held from Done:"
#: The facts read from a task's evaluated Start Criteria.
_CRITERIA_FACTS = ("criteria_met", "criteria_unmet")
LATENCY_METRIC = "starpulse_task_actor_latency_seconds"
#: The upper bounds of the latency histogram's buckets, in seconds; the count past the last is the `+Inf` bucket's.
BUCKETS_S = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
PROJECTION_METRIC = "starpulse_task_actor_projection_seconds"
HANDOFF_METRIC = "starpulse_task_actor_handoff_seconds"
#: The bounds of the projection and handoff histograms: a pin walk takes seconds, and the 10 s bound is the measure.
SLOW_BUCKETS_S = (0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0)
#: Seconds the event loop waits for a change before it looks at its stop flag.
_POLL_S = 0.5
#: A Waiting task's service level expectation: seconds from entering Waiting, or past its latest `expect_by`.
_DAY_S = 86_400.0
#: The facts whose event parks a task in Needs attention: the comment is also its `## Needs attention` reason, a question.
_ASKS = ("overdue", "pr_closed_unmerged")
_SLE_DAYS, _GRACE_DAYS = 7, 2
#: Start Criteria evaluated at once: each is a subprocess, so the pass is bounded rather than one thread per gated task.
_EVALUATIONS = 8


def _exit_links(machines: Mapping[str, Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Each lifecycle machine's links that exit on a skill machine's state: `{machine: [link]}`, the Board's apart."""
    found = {
        name: [link for link in drawn.get("submachines", ()) if link.get("exits")] for name, drawn in machines.items()
    }
    return {name: links for name, links in found.items() if links and name != "board"}


def _lint_record(agent: Mapping[str, Any]) -> tuple[Any, ...]:
    """The parts of a task's record the board's lint reads, which a repair changes and a comment does not."""
    return agent["description"], agent["profile"], tuple(agent["labels"]), tuple(agent["dependencies"])


def _view(agent: Mapping[str, Any]) -> tuple[str, tuple[str, ...], tuple[str, ...], tuple[bool, ...]]:
    """The parts of a task's record the actor re-derives on: its lane, dependencies, pull requests and checked criteria."""
    ticks = tuple(criterion["checked"] for criterion in agent.get("criteria", ()))
    return agent["state"], tuple(agent["dependencies"]), tuple(agent["prs"]), ticks


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


def _dod_ticks(agent: Mapping[str, Any]) -> tuple[bool, ...]:
    """Which of a task's Definition of Done items are checked; empty when its record carries none."""
    return tuple(item["checked"] for item in agent.get("definition_of_done", ()))


def moves_of(machine: Mapping[str, Any]) -> dict[tuple[str, str], str]:
    """`{(lane, event): target lane}` for the transitions of a drawn machine (`snapshot.describe`)."""
    return {(move["source"], move["event"]): move["target"] for move in machine["transitions"]}


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
        with self._lock:
            counts, total = list(self._counts), self._sum
        buckets = [
            f'{name}_bucket{{le="{bound:g}"}} {count}' for bound, count in zip(self._bounds, counts, strict=False)
        ]
        return [
            f"# HELP {name} {help_text}",
            f"# TYPE {name} histogram",
            *buckets,
            f'{name}_bucket{{le="+Inf"}} {counts[-1]}',
            f"{name}_sum {total:g}",
            f"{name}_count {counts[-1]}",
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
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        evaluate: Callable[[str, str], list[dict[str, Any]]] | None = None,
        holds: Callable[[str], Sequence[str]] | None = None,
        parked: Callable[[str], None] | None = None,
        released: Callable[[str], None] | None = None,
        delivered: Callable[[str, str], None] | None = None,
        closed: Callable[[str], None] | None = None,
        fresh_s: float = criteria.CACHE_SECONDS,
        live: LiveBuild | None = None,
        advance: Callable[[str, str, str], None] | None = None,
        read: TaskReader | None = None,
        sequences: Mapping[str, Sequence[str]] = MappingProxyType({}),
        unfinished: Callable[[str], Sequence[str]] | None = None,
        create: TaskCreator | None = None,
    ) -> None:
        self._read = read
        self._create = create
        self._advance = advance
        #: The phases a task of each type goes through, in order (`[sequences]`); `default` serves an unnamed type.
        self._sequences = sequences
        self._unfinished = unfinished
        #: Each non-Board machine's links that exit on a skill machine's state, when there is somewhere to send the exit.
        self._links = _exit_links(feed.machines) if advance else {}
        #: The exit last sent for each `(machine, task)`, with the phase's step count, so one exit is sent once.
        self._exited: dict[tuple[str, str], tuple[str, int, str]] = {}
        self._feed = feed
        self._store = store
        self._edit = edit
        self._waits = waits
        self._moves = moves
        self._clock = clock
        #: Epoch seconds, which a task's `entered` and `expect_by` are in; `clock` is monotonic and has no date.
        self._wall = wall
        #: The lanes that wait on the service level expectation.
        self._timed_lanes = {lane for lane, facts in waits.items() if "overdue" in facts}
        #: When each timed task's deadline falls, if still ahead, and the `expect_by` dates it was armed on.
        self._due: dict[str, float] = {}
        self._dates: dict[str, tuple[str, ...]] = {}
        self._evaluate = evaluate
        self._holds = holds
        self._tell = parked
        self._released = released
        self._delivered = delivered
        #: The step count of each task's last finished delivery handed to `delivered`, so one run's end is told once.
        self._told: dict[str, int] = {}
        self._closed = closed
        self._fresh_s = fresh_s
        #: The lanes that wait on a task's Start Criteria.
        self._gated_lanes = {lane for lane, facts in waits.items() if facts.keys() & set(_CRITERIA_FACTS)}
        #: When each gated task's criteria were last evaluated, and each criterion's `(id, status)` then.
        self._results: dict[str, tuple[float, tuple[tuple[str, str], ...]]] = {}
        #: The Start Criteria each gated task carried when its record last changed: a result is dropped when they change.
        self._gates: dict[str, list[dict[str, Any]] | None] = {}
        #: Tasks whose `deps_done` the board adapter holds; a task created re-derives them.
        self._held: set[str] = set()
        self._gate = PinGate(feed, store, repos, pin_rule, pins, live)
        self._lock = threading.RLock()
        #: Each open task's lane, dependencies and pull requests as the actor last saw them.
        self._seen: dict[str, tuple[str, tuple[str, ...], tuple[str, ...], tuple[bool, ...]]] = {}
        self._by_pr: dict[str, set[str]] = {}
        #: What each pull request last read as, so a refresh that changed nothing derives nothing.
        self._pull_states: dict[str, tuple[str, str | None, bool, str]] = {}
        #: Per task sent back from Review to the working lane, the head of each pull request it cites at that moment: a
        #: ready pull request still on that head is the reviewed work, which `pr_ready` does not send to Review again.
        self._sent_back: dict[str, dict[str, str]] = {}
        #: Tasks whose dependencies are done but wait for a pin bump, and the store revision last read for them.
        self._pin_held: set[str] = set()
        self._store_rev = store.rev
        #: The move last tried for each task, until the task changes lane: the same facts are not tried twice.
        self._tried: dict[str, tuple] = {}
        #: The refusal each task was last parked in Needs attention for, so the same refusal parks it once.
        self._parked: dict[str, str] = {}
        #: The record each task's release was last refused on by the board's lint, so a repaired record is tried again.
        self._lint_held: dict[str, tuple[Any, ...]] = {}
        #: Each open task's Definition of Done ticks as the actor last saw them, so a tick that completes them is seen.
        self._ticks: dict[str, tuple[bool, ...]] = {}
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
        #: Set by a store save; `_saved_at` is the clock when the oldest unread save happened.
        self._saved = threading.Event()
        self._saved_at = 0.0
        #: Set once the start's derivation of every open task is done.
        self.ready = threading.Event()
        #: Set once the start sweep has indexed the open tasks and read their pull requests, before it derives them.
        self.indexed = threading.Event()
        #: How many times each task's waits were derived, for the tests and a diagnosis.
        self.derivations: Counter[str] = Counter()

    def exposition(self) -> str:
        """Prometheus text of the writes the board refused and of how long a fact took to become a landed write."""
        with self._metrics:
            counts, total, refusals = list(self._buckets), self._sum, self._refusals
        with self._lock:
            errors = {
                name: sum(status == "error" for _, status in statuses) for name, (_, statuses) in self._results.items()
            }
            pin_held = len(self._pin_held)
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
                f"# HELP {PIN_HELD_METRIC} Waiting tasks whose dependencies are done but wait for a pin bump to merge.",
                f"# TYPE {PIN_HELD_METRIC} gauge",
                f"{PIN_HELD_METRIC} {pin_held}",
                f"# HELP {CRITERIA_ERRORS_METRIC} Start Criteria the evaluator could not evaluate, per gated task; such a gate never passes.",
                f"# TYPE {CRITERIA_ERRORS_METRIC} gauge",
                *(
                    f'{CRITERIA_ERRORS_METRIC}{{task="{name}"}} {count}'
                    for name, count in sorted(errors.items())
                    if count
                ),
                "",
            ]
        )

    def start(self, stop: threading.Event) -> threading.Thread:
        """Follow the feed on a daemon thread until `stop` is set."""
        thread = threading.Thread(target=self._run, args=(stop,), name="task-actor", daemon=True)
        thread.start()
        if self._evaluate is not None and self._gated_lanes:
            threading.Thread(target=self._keep_criteria, args=(stop,), name="task-actor-criteria", daemon=True).start()
        threading.Thread(target=self._follow_store, args=(stop,), name="task-actor-store", daemon=True).start()
        if self._timed_lanes:
            threading.Thread(target=self._keep_deadlines, args=(stop,), name="task-actor-deadlines", daemon=True).start()
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

    def _follow_store(self, stop: threading.Event) -> None:
        """Re-derive the tasks whose pull requests changed as soon as the store saves, ahead of the projection that
        saved it finishing its pin walk."""
        self.indexed.wait()
        while not stop.is_set():
            if not self._saved.wait(_POLL_S):
                continue
            self._saved.clear()
            try:
                self._store_saved(self._saved_at)
            except Exception:  # one pass must not end the thread
                logger.exception("task actor: cannot read the pull request store")

    def _store_saved(self, saved: float) -> None:
        with self._lock:
            observed = self._clock()
            self._handoff.observe(observed - saved)
            self._derive_all(self._read_pulls(), observed)

    def _keep_criteria(self, stop: threading.Event) -> None:
        """Evaluate each gated task whose result is missing or stale, and re-derive it when the result changed."""
        self.ready.wait()
        while not stop.is_set():
            try:
                self._evaluate_due()
            except Exception:  # one pass must not end the thread
                logger.exception("task actor: cannot evaluate Start Criteria")
            stop.wait(min(self._fresh_s / 2, _POLL_S))

    def _keep_deadlines(self, stop: threading.Event) -> None:
        """Derive each armed task again at its own deadline, so a Waiting task goes overdue with no event to wake it."""
        self.ready.wait()
        while not stop.is_set():
            try:
                with self._lock:
                    now = self._wall()
                    late = [name for name, due in self._due.items() if due <= now]
                    for name in late:
                        del self._due[name]
                    self._derive_all(late, self._clock())
                    ahead = min(self._due.values(), default=None)
            except Exception:  # one pass must not end the thread
                logger.exception("task actor: cannot derive the overdue tasks")
                ahead = None
            stop.wait(_POLL_S if ahead is None else max(0.0, min(ahead - self._wall(), _POLL_S)))

    def _evaluate_due(self) -> None:
        gated = {
            agent["id"]: agent["description"]
            for agent in self._feed.open_tasks()
            if agent["state"] in self._gated_lanes and criteria.authored(agent["description"])
        }
        with self._lock:
            for name in self._results.keys() - gated.keys():  # no longer gated: its result and its errors go
                del self._results[name]
                self._error_passes.pop(name, None)
            now = self._clock()
            due = [
                name
                for name in sorted(gated)
                if name not in self._results or now - self._results[name][0] >= self._fresh_s
            ]
        with ThreadPoolExecutor(max_workers=_EVALUATIONS) as pool:  # a slow task must not hold up the ones sorted after it
            running = {pool.submit(self._evaluated, name, gated[name]): name for name in due}
            for finished in as_completed(running):
                self._keep_result(running[finished], gated[running[finished]], finished.result())

    def _evaluated(self, name: str, description: str) -> list[dict[str, Any]]:
        try:
            return self._evaluate(name, description)
        except Exception as error:  # an evaluator returns errors as results; this one raised
            logger.warning("task actor: cannot evaluate the Start Criteria of %s: %s", name, error)
            return [{"id": each["id"], "status": "error"} for each in criteria.authored(description)]

    def _keep_result(self, name: str, description: str, evaluated: list[dict[str, Any]]) -> None:
        statuses = tuple((str(each["id"]), str(each["status"])) for each in evaluated)
        observed = self._clock()
        with self._lock:
            current = self._feed.task(name)
            if not current or criteria.authored(current["description"]) != criteria.authored(description):
                return  # parked again on other criteria, or gone, while it ran: the result is not this park's
            before = self._results.get(name)
            self._results[name] = (observed, statuses)
            if before is None or before[1] != statuses:
                self._derive(name, observed)
            self._count_error_passes(name, evaluated)

    def _run(self, stop: threading.Event) -> None:
        self._feed.wait_replayed()
        _, changes = self._feed.subscribe()
        with self._lock:
            observed = self._clock()
            tasks = self._feed.open_tasks()
            for agent in tasks:
                self._index(agent)
            self._read_pulls()
        self.indexed.set()
        for name in sorted(agent["id"] for agent in tasks):  # per task, so a store save waits one derivation
            with self._lock:
                self._derive(name, observed)
        with self._lock:
            for parent in self._links:
                for placed in self._feed.machine_tasks(parent):
                    self._exit_phase(placed["id"])
        self.ready.set()
        while not stop.is_set():
            try:
                kind, data = changes.get(timeout=_POLL_S)
            except queue.Empty:
                continue
            if kind in ("task", "move"):
                handle = self._changed if kind == "task" else self._moved
                try:
                    handle(data)
                except Exception:  # one change must not end the actor
                    logger.exception("task actor: cannot handle the change of %s", data.get("id"))

    def _drop_stale_result(self, name: str, agent: dict[str, Any]) -> None:
        """Forget the last evaluation of a task that left the gated lanes or was gated on other criteria: the sweep
        that does so runs only between passes, and a slow evaluation holds a pass, so a task parked again would
        otherwise be released on the result of its last park."""
        gate = self._gate_of(agent)
        if self._gates.get(name) != gate:
            self._results.pop(name, None)
        self._gates[name] = gate

    def _gate_of(self, agent: dict[str, Any]) -> list[dict[str, Any]] | None:
        return criteria.authored(agent["description"]) if agent["state"] in self._gated_lanes else None

    def _index(self, agent: dict[str, Any]) -> None:
        """Take `agent`'s lane, dependencies, pull requests and checked criteria into the indexes."""
        name = agent["id"]
        for url in self._seen.get(name, ("", (), (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._seen[name] = _view(agent)
        self._gates.setdefault(name, self._gate_of(agent))
        self._ticks[name] = _dod_ticks(agent)
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
            ticks = _dod_ticks(agent)
            ticked = all(ticks) and ticks != self._ticks.get(
                name, ticks
            )  # the last item checked: a refused Done move may now pass
            if ticked:
                self._tried.pop(name, None)
            rearmed = agent["state"] in self._timed_lanes and tuple(
                criteria.expect_dates(agent["description"])
            ) != self._dates.get(name, ())
            if before == (now := _view(agent)) and not repaired and not ticked and not rearmed:
                return
            self._index(agent)
            touched = {name}
            if before is None:  # a task created: a hold may have waited on it
                touched |= self._held
            if before is None or before[0] != now[0]:
                self._tried.pop(name, None)
                self._sent_back.pop(name, None)
                if before and before[0] == "review" and now[0] == self._feed.roles.working:
                    self._sent_back[name] = self._heads(agent)
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
        data = last.get("data") or {}
        verdict = " ".join(part for part in (data.get("verdict"), data.get("step")) if part)
        try:
            self._delivered(task, verdict)
        except Exception:  # the move stands; a board hook is a notice, not part of the write
            logger.exception("task actor: %s finished its delivery but its holder was not told", task)

    def _exit_phase(self, task: str) -> None:
        """Send the exit event of the phase `task` is in when that phase's skill machine sits in the state its link exits
        on. A skill machine the current phase does not link never counts, so a late final event of an earlier phase's
        skill advances nothing."""
        for parent, links in self._links.items():
            phase = self._feed.machine_task(parent, task)
            event = self._exit_event(links, phase["state"], task) if phase else None
            if phase and event and self._exited.get((parent, task)) != (phase["state"], phase["steps"], event):
                self._exited[parent, task] = (phase["state"], phase["steps"], event)
                self._advance(parent, task, event)

    def _exit_event(self, links: Sequence[Mapping[str, Any]], phase: str, task: str) -> str | None:
        for link in links:
            placed = self._feed.machine_task(link["machine"], task) if link["state"] == phase else None
            if placed and link["exits"].get(placed["state"]):
                return self._route(link, task) or link["exits"][placed["state"]]
        return None

    def _route(self, link: Mapping[str, Any], task: str) -> str | None:
        """The event of the link's route to the phase after it in the sequence of `task`'s type, when the link draws one."""
        kind = (self._feed.task(task) or {}).get("type", "").lower()
        sequence = self._sequences.get(kind) or self._sequences.get("default", ())
        following = sequence[sequence.index(link["state"]) + 1 :][:1] if link["state"] in sequence else ()
        return link.get("routes", {}).get(following[0]) if following else None

    def _forget(self, name: str) -> None:
        for url in self._seen.pop(name, ("", (), (), ()))[2]:
            self._by_pr.get(url, set()).discard(name)
        self._tried.pop(name, None)
        self._sent_back.pop(name, None)
        self._ticks.pop(name, None)
        self._lint_held.pop(name, None)
        self._due.pop(name, None)
        self._dates.pop(name, None)
        self._gates.pop(name, None)

    def _dependents(self, name: str) -> set[str]:
        return {other for other, (_, dependencies, *_) in self._seen.items() if name in dependencies}

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
        return pull_record(self._store, url)

    def _own_prs(self, agent: dict[str, Any]) -> list[str]:
        return own_prs(self._store, agent)

    def _proof_prs(self, agent: dict[str, Any]) -> list[str]:
        """The pull requests whose ends prove a task's work. In Review, a task with no own pull request merged takes
        every cited one: another task's delivery may have superseded its own, which closed unmerged or never existed."""
        own = self._own_prs(agent)
        if agent["state"] != "review":
            return own
        if any((record := self._record(url)) and record["state"] == "MERGED" for url in own):
            return own
        return agent["prs"]

    def _pull_state(self, url: str) -> tuple[str, str | None, bool, str]:
        record = self._record(url)
        if record is None:
            return "", None, False, ""
        return record["state"], record["mergeSha"], record["isDraft"], record["headRefOid"]

    def _heads(self, agent: dict[str, Any]) -> dict[str, str]:
        """The head of each own pull request of the task the store holds."""
        records = {url: self._record(url) for url in self._own_prs(agent)}
        return {url: record["headRefOid"] for url, record in records.items() if record}

    def _derive_all(self, names: Any, observed: float) -> None:
        for name in sorted(names):
            self._derive(name, observed)

    def _derive(self, name: str, observed: float) -> None:
        """Write the first move the task's lane waits on whose fact holds. A move already tried on these facts, or one the
        board refuses, leaves the next fact its turn: a Waiting task whose return to Review is refused still reaches Ready."""
        agent = self._feed.task(name)
        if agent is None:
            return
        self.derivations[name] += 1
        self._arm(name, agent)
        for fact, event in self._waits.get(agent["state"], {}).items():
            target = self._moves.get((agent["state"], event))
            held = self._facts.get(fact, lambda *_: None)(self, agent) if target else None
            if held is None:
                continue
            evidence, comment = held
            sent = (agent["state"], event, evidence)
            if self._tried.get(name) == sent:
                continue
            self._tried[name] = sent
            changes = self._stale(agent) if fact.startswith("deps_done") else {}
            if fact in _ASKS:
                changes = {"description": section_set(agent["description"], "Needs attention", comment)}
            if self._write(name, target, comment, observed, source=agent["state"], stale=changes):
                return

    def _write(
        self, name: str, target: str, comment: str, observed: float, source: str, stale: Mapping[str, Any] = {}
    ) -> bool:
        written = self._apply(name, {"status": target, **stale}, comment)
        if written.ok:
            self._landed(self._clock() - observed)
            roles = self._feed.roles
            if self._tell and source == roles.working and target == roles.waiting:
                self._notice(self._tell, name, "was parked but its holder was not told")
            if self._released and source == roles.waiting and target == roles.ready:
                self._notice(self._released, name, "was released but its holder was not told")
            if self._closed and target == roles.done:
                self._notice(self._closed, name, "was closed but the board was not told")
            return True
        logger.warning("task actor: %s was not moved to %s: %s", name, target, written.output)
        if target == self._feed.roles.ready:
            if written.lint:
                self._hold_for_repair(name, written.output)
            else:
                self._park(name, written.output)
        with self._metrics:
            self._refusals += 1
        return False

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
        priority = (self._feed.task(name) or {}).get("priority") or "medium"  # the re-gate is as urgent as the task it unblocks
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
        self._lint_held[name] = _lint_record(self._feed.task(name))
        written = self._apply(name, {}, f"{LINT_REFUSED} {refusal.rstrip('.')}.")
        if not written.ok:
            logger.warning("task actor: the lint refusal of %s was not commented: %s", name, written.output)

    def _notice(self, hook: Callable[[str], None], name: str, missed: str) -> None:
        """Run the board's `parked`, `released` or `closed` hook for a task the actor just moved; a failure is logged only."""
        try:
            hook(name)
        except Exception:  # the move stands; a board hook is a notice, not part of the write
            logger.exception("task actor: %s %s", name, missed)

    def _park(self, name: str, refusal: str) -> None:
        """Write a task whose release to Ready was refused to Needs attention, with the refusal as its reason."""
        if self._parked.get(name) == refusal:
            return
        self._parked[name] = refusal
        reason = f"{refusal.rstrip('.')}. Clear it so the task can return to Ready?"
        description = section_set(self._feed.task(name)["description"], "Needs attention", reason)
        written = self._apply(name, {"status": self._feed.roles.attention, "description": description}, reason)
        if not written.ok:
            logger.warning("task actor: %s was not parked in Needs attention: %s", name, written.output)

    def _apply(self, name: str, changes: Mapping[str, Any], comment: str) -> Written:
        with self._feed.recording:  # the board's poll finds the lane recorded under the actor, not as external
            try:
                written = self._edit(name, changes, comment, actor=ACTOR)
            except Exception as error:  # a board that raises refuses like one that answers no
                written = Written(False, str(error))
            if written.ok and written.lane:
                self._feed.record_written(name, written.lane, written.at or time.time(), (ACTOR, "", ""))
        return written

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
            link = f"PR #{record['number']}" if record["repo"] == _BOARD_REPO else url
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
        Verify plan is present exactly when `planned`, else None: a delivery closed unmerged is no proof of the work."""
        terminal = self._pr_terminal(agent)
        merged = any((record := self._record(url)) and record["state"] == "MERGED" for url in self._proof_prs(agent))
        return terminal if terminal and merged and self._planned(agent) is planned else None

    def _pr_closed_unmerged(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The closed pull requests and the Needs attention question when every pull request the task cites has ended and
        none merged: its delivery is gone and no merge will ever close it."""
        terminal = self._pr_terminal(agent)
        merged = any((record := self._record(url)) and record["state"] == "MERGED" for url in self._proof_prs(agent))
        if not terminal or merged:
            return None
        return terminal[0], (
            f"Every pull request it cites closed unmerged: {terminal[0]}. "
            "Close it as superseded, or redeliver it?"
        )

    def _pr_closed_unmerged_complete(self, agent: dict[str, Any]) -> tuple[str, str] | None:
        """The closed pull requests when `_pr_closed_unmerged` holds and every criterion and Definition of Done item is
        checked: the work was done without a merge (a no-op), so nothing is left to ask the operator."""
        closed = self._pr_closed_unmerged(agent)
        ticks = _dod_ticks(agent) + tuple(criterion["checked"] for criterion in agent.get("criteria", ()))
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
        """The merge evidence and what is left when the task's pull requests merged and the board reports work
        unfinished, else None. A command that fails reports its error: the task returns to its holder, never closes."""
        merged = self._pr_merged(agent)
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
        session's answer."""
        parts = []
        held = self._sent_back.get(agent["id"], {})
        for url in self._own_prs(agent):
            record = self._record(url)
            if record is None:
                continue
            merged = record["state"] == "MERGED" and record["mergedAt"]
            reviewed = held.get(url) == record["headRefOid"]
            if merged or (record["state"] == "OPEN" and not record["isDraft"] and not reviewed):
                parts.append(f"{record['repo']}#{record['number']} {'merged' if merged else 'ready'}")
        if not parts:
            return None
        proof = "; ".join(parts)
        return proof, f"Pull request ready: {proof}"

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
        try:
            return tuple(self._holds(name))
        except Exception as error:
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
            written = self._edit(name, {}, f"{prefix} {'; '.join(reasons)}.", actor=ACTOR)
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
        self._due.pop(name, None)
        if agent["state"] not in self._timed_lanes:
            self._dates.pop(name, None)
            return
        self._dates[name] = tuple(criteria.expect_dates(agent["description"]))
        deadline = self._deadline(agent)
        if deadline and deadline[0] > self._wall():
            self._due[name] = deadline[0]

    def _deadline(self, agent: dict[str, Any]) -> tuple[float, str] | None:
        """When the task's service level expectation ends, in epoch seconds, and what it is counted from; None while the
        task is exempt (gated only on dependencies, each still In Progress or Review) or has no entry time.
        The SLE is the latest `expect_by` plus two days, else seven days from entering the lane."""
        if not agent.get("entered"):
            return None
        if not criteria.authored(agent["description"]) and self._moving(agent):
            return None
        dates = [stamp for stamp in map(_epoch, criteria.expect_dates(agent["description"])) if stamp]
        if dates:
            return max(dates) + _GRACE_DAYS * _DAY_S, f"expect_by {_stamp(max(dates))} plus {_GRACE_DAYS} days"
        return agent["entered"] + _SLE_DAYS * _DAY_S, f"{_SLE_DAYS} days from entering Waiting"

    def _moving(self, agent: dict[str, Any]) -> bool:
        """Whether the task has open dependencies and each is In Progress or Review: work is under way on its gate."""
        roles = self._feed.roles
        open_ = [dependency for dependency in agent["dependencies"] if not self._feed.is_done(dependency)]
        return bool(open_) and all(
            (self._feed.task(dependency) or {}).get("state") in (roles.working, roles.review) for dependency in open_
        )

    def _overdue(self, agent: dict[str, Any]) -> tuple[Any, str] | None:
        """The deadline and the Needs attention question when the task is past its service level expectation."""
        deadline = self._deadline(agent)
        now = self._wall()
        if not deadline or deadline[0] > now:
            return None
        if self._evaluate is not None and criteria.authored(agent["description"]) and agent["id"] not in self._results:
            return None  # the gate is not read yet: its result derives the task again, and a gate that holds comes first
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
            if not self._feed.is_done(dependency) and dependency not in early
        )

    def _early(self, agent: dict[str, Any]) -> tuple[str, ...]:
        """The open dependencies whose every criterion the task's record says it needs (`dependencyNeeds`, `TASK-N#K`)
        is checked: the fact the task waited on holds, whatever the dependency still has open. A dependency with no
        need names the whole task; a record the board cannot read names none."""
        open_ = [dependency for dependency in agent["dependencies"] if not self._feed.is_done(dependency)]
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
        ticks = tuple(criterion["checked"] for criterion in (self._feed.task(dependency) or {}).get("criteria", ()))
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
        "deps_done": _deps_done,
        "deps_done_with_pr": _deps_done_with_pr,
        "deps_unresolved": _deps_unresolved,
        "criteria_met": _criteria_met,
        "criteria_unmet": _criteria_unmet,
        "overdue": _overdue,
    }
