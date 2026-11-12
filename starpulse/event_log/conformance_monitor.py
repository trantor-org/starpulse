"""Live conformance: the moves recorded on the event log, counted per machine against the transitions it declares.

The `board` machine is judged on the `board:lanes` stream (`lane_events`): a task's lane change is a violation when no
transition leads from the lane it left to the lane it entered, and the first lane seen for a task is placed unjudged,
because the log keeps no earlier history. Every other machine is judged on the `machine:events` stream (`events`):
an event is a violation when no state the task or run may be in declares it (`replay.EventJudge`). A guard that reads
a task's facts is not judged. The counts cover the entries the log retains and everything appended since.

The counts, each task's lane and each judged key's states are saved every `CHECKPOINT_S` with the id of the last entry
of each stream they cover (`CHECKPOINT`), so a restart reads only what was appended after them instead of replaying the
whole retention. A checkpoint of another `CHECKPOINT_VERSION` or other machines, or one whose last entry of a stream
the log no longer retains (so the entries after it may have been pruned unread), is ignored and the retention replayed. A resumed count still holds the entries pruned since it was saved, as
the process that saved it did.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import defaultdict
from collections.abc import Mapping
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

#: The setting the counts and states are saved under, with the last entry of each stream they cover.
CHECKPOINT = "conformance:checkpoint"
#: Raised when what a checkpoint holds, or how an entry is counted, changes, so an older one is replayed over.
CHECKPOINT_VERSION = 1
#: Seconds between two saves of a changed checkpoint.
CHECKPOINT_S = 300.0
_STREAMS = (lane_events.STREAM, events.STREAM)

logger = logging.getLogger(__name__)


def _basis(machines: Mapping[str, dict]) -> str:
    """The fingerprint of what the counts are judged against: each machine's states and transitions."""
    shapes = {
        name: [
            sorted((s["id"], bool(s["initial"]), bool(s["final"])) for s in machine["states"]),
            sorted((t["source"], t["target"], t["event"]) for t in machine["transitions"]),
        ]
        for name, machine in machines.items()
    }
    return hashlib.sha256(json.dumps([CHECKPOINT_VERSION, list(machines), shapes]).encode()).hexdigest()


class Conformance:
    """Counts, per machine, the moves read from the log and the ones among them no transition declares."""

    def __init__(self, machines: Mapping[str, dict]) -> None:
        self._names = list(machines)
        self._basis = _basis(machines)
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

    def handle_lane(self, entry: Entry) -> None:
        task, lane = entry.fields.get("task"), entry.fields.get("lane")
        with self._lock:
            self._cursors[lane_events.STREAM] = entry.id
            if BOARD not in self._names or not task or not lane:
                return
            source = self._lanes.get(task)
            self._lanes[task] = lane
            if source is None or source == lane:
                return
            self._judged[BOARD] += 1
            self._violations[BOARD] += (source, lane) not in self._lane_moves

    def handle_event(self, entry: Entry) -> None:
        machine, event, key = (
            entry.fields.get("machine"),
            entry.fields.get("event"),
            entry.fields.get("task") or entry.fields.get("run"),
        )
        with self._lock:
            self._cursors[events.STREAM] = entry.id
            if machine not in self._judges or not event or not key:
                return
            self._judged[machine] += 1
            if (machine, event) in self._occurrences:
                self._occurrences[machine, event] += 1
            self._violations[machine] += self._judges[machine].judge(key, event) is not None

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
            return f"{counters}# HELP {OCCURRENCES_METRIC} {OCCURRENCES_HELP}\n# TYPE {OCCURRENCES_METRIC} counter\n{occurrences}"

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

    def _resumed(self, log: EventLog) -> dict[str, int]:
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
        self, log: EventLog, stop: StopEvent, checkpoint_s: float = CHECKPOINT_S
    ) -> list[threading.Thread]:
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
