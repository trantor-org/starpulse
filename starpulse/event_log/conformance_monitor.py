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

The counts, each task's lane and each judged key's states are saved every `CHECKPOINT_S` with the id of the last entry
of each stream they cover (`CHECKPOINT`), so a restart reads only what was appended after them instead of replaying the
whole retention. A checkpoint of another `CHECKPOINT_VERSION` or other machines, or one whose last entry of a stream
the log no longer retains (so the entries after it may have been pruned unread), is ignored and the retention replayed. A resumed count still holds the entries pruned since it was saved, as
the process that saved it did.
"""

import hashlib
import json
import logging
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Collection, Mapping
from typing import TYPE_CHECKING, Any

from starpulse.event_log import events, lane_events
from starpulse.event_log.wake import StopEvent
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
#: Seconds with no lane change and no task event after which a working task is stalled.
STALL_S = 300.0
_HARNESS, _COMMAND = "harness", "TOOL_USED"

#: The setting the counts and states are saved under, with the last entry of each stream they cover.
CHECKPOINT = "conformance:checkpoint"
#: Raised when what a checkpoint holds, or how an entry is counted, changes, so an older one is replayed over.
CHECKPOINT_VERSION = 6
#: Seconds between two saves of a changed checkpoint.
CHECKPOINT_S = 300.0
_STREAMS = (lane_events.STREAM, events.STREAM)

logger = logging.getLogger(__name__)


def _basis(
    machines: Mapping[str, dict],
    entered: Collection[str] = (),
    watched: Collection[str | None] = (),
    work: Collection[str] = (),
) -> str:
    """The fingerprint of what the counts are judged against: each machine's states and transitions, the lanes
    whose entries are counted, the working and review lanes, and the machines whose events are work."""
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
    ) -> None:
        self._names = list(machines)
        self._entered: dict[str, int] = dict.fromkeys(entered, 0)
        self._working, self._review = working, review
        self._review_moves = 0
        self._clock = clock
        self._work = set(work)
        #: When each task in the working lane last moved or took an event, and those among them that had a stall.
        self._active: dict[str, float] = {}
        self._stalled: set[str] = set()
        #: The work events of each task outside the working lane as far as the lane stream has read; its entry into the
        #: lane takes those at or after it, and its exit drops those up to it, whichever stream is read first.
        self._seen: dict[str, list[float]] = {}
        self._basis = _basis(machines, entered, (working, review), self._work)
        #: The id of the last entry of each stream handled, which the counts cover.
        self._cursors: dict[str, int] = {}
        self._saved: dict[str, int] = {}
        self._lane_moves = lane_moves(machines[BOARD]) if BOARD in machines else set()
        tables_ = tables(machines)
        self._judges = {name: EventJudge(table) for name, table in tables_.items()}
        self._lanes: dict[str, str] = {}
        self._violations: dict[str, int] = defaultdict(int)
        self._judged: dict[str, int] = defaultdict(int)
        self._occurrences: dict[tuple[str, str], int] = {
            (name, event): 0 for name, table in tables_.items() for event in sorted(table.moves)
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
            if self._review and source == self._working and lane == self._review:
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
            if key:
                self._touch(key, machine, event, entry.at)
            if machine not in self._judges or not event or not key:
                return
            self._judged[machine] += 1
            if (machine, event) in self._occurrences:
                self._occurrences[machine, event] += 1
            self._violations[machine] += self._judges[machine].judge(key, event) is not None

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

    def exposition(self) -> str:
        """Prometheus text of the counters, a series per machine (and per declared event) from the first scrape."""
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
            caught_up = self._until is not None and all(
                self._cursors.get(stream, 0) >= last for stream, last in self._until.items()
            )
            entered = "".join(
                f'{ENTERED_METRIC}{{lane="{_escape(lane)}"}} {count}\n' for lane, count in self._entered.items()
            )
            entered = entered if caught_up else ""
            entered_head = (
                f"# HELP {ENTERED_METRIC} {ENTERED_HELP}\n# TYPE {ENTERED_METRIC} counter\n" if entered else ""
            )
            watched = ""
            if caught_up and self._working and self._review:
                working = sum(lane == self._working for lane in self._lanes.values())
                now = self._clock()
                stalled = sum(task in self._stalled or now - last >= STALL_S for task, last in self._active.items())
                watched = (
                    f"# HELP {REVIEW_MOVES_METRIC} {REVIEW_MOVES_HELP}\n# TYPE {REVIEW_MOVES_METRIC} counter\n"
                    f"{REVIEW_MOVES_METRIC} {self._review_moves}\n"
                    f"# HELP {WORKING_METRIC} {WORKING_HELP}\n# TYPE {WORKING_METRIC} gauge\n{WORKING_METRIC} {working}\n"
                    f"# HELP {STALLED_METRIC} {STALLED_HELP}\n# TYPE {STALLED_METRIC} gauge\n{STALLED_METRIC} {stalled}\n"
                )
            return (
                f"{counters}# HELP {OCCURRENCES_METRIC} {OCCURRENCES_HELP}\n# TYPE {OCCURRENCES_METRIC} counter\n"
                f"{occurrences}{entered_head}{entered}{watched}"
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
        if not isinstance(held, dict) or held.get("version") != CHECKPOINT_VERSION or held.get("basis") != self._basis:
            return None
        cursors = {stream: int(cursor) for stream, cursor in held["cursors"].items() if stream in _STREAMS}
        for stream, cursor in cursors.items():
            oldest = first.get(stream)
            if oldest is None or oldest > cursor:
                return None
        with self._lock:
            self._cursors = dict(cursors)
            self._saved = dict(cursors)
            self._lanes = dict(held["lanes"])
            self._violations = defaultdict(int, held["violations"])
            self._judged = defaultdict(int, held["judged"])
            self._entered = {lane: held["entered"].get(lane, 0) for lane in self._entered}
            self._review_moves = held["review_moves"]
            self._active = dict(held["active"])
            self._stalled = set(held["stalled"])
            self._seen = {task: list(times) for task, times in held["seen"].items()}
            for name, event, count in held["occurrences"]:
                self._occurrences[name, event] = count
            for name, judge in self._judges.items():
                judge.restore(held["where"].get(name, {}))
        return cursors

    def save(self, log: EventLog) -> None:
        """Save the `checkpoint` under `CHECKPOINT` when an entry was handled since the last save; a failed write is
        logged and tried again at the next."""
        held = self.checkpoint()
        if held["cursors"] == self._saved:
            return
        try:
            log.set_setting(CHECKPOINT, held)
        except Exception:
            logger.warning("conformance: cannot save the checkpoint", exc_info=True)
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

    def follow(self, log: EventLog, stop: StopEvent, checkpoint_s: float = CHECKPOINT_S) -> list[threading.Thread]:
        """Read `log` from the saved checkpoint, or what it retains when none applies, then follow it, on a thread per
        stream until `stop`, saving the checkpoint every `checkpoint_s`; the threads read the log, so the caller does
        not wait on a long one."""
        cursors = self._resumed(log)
        threads = []
        for stream, handle in ((lane_events.STREAM, self.handle_lane), (events.STREAM, self.handle_event)):
            tail = log.tail(stream, after=cursors.get(stream))
            thread = threading.Thread(target=tail.run, args=(handle, stop), name=f"conformance-{stream}", daemon=True)
            thread.start()
            threads.append(thread)
        saver = threading.Thread(
            target=self._keep_saving, args=(log, stop, checkpoint_s), name="conformance-checkpoint", daemon=True
        )
        saver.start()
        return [*threads, saver]

    def _keep_saving(self, log: EventLog, stop: StopEvent, checkpoint_s: float) -> None:
        while not stop.wait(checkpoint_s):
            self.save(log)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
