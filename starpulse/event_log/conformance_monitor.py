"""Live conformance: the moves recorded on the event log, counted per machine against the transitions it declares.

The `board` machine is judged on the `board:lanes` stream (`lane_events`): a task's lane change is a violation when no
transition leads from the lane it left to the lane it entered, and the first lane seen for a task is placed unjudged,
because the log keeps no earlier history. The moves into each lane named in `entered` (the Board's done lane and
`archived`) are counted too, a task's first sight in one included. With the `working` and `review` lanes named, each
lane change from the first to the second is counted as a review move (a first sight is none), and the tasks in the
`working` lane now are a gauge, and so are those among them stalled: a stall is `STALL_S` with no lane change and no
event of a work machine (`work`: the machines `liveness.work_machines` names) or of the harness's `TOOL_USED` for the task in the working lane,
and a task counts from its first stall until it leaves the lane, a stall still open at the scrape included. Every other machine is judged on the `machine:events` stream (`events`):
an event is a violation when no state the task or run may be in declares it (`replay.EventJudge`). A guard that reads
a task's facts is not judged. The counts cover the entries the log retains and everything appended since.

The counts, each task's lane and each judged key's states are saved `CHECKPOINT_DEBOUNCE_S` after a change, and at stop, with the id of the last entry
of each stream they cover (`CHECKPOINT`), so a restart reads only what was appended after them instead of replaying the
whole retention. A checkpoint of another `CHECKPOINT_VERSION` or other machines, or one whose last entry of a stream
the log no longer retains (so the entries after it may have been pruned unread), is ignored and the retention replayed. A resumed count still holds the entries pruned since it was saved, as
the process that saved it did, and so does the review-move count after an ignored checkpoint: the replay counts only
the moves after the ignored one's last lane entry, so a restart never lowers that counter.
"""

import hashlib
import json
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Collection, Iterable, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.event_log import events, lane_events
from starpulse.event_log.wake import StopEvent, save_on_change
from starpulse.machine_engine.model.replay import EventJudge, lane_moves
from starpulse.machine_engine.model.transitions import tables

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

BOARD = "board"
VIOLATIONS_METRIC = "starpulse_machine_conformance_violations_total"
JUDGED_METRIC = "starpulse_machine_conformance_events_total"
VIOLATIONS_HELP = "Recorded moves no transition of the machine declares, per machine."
OCCURRENCES_METRIC = "starpulse_machine_event_occurrences_total"
OCCURRENCES_HELP = "Recorded occurrences of each event a machine declares, per machine and event."
JUDGED_HELP = "Recorded moves judged against the machine's transitions, per machine."
ENTERED_METRIC = "starpulse_board_lane_entered_total"
ENTERED_HELP = (
    "Recorded entries into each counted lane, such as Done or archived: a lane change, or a task's first sight in it."
)
REVIEW_MOVES_METRIC = "starpulse_board_review_moves_total"
REVIEW_MOVES_HELP = "Recorded lane changes from the working lane to the review lane."
WORKING_METRIC = "starpulse_board_in_progress_tasks"
WORKING_HELP = "Tasks in the working lane now."
STALLED_METRIC = "starpulse_board_in_progress_stalled_tasks"
STALLED_HELP = "Tasks in the working lane now that had a stall, 5 minutes with no lane change and no work event or tool call, in their stay."
REMAINING_METRIC = "starpulse_conformance_replay_remaining_entries"
REMAINING_HELP = "Entry ids of the board and machine streams past the monitor's cursors up to the heads it found at start, 0 once it has read them."
IDLE_METRIC = "starpulse_board_in_progress_idle_seconds"
IDLE_HELP = "Seconds since the last lane move, work event or tool call of a working task whose holder no running shell keeps busy and whose harness is not active or silent for the stall bound, per task."
#: Seconds with no lane change and no task event after which a working task is stalled.
STALL_S = 300.0
_HARNESS, _COMMAND = "harness", "TOOL_USED"
DONE_METRIC = "starpulse_tasks_done_total"
DONE_HELP = "Recorded lane entries into the done lane, per task type; a type the board does not declare counts as other."
TRANSITIONS_METRIC = "starpulse_machine_transitions_total"
TRANSITIONS_HELP = "Recorded moves along a transition a machine declares, per machine, source state and target state."
LANE_SECONDS_METRIC = "starpulse_task_lane_duration_seconds"
LANE_SECONDS_HELP = "Seconds a task stayed in a lane, observed when it left, per lane."
JOB_SECONDS_METRIC = "starpulse_job_run_duration_seconds"
JOB_SECONDS_HELP = "Seconds from a job's first event to its machine's final state, per machine; a job is an instance keyed by a run."
#: Upper bounds, in seconds, of a lane stay (a minute to a week) and of a job run (a second to four hours).
LANE_BOUNDS_S = (60.0, 300.0, 900.0, 3600.0, 14400.0, 43200.0, 86400.0, 259200.0, 604800.0)
JOB_BOUNDS_S = (1.0, 5.0, 15.0, 60.0, 300.0, 900.0, 3600.0, 14400.0)
#: The `type` label of a done task whose type the board does not declare.
OTHER_TYPE = "other"
NO_EVENT_METRIC = "starpulse_harness_active_no_event_seconds"
NO_EVENT_HELP = "Seconds since the last lane move, work event or tool call of a working task, per task, whose harness reads active or whose settled holder a running shell keeps busy; no series when none."

