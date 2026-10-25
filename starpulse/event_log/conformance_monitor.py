"""Live conformance: the moves recorded on the event log, counted per machine against the transitions it declares.

The `board` machine is judged on the `board:lanes` stream (`lane_events`): a task's lane change is a violation when no
transition leads from the lane it left to the lane it entered, and the first lane seen for a task is placed unjudged,
because the log keeps no earlier history. Every other machine is judged on the `machine:events` stream (`events`):
an event is a violation when no state the task or run may be in declares it (`replay.EventJudge`). A guard that reads
a task's facts is not judged. The counts cover the entries the log retains and everything appended since.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from collections.abc import Mapping
from typing import TYPE_CHECKING

from starpulse.event_log import events, lane_events
from starpulse.machine_engine.model.replay import EventJudge, lane_moves
from starpulse.machine_engine.model.transitions import tables

if TYPE_CHECKING:
    from starpulse.event_log.event_log import Entry, EventLog

BOARD = "board"
VIOLATIONS_METRIC = "starpulse_machine_conformance_violations_total"
JUDGED_METRIC = "starpulse_machine_conformance_events_total"
VIOLATIONS_HELP = "Recorded moves no transition of the machine declares, per machine."
JUDGED_HELP = "Recorded moves judged against the machine's transitions, per machine."


class Conformance:
    """Counts, per machine, the moves read from the log and the ones among them no transition declares."""

    def __init__(self, machines: Mapping[str, dict]) -> None:
        self._names = list(machines)
        self._lane_moves = lane_moves(machines[BOARD]) if BOARD in machines else set()
        self._judges = {name: EventJudge(table) for name, table in tables(machines).items()}
        self._lanes: dict[str, str] = {}
        self._violations: dict[str, int] = defaultdict(int)
        self._judged: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def handle_lane(self, entry: Entry) -> None:
        task, lane = entry.fields.get("task"), entry.fields.get("lane")
        if BOARD not in self._names or not task or not lane:
            return
        with self._lock:
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
        if machine not in self._judges or not event or not key:
            return
        with self._lock:
            self._judged[machine] += 1
            self._violations[machine] += self._judges[machine].judge(key, event) is not None

    def exposition(self) -> str:
        """Prometheus text of both counters, a series per machine from the first scrape."""
        with self._lock:
            return "".join(
                f"# HELP {metric} {text}\n# TYPE {metric} counter\n"
                + "".join(f'{metric}{{machine="{_escape(name)}"}} {counts[name]}\n' for name in self._names)
                for metric, text, counts in (
                    (VIOLATIONS_METRIC, VIOLATIONS_HELP, self._violations),
                    (JUDGED_METRIC, JUDGED_HELP, self._judged),
                )
            )

    def follow(self, log: EventLog, stop: threading.Event) -> list[threading.Thread]:
        """Read what `log` retains, then follow it, on a thread per stream until `stop`; the thread reads the retained part, so the caller does not wait on a long log."""
        threads = []
        for stream, handle in ((lane_events.STREAM, self.handle_lane), (events.STREAM, self.handle_event)):
            from starpulse.event_log.event_log import Tail  # noqa: PLC0415 - the database stack loads when a log opens

            tail = Tail.replay(log, stream)
            thread = threading.Thread(target=tail.run, args=(handle, stop), name=f"conformance-{stream}", daemon=True)
            thread.start()
            threads.append(thread)
        return threads


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