#: The setting the counts and states are saved under, with the last entry of each stream they cover.
CHECKPOINT = "conformance:checkpoint"
#: Raised when what a checkpoint holds, or how an entry is counted, changes, so an older one is replayed over.
CHECKPOINT_VERSION = 7
#: Seconds after a cursor moves before its changed checkpoint is saved.
CHECKPOINT_DEBOUNCE_S = 10.0
_STREAMS = (lane_events.STREAM, events.STREAM)

logger = logging.getLogger(__name__)


def _basis(
    machines: Mapping[str, dict],
    entered: Collection[str] = (),
    watched: Collection[str | None] = (),
    work: Collection[str] = (),
) -> str:
    """The fingerprint of what the counts are judged against: each machine's states and transitions, the lanes
    whose entries are counted, the working, review and done lanes and the declared types, and the machines whose
    events are work."""
    shapes = {
        name: [
            sorted((s["id"], bool(s["initial"]), bool(s["final"])) for s in machine["states"]),
            sorted((t["source"], t["target"], t["event"]) for t in machine["transitions"]),
        ]
        for name, machine in machines.items()
    }
    return hashlib.sha256(
        json.dumps([CHECKPOINT_VERSION, list(machines), shapes, sorted(entered), list(watched), sorted(work)]).encode()
    ).hexdigest()


class _Histogram:
    """Cumulative bucket counts of observed seconds, kept as plain data for the checkpoint."""

    def __init__(self, bounds: tuple[float, ...]) -> None:
        self.bounds = bounds
        self.counts = [0] * len(bounds)
        self.total = 0
        self.seconds = 0.0

    def observe(self, seconds: float) -> None:
        self.counts = [count + (seconds <= bound) for count, bound in zip(self.counts, self.bounds, strict=True)]
        self.total += 1
        self.seconds += seconds

    def lines(self, metric: str, label: str, value: str) -> str:
        series = f'{label}="{_escape(value)}"'
        buckets = "".join(
            f'{metric}_bucket{{{series},le="{bound:g}"}} {count}\n'
            for bound, count in zip(self.bounds, self.counts, strict=True)
        )
        return (
            f'{buckets}{metric}_bucket{{{series},le="+Inf"}} {self.total}\n'
            f"{metric}_sum{{{series}}} {self.seconds}\n{metric}_count{{{series}}} {self.total}\n"
        )

    def held(self) -> dict[str, Any]:
        return {"counts": self.counts, "total": self.total, "seconds": self.seconds}

    def restore(self, held: Mapping[str, Any]) -> None:
        self.counts, self.total, self.seconds = list(held["counts"]), held["total"], held["seconds"]


class Conformance:
    """Counts, per machine, the moves read from the log and the ones among them no transition declares."""

    def __init__(
        self,
        machines: Mapping[str, dict],
        entered: Collection[str] = (),
        working: str | None = None,
        review: str | None = None,
        work: Collection[str] = (),
        clock: Callable[[], float] = time.time,
        open_tasks: Callable[[], Iterable[Mapping[str, Any]]] | None = None,
        sessions: Mapping[str, dict] = {},
        done: str | None = None,
        types: Collection[str] = (),
        busy: Callable[[str], bool] = lambda _task: False,
    ) -> None:
        self._busy = busy
        self._names = list(machines)
        self._done, self._types = done, set(types)
        self._entered: dict[str, int] = dict.fromkeys(entered, 0)
        self._working, self._review = working, review
        self._review_moves = 0
        #: The lane-stream entry the review moves already counted reach: a replay over an ignored checkpoint counts
        #: only the moves after it, so the exported counter never falls.
        self._review_after = 0
        self._clock = clock
        self._open_tasks = open_tasks
        self._work = set(work)
        #: When each task in the working lane last moved or took an event, and those among them that had a stall.
        self._active: dict[str, float] = {}
        self._stalled: set[str] = set()
        #: The work events of each task outside the working lane as far as the lane stream has read; its entry into the
        #: lane takes those at or after it, and its exit drops those up to it, whichever stream is read first.
        self._seen: dict[str, list[float]] = {}
        judged = {**sessions, **machines}
        self._basis = _basis(judged, entered, (working, review, done, *sorted(self._types)), self._work)
        #: The id of the last entry of each stream handled, which the counts cover.
        self._cursors: dict[str, int] = {}
        self._saved: dict[str, int] = {}
        #: Set when an entry moves a cursor, so the saver writes the checkpoint after a debounce.
        self._moved = threading.Event()
        self._lane_moves = lane_moves(machines[BOARD]) if BOARD in machines else set()
        # `sessions` are judged too but kept out of `_names`, so they add no counter series.
        tables_ = tables(judged)
        self._judges = {name: EventJudge(table) for name, table in tables_.items()}
        self._lanes: dict[str, str] = {}
        self._violations: dict[str, int] = defaultdict(int)
        self._judged: dict[str, int] = defaultdict(int)
        self._occurrences: dict[tuple[str, str], int] = {
            (name, event): 0 for name, table in tables_.items() for event in sorted(table.moves)
        }
        #: The done entries per `type` label: the declared types, none and other from the first scrape.
        self._done_types: dict[str, int] = dict.fromkeys((*sorted(self._types), "", OTHER_TYPE), 0)
        self._tables = tables_
        #: The declared moves, by `(machine, source, target)`, of the machines that give counters; a self loop is no move.
        self._transitions: dict[tuple[str, str, str], int] = {
            (BOARD, source, target): 0 for source, target in sorted(self._lane_moves) if source != target
        }
        for name in self._names:
            if name in self._tables:
                self._transitions.update(
                    {(name, source, target): 0 for event in sorted(self._tables[name].moves)
                     for source, targets in self._tables[name].moves[event].items()
                     for target in sorted(targets) if source != target}
                )
        #: When each task entered the lane it is in, for the stay observed when it leaves.
        self._lane_since: dict[str, float] = {}
        self._lane_hist: dict[str, _Histogram] = {
            state["id"]: _Histogram(LANE_BOUNDS_S) for state in machines.get(BOARD, {}).get("states", ())
        }
        #: When each run of a machine, a job, had its first event, until it reaches a final state.
        self._run_start: dict[str, dict[str, float]] = {}
        self._job_hist: dict[str, _Histogram] = {
            name: _Histogram(JOB_BOUNDS_S) for name in self._names if self._tables.get(name) and self._tables[name].finals
        }
        self._lock = threading.Lock()
        #: The last entry of each stream when `follow` began, which the lane-entered counts are held back until read;
        #: None when `follow` could not read them.
        self._until: dict[str, int] | None = {}
        self._log: EventLog | None = None

    def handle_lane(self, entry: Entry) -> None:
        task, lane = entry.fields.get("task"), entry.fields.get("lane")
        self._recover_heads()
        with self._lock:
            self._cursors[lane_events.STREAM] = entry.id
            self._moved.set()
            if not task or not lane:
                return
            source = self._lanes.get(task)
            self._lanes[task] = lane
            if source == lane:
                return
            if self._working:
                self._active.pop(task, None)
                self._stalled.discard(task)
                if source == self._working:
                    self._seen[task] = [at for at in self._seen.get(task, ()) if at > entry.at]
                if lane == self._working:
                    self._enter(task, entry.at)
            if lane in self._entered:
                self._entered[lane] += 1
            self._export_lane(task, source, lane, entry)
            if self._review and source == self._working and lane == self._review and entry.id > self._review_after:
                self._review_moves += 1
            if BOARD not in self._names or source is None:
                return
            self._judged[BOARD] += 1
            self._violations[BOARD] += (source, lane) not in self._lane_moves

    def handle_event(self, entry: Entry) -> None:
        machine, event, key = (
            entry.fields.get("machine"),
            entry.fields.get("event"),
            entry.fields.get("task") or entry.fields.get("run"),
        )
        self._recover_heads()
        with self._lock:
            self._cursors[events.STREAM] = entry.id
            self._moved.set()
            if key:
                self._touch(key, machine, event, entry.at)
            if machine not in self._judges or not event or not key:
                return
            self._judged[machine] += 1
            if (machine, event) in self._occurrences:
                self._occurrences[machine, event] += 1
            judge = self._judges[machine]
            before = judge.states(key)
            refused = judge.judge(key, event) is not None
            self._violations[machine] += refused
            if not refused and machine in self._names:
                self._export_event(machine, event, key, before, bool(entry.fields.get("task")), entry.at)

    def _export_lane(self, task: str, source: str | None, lane: str, entry: Entry) -> None:
        since = self._lane_since.get(task)
        self._lane_since[task] = entry.at
        if source in self._lane_hist and since is not None:
            self._lane_hist[source].observe(max(0.0, entry.at - since))
        if (BOARD, source, lane) in self._transitions:
            self._transitions[BOARD, source, lane] += 1
        if self._done and lane == self._done:
            kind = entry.fields.get("type") or ""
            self._done_types["" if not kind else kind if kind in self._types else OTHER_TYPE] += 1

    def _export_event(
        self, machine: str, event: str, key: str, before: frozenset[str], of_task: bool, at: float
    ) -> None:
        table = self._tables[machine]
        for source, target in table.steps(before, event):
            if (machine, source, target) in self._transitions:
                self._transitions[machine, source, target] += 1
        if of_task or machine not in self._job_hist:
            return
        started = self._run_start.setdefault(machine, {}).setdefault(key, at)
        if (states := self._judges[machine].states(key)) and states <= table.finals:
            del self._run_start[machine][key]
            self._job_hist[machine].observe(max(0.0, at - started))

    def _exports(self) -> str:
        done = "".join(f'{DONE_METRIC}{{type="{_escape(kind)}"}} {count}\n' for kind, count in self._done_types.items())
        moves = "".join(
            f'{TRANSITIONS_METRIC}{{flow="{_escape(flow)}",from="{_escape(source)}",to="{_escape(target)}"}} {count}\n'
            for (flow, source, target), count in self._transitions.items()
        )
        text = f"# HELP {TRANSITIONS_METRIC} {TRANSITIONS_HELP}\n# TYPE {TRANSITIONS_METRIC} counter\n{moves}" if moves else ""
        if self._done:
            text += f"# HELP {DONE_METRIC} {DONE_HELP}\n# TYPE {DONE_METRIC} counter\n{done}"
        for metric, help_, label, hists in (
            (LANE_SECONDS_METRIC, LANE_SECONDS_HELP, "lane", self._lane_hist),
            (JOB_SECONDS_METRIC, JOB_SECONDS_HELP, "flow", self._job_hist),
        ):
            if hists:
                text += f"# HELP {metric} {help_}\n# TYPE {metric} histogram\n"
                text += "".join(hist.lines(metric, label, value) for value, hist in hists.items())
        return text

    def _enter(self, task: str, entered: float) -> None:
        last = entered
        self._seen[task] = [at for at in sorted(self._seen.get(task, ())) if at >= entered]
        for at in self._seen[task]:
            if at - last >= STALL_S:
                self._stalled.add(task)
            last = at
        self._active[task] = last

    def _touch(self, task: str, machine: str | None, event: str | None, at: float) -> None:
        if not (self._working and (machine in self._work or (machine == _HARNESS and event == _COMMAND))):
            return
        last = self._active.get(task)
        if last is None:
            seen = self._seen.setdefault(task, [])
            seen.append(at)
            if len(seen) > 2 and seen[-3] <= seen[-2] <= at and at - seen[-3] < STALL_S:
                del seen[-2]  # no stay entered anywhere in this span could count a stall within it
            return
        if at - last >= STALL_S:
            self._stalled.add(task)
        self._active[task] = max(last, at)

    def _working_now(self) -> set[str]:
        """The tasks in the working lane: the board's own, where it is given, since a lane move recorded nowhere (a file
        moved while the server was down) never reaches the lane stream; else those the lane stream last placed there."""
        if self._open_tasks is not None:
            return {task["id"] for task in self._open_tasks() if task["state"] == self._working}
        return {task for task, lane in self._lanes.items() if lane == self._working}

    def stall_state(self) -> dict[str, Any]:
        """The working tasks already stalled and the epoch deadlines of the others, which the gauge counts as time passes
        them (`stalled_exposition`); empty while the lane streams are not read up."""
        with self._lock:
            return self._stall_state()

    def _stall_state(self) -> dict[str, Any]:
        if not (self.caught_up() and self._working and self._review):
            return {}
        working = self._working_now()
        live = {task: last for task, last in self._active.items() if task in working}
        quiet = {task: last for task, last in live.items() if not self._busy(task)}
        idle = {task: last for task, last in quiet.items() if not self._harness_active(task)}
        return {
            "stalled": sum(task in self._stalled for task in live),
            "due": sorted(last + STALL_S for task, last in live.items() if task not in self._stalled),
            "idle": idle,
            "idle_due": {task: last for task, last in quiet.items() if task not in idle},
            "active": {task: last for task, last in live.items() if task not in idle},
        }

    def _harness_active(self, task: str) -> bool:
        return _HARNESS in self._judges and self._judges[_HARNESS].states(task) == {"active"}

    def caught_up(self) -> bool:
        """Whether both streams are read up to the entries they held when `follow` began."""
        return self._until is not None and all(
            self._cursors.get(stream, 0) >= last for stream, last in self._until.items()
        )

    def exposition(self, stalled: bool = True) -> str:
        """Prometheus text of the counters, a series per machine (and per declared event) from the first scrape; the
        stalled gauge too unless `stalled` is False, for a reader that serves it at scrape. While a replay reads on, the
        review-move count shows once an ignored checkpoint kept it, and the working-lane gauge when the board gives
        `open_tasks`: neither depends on the entries replayed."""
        with self._lock:
            counters = "".join(
                f"# HELP {metric} {text}\n# TYPE {metric} counter\n"
                + "".join(f'{metric}{{machine="{_escape(name)}"}} {counts[name]}\n' for name in self._names)
                for metric, text, counts in (
                    (VIOLATIONS_METRIC, VIOLATIONS_HELP, self._violations),
                    (JUDGED_METRIC, JUDGED_HELP, self._judged),
                )
            )
            occurrences = "".join(
                f'{OCCURRENCES_METRIC}{{machine="{_escape(name)}",event="{_escape(event)}"}} {count}\n'
                for (name, event), count in self._occurrences.items()
            )
            caught_up = self.caught_up()
            entered = "".join(
                f'{ENTERED_METRIC}{{lane="{_escape(lane)}"}} {count}\n' for lane, count in self._entered.items()
            )
            entered = entered if caught_up else ""
            entered_head = (
                f"# HELP {ENTERED_METRIC} {ENTERED_HELP}\n# TYPE {ENTERED_METRIC} counter\n" if entered else ""
            )
            remaining = ""
            if self._until is not None:
                left = sum(max(0, last - self._cursors.get(stream, 0)) for stream, last in self._until.items())
                remaining = f"# HELP {REMAINING_METRIC} {REMAINING_HELP}\n# TYPE {REMAINING_METRIC} gauge\n{REMAINING_METRIC} {left}\n"
            watched = ""
            if self._working and self._review:
                if caught_up or self._review_after:
                    watched += (
                        f"# HELP {REVIEW_MOVES_METRIC} {REVIEW_MOVES_HELP}\n# TYPE {REVIEW_MOVES_METRIC} counter\n"
                        f"{REVIEW_MOVES_METRIC} {self._review_moves}\n"
                    )
                if caught_up or self._open_tasks is not None:
                    watched += (
                        f"# HELP {WORKING_METRIC} {WORKING_HELP}\n# TYPE {WORKING_METRIC} gauge\n"
                        f"{WORKING_METRIC} {len(self._working_now())}\n"
                    )
                if caught_up and stalled:
                    watched += stalled_exposition(self._stall_state(), self._clock())
            return (
                f"{counters}# HELP {OCCURRENCES_METRIC} {OCCURRENCES_HELP}\n# TYPE {OCCURRENCES_METRIC} counter\n"
                f"{occurrences}{remaining}{entered_head}{entered}{watched}{self._exports() if caught_up else ''}"
            )

    def checkpoint(self) -> dict[str, Any]:
        """The counts, each task's lane and each judged key's states as plain data, with the last entry of each stream
        they cover."""
        with self._lock:
            return {
                "version": CHECKPOINT_VERSION,
                "basis": self._basis,
                "cursors": dict(self._cursors),
                "lanes": dict(self._lanes),
                "violations": dict(self._violations),
                "judged": dict(self._judged),
                "entered": dict(self._entered),
                "review_moves": self._review_moves,
                "done_types": dict(self._done_types),
                "transitions": [[*move, count] for move, count in self._transitions.items()],
                "lane_since": dict(self._lane_since),
                "lane_hist": {lane: hist.held() for lane, hist in self._lane_hist.items()},
                "run_start": {name: dict(runs) for name, runs in self._run_start.items()},
                "job_hist": {name: hist.held() for name, hist in self._job_hist.items()},
                "active": dict(self._active),
                "stalled": sorted(self._stalled),
                "seen": {task: list(times) for task, times in self._seen.items()},
                "occurrences": [[name, event, count] for (name, event), count in self._occurrences.items()],
                "where": {name: judge.held() for name, judge in self._judges.items()},
            }

    def resume(self, held: Any, first: Mapping[str, int | None]) -> dict[str, int] | None:
        """Take the state of the `checkpoint` `held` and return the cursors to read on from; None, taking nothing,
        when it is missing, of another version or other machines, or when a stream's `first` retained entry lies past
        its cursor: the log prunes oldest first, so an entry after the cursor may have been pruned uncounted."""
        if not isinstance(held, dict):
            return None
        if held.get("version") != CHECKPOINT_VERSION or held.get("basis") != self._basis:
            self._keep_review_moves(held)
            return None
        cursors = {stream: int(cursor) for stream, cursor in held["cursors"].items() if stream in _STREAMS}
        for stream, cursor in cursors.items():
            oldest = first.get(stream)
            if oldest is None or oldest > cursor:
                self._keep_review_moves(held)
                return None
        with self._lock:
            self._cursors = dict(cursors)
            self._saved = dict(cursors)
            self._lanes = dict(held["lanes"])
            self._violations = defaultdict(int, held["violations"])
            self._judged = defaultdict(int, held["judged"])
            self._entered = {lane: held["entered"].get(lane, 0) for lane in self._entered}
            self._review_moves = held["review_moves"]
            self._done_types.update(held["done_types"])
            for flow, source, target, count in held["transitions"]:
                if (flow, source, target) in self._transitions:
                    self._transitions[flow, source, target] = count
            self._lane_since = dict(held["lane_since"])
            for lane, hist in self._lane_hist.items():
                hist.restore(held["lane_hist"][lane])
            self._run_start = {name: dict(runs) for name, runs in held["run_start"].items()}
            for name, hist in self._job_hist.items():
                hist.restore(held["job_hist"][name])
            self._active = dict(held["active"])
            self._stalled = set(held["stalled"])
            self._seen = {task: list(times) for task, times in held["seen"].items()}
            for name, event, count in held["occurrences"]:
                self._occurrences[name, event] = count
            for name, judge in self._judges.items():
                judge.restore(held["where"].get(name, {}))
        return cursors

    def _keep_review_moves(self, held: Mapping[str, Any]) -> None:
        cursors = held.get("cursors")
        cursor = cursors.get(lane_events.STREAM) if isinstance(cursors, Mapping) else None
        if isinstance(held.get("review_moves"), int) and isinstance(cursor, int):
            with self._lock:
                self._review_moves, self._review_after = held["review_moves"], cursor

    def save(self, log: EventLog) -> None:
        """Save the `checkpoint` under `CHECKPOINT` when an entry was handled since the last save; a failed write is
        logged and tried again a debounce later."""
        held = self.checkpoint()
        if held["cursors"] == self._saved:
            return
        try:
            log.set_setting(CHECKPOINT, held)
        except Exception:
            logger.warning("conformance: cannot save the checkpoint", exc_info=True)
            self._moved.set()
            return
        self._saved = held["cursors"]

    def _recover_heads(self) -> None:
        if self._until is not None or self._log is None:
            return
        try:
            heads = {stream: self._log.last(stream) for stream in _STREAMS}
        except Exception:
            return
        with self._lock:
            self._until = {stream: head for stream, head in heads.items() if head is not None}

    def _resumed(self, log: EventLog) -> dict[str, int]:
        self._log = log
        try:
            heads = {stream: log.last(stream) for stream in _STREAMS}
            self._until = {stream: head for stream, head in heads.items() if head is not None}
        except Exception:
            self._until = None
            logger.warning(
                "conformance: cannot read the stream heads; lane-entered series hidden until a later read",
                exc_info=True,
            )
        try:
            held = log.setting(CHECKPOINT)
            first = {stream: log.first(stream) for stream in _STREAMS}
        except Exception:
            logger.warning("conformance: cannot read the checkpoint; replaying the retained log", exc_info=True)
            return {}
        cursors = self.resume(held, first)
        if cursors is None:
            logger.info("conformance: no checkpoint of these machines to resume; replaying the retained log")
            return {}
        logger.info("conformance: resuming after %s", cursors)
        return cursors

    def follow(
        self,
        log: EventLog,
        stop: StopEvent,
        after: Callable[[], None] = lambda: None,
    ) -> list[threading.Thread]:
        """Read `log` from the saved checkpoint, or what it retains when none applies, then follow it, on a thread per
        stream until `stop`, saving the checkpoint `CHECKPOINT_DEBOUNCE_S` after a cursor moves and once at stop, and
        calling `after` once each entry is handled;
        the threads read the log, so the caller does not wait on a long one."""
        cursors = self._resumed(log)
        threads = []
        for stream, handle in ((lane_events.STREAM, self.handle_lane), (events.STREAM, self.handle_event)):
            tail = log.tail(stream, after=cursors.get(stream))
            thread = threading.Thread(
                target=tail.run, args=(lane_events.then(handle, after), stop), name=f"conformance-{stream}", daemon=True
            )
            thread.start()
            threads.append(thread)
        saver = threading.Thread(
            target=save_on_change,
            args=(stop, self._moved, lambda: self.save(log), CHECKPOINT_DEBOUNCE_S),
            name="conformance-checkpoint",
            daemon=True,
        )
        saver.start()
        return [*threads, saver]


def stalled_exposition(state: Mapping[str, Any], now: float) -> str:
    """Prometheus text of the stalled gauge at `now` from a `stall_state`: the tasks already stalled and those whose
    deadline has passed; empty for no state."""
    if not state:
        return ""
    stalled = state["stalled"] + sum(due <= now for due in state["due"])
    # a state kept before this series existed has none until the monitor rewrites it; an entry stamped after the scrape
    # clock reads 0, never negative
    quiet = "".join(
        f'{NO_EVENT_METRIC}{{task="{_escape(task)}"}} {max(now - last, 0.0)}\n'
        for task, last in state.get("active", {}).items()
    )
    return (
        f"# HELP {STALLED_METRIC} {STALLED_HELP}\n# TYPE {STALLED_METRIC} gauge\n{STALLED_METRIC} {stalled}\n"
        f"# HELP {NO_EVENT_METRIC} {NO_EVENT_HELP}\n# TYPE {NO_EVENT_METRIC} gauge\n{quiet}"
        f"# HELP {IDLE_METRIC} {IDLE_HELP}\n# TYPE {IDLE_METRIC} gauge\n"
        + "".join(
            f'{IDLE_METRIC}{{task="{_escape(task)}"}} {max(now - last, 0.0)}\n'
            for task, last in {
                **{task: last for task, last in state.get("idle_due", {}).items() if last + STALL_S <= now},
                **state.get("idle", {}),
            }.items()
        )
    )


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
