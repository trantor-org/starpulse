"""Task liveness and the Board's pace into Review, from lane changes and machine events.

`liveness` is a pure function of the stays tasks made in the working lane (`working_stays` over
`LaneHistory.lane_rows`) and each task's machine events (`HistoryStore.task_events`), so a fixture history gives numbers
that can be worked out by hand. A task's state changes when it changes lane or a work machine (the working lane's
machine and the machines it links) takes an event for it; it issues a command when the harness machine takes
`TOOL_USED` for it. A task is stalled once both are older than the threshold, and the events say why:

- `slow_process`: a machine outside the work (a check, a pipeline) moved the task inside the threshold, or the session's
  turn is still open on a command that has not returned; `waits_in` names that machine's state, or the stage the task
  works in.
- `waiting_checks`: the session's turn ended and the last check rollup of the task's stay, whatever its age, is
  pending; a rollup from before the stay is not read.
- `idle`: the session's turn ended and nothing outside moves the task.
- `unattributed`: no harness event names the task, so its commands cannot be seen.

Every second a task spends in the working lane inside the window is slot time, held by one cause: `working` for a
silence no longer than the threshold (a quiet after a turn end included), else the cause the silence stalled on.

Any other outside process that runs silent for longer than the threshold reads `idle`: only an event shows it running.
"""

import math
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from typing import Any, NamedTuple

__all__ = ["HARNESS", "WorkingStay", "liveness", "work_machines", "working_stays"]

#: The machine a session's own events move, and what its events mean here.
HARNESS = "harness"
_COMMAND = "TOOL_USED"
_TURN_ENDED = frozenset({"SESSION_STOPPED", "SESSION_SETTLED"})
#: The machine a pull request's check rollup moves, and its state while a required check has not reported.
_CHECKS = "pr-checks"
_PENDING = "pending"
_HOUR_S = 3600.0


class WorkingStay(NamedTuple):
    """One stay of `task` in the working `lane`: when it `began`, when it `ended` (None: still there) and the lane it
    moved `to`."""

    task: str
    lane: str
    began: float
    ended: float | None
    to: str | None


def work_machines(machines: Mapping[str, Mapping[str, Any]], board: str, working: str) -> set[str]:
    """The machines whose events are a working task's state changes: the lifecycle machine `board`'s `working` State
    links (the link whose `exits` move the task on) and every machine linked beneath it. A machine the State links with
    no exits, such as a pipeline's, runs beside the work and is no part of it."""
    links = [
        link["machine"]
        for link in machines.get(board, {}).get("submachines", ())
        if link["state"] == working and link.get("exits")
    ]
    work: set[str] = set()
    while links:
        machine = links.pop()
        if machine not in work:
            work.add(machine)
            links.extend(link["machine"] for link in machines.get(machine, {}).get("submachines", ()))
    return work


def working_stays(
    rows: Iterable[tuple[str, float, str | None, str]], working: Collection[str], *, start: float
) -> list[WorkingStay]:
    """The stays in a `working` lane that are still going or ended at or after `start`, from `(task, at, from, to)`
    lane changes oldest first. A row repeating a task, time and lanes is one change, as the Backlog Flow Metric
    Definitions count it."""
    open_stays: dict[str, tuple[str, float]] = {}
    stays: list[WorkingStay] = []
    for task, at, _before, to in dict.fromkeys(tuple(row) for row in rows):
        held = open_stays.get(task)
        if held is None and to in working:
            open_stays[task] = (to, at)
        elif held is not None and to not in working:
            del open_stays[task]
            if at >= start:
                stays.append(WorkingStay(task, held[0], held[1], at, to))
    return stays + [WorkingStay(task, lane, began, None, None) for task, (lane, began) in open_stays.items()]


def liveness(
    stays: Iterable[WorkingStay],
    events: Mapping[str, list[dict[str, Any]]],
    *,
    work: Collection[str],
    review: Collection[str],
    now: float,
    window_s: float,
    stalled_s: float,
) -> dict[str, Any]:
    """Each working task's liveness as of `now`, and the Board's pace into `review` over the last `window_s` seconds.

    `tasks` lists every task in the working lane, longest without a state change first: `state_idle_s` since its last
    state change, `command_idle_s` since its last command (None: none seen), `stalled` when both pass `stalled_s`, and
    a stalled task's `cause` and `waits_in`. `review` counts the moves from the working lane into a `review` lane inside
    the window, per hour and in hourly buckets from the window's start. `stages` and `stalls` read the stays those
    moves ended: the time spent after each work-machine event (`machine:state`; the lane before the first), summing to
    `in_progress_s`, and the time past the threshold in each silence, by cause, each largest first. `slots` splits the
    window's slot time (`slot_s`: every working stay's seconds inside it) by the cause that held each silence, whole,
    `working` for one inside the threshold, largest first; `review.per_slot_hour` is the moves per slot hour.
    """
    start = now - window_s
    stays = list(stays)
    reviewed = [stay for stay in stays if stay.ended is not None and stay.to in review and start <= stay.ended <= now]
    hours = [0] * math.ceil(window_s / _HOUR_S)
    stage_time: dict[str, list[float]] = defaultdict(list)
    stalls: dict[tuple[str, str | None], list[float]] = defaultdict(list)
    for stay in reviewed:
        hours[min(int((stay.ended - start) // _HOUR_S), len(hours) - 1)] += 1
        seen = _within(events.get(stay.task, ()), stay.began, stay.ended)
        for stage, length in _stages(stay, seen, work, stay.ended):
            stage_time[stage].append(length)
        for cause, length in _stalls(stay, seen, work, stay.ended, stalled_s):
            stalls[cause].append(length)
    total = sum(sum(lengths) for lengths in stage_time.values())
    slot_time: dict[str, float] = defaultdict(float)
    for stay in stays:
        ended = now if stay.ended is None else stay.ended
        for cause, length in _slots(
            stay, _within(events.get(stay.task, ()), stay.began, ended), work, start, ended, stalled_s
        ):
            slot_time[cause] += length
    slot_s = sum(slot_time.values())
    return {
        "now": now,
        "window_s": window_s,
        "stalled_after_s": stalled_s,
        "tasks": sorted(
            (
                _task(stay, _within(events.get(stay.task, ()), stay.began, now), work, now, stalled_s)
                for stay in stays
                if stay.ended is None
            ),
            key=lambda entry: -entry["state_idle_s"],
        ),
        "review": {
            "count": len(reviewed),
            "per_hour": len(reviewed) / (window_s / _HOUR_S),
            "per_slot_hour": len(reviewed) / (slot_s / _HOUR_S) if slot_s else None,
            "hours": [{"at": start + i * _HOUR_S, "count": count} for i, count in enumerate(hours)],
        },
        "in_progress_s": total,
        "stages": sorted(
            (
                {
                    "stage": stage,
                    "visits": len(lengths),
                    "task_s": sum(lengths),
                    "mean_s": sum(lengths) / len(lengths),
                    "share": sum(lengths) / total if total else None,
                }
                for stage, lengths in stage_time.items()
            ),
            key=lambda entry: -entry["task_s"],
        ),
        "slot_s": slot_s,
        "slots": sorted(
            ({"cause": cause, "slot_s": length, "share": length / slot_s} for cause, length in slot_time.items()),
            key=lambda entry: -entry["slot_s"],
        ),
        "stalls": sorted(
            (
                {"cause": cause, "waits_in": waits_in, "count": len(lengths), "stalled_s": sum(lengths)}
                for (cause, waits_in), lengths in stalls.items()
            ),
            key=lambda entry: -entry["stalled_s"],
        ),
    }


def _within(events: Iterable[dict[str, Any]], began: float, ended: float) -> list[dict[str, Any]]:
    return [event for event in events if began <= event["at"] <= ended]


def _task(stay: WorkingStay, seen: list[dict[str, Any]], work: Collection[str], now: float, stalled_s: float) -> dict:
    changed = max((e["at"] for e in seen if e["machine"] in work), default=stay.began)
    commanded = max((e["at"] for e in seen if _is_command(e)), default=None)
    stalled = now - changed > stalled_s and (commanded is None or now - commanded > stalled_s)
    cause, waits_in = _cause(stay, seen, work, now, stalled_s) if stalled else (None, None)
    return {
        "task": stay.task,
        "since": stay.began,
        "state_idle_s": now - changed,
        "command_idle_s": None if commanded is None else now - commanded,
        "stalled": stalled,
        "cause": cause,
        "waits_in": waits_in,
    }


def _is_command(event: dict[str, Any]) -> bool:
    return event["machine"] == HARNESS and event["event"] == _COMMAND


def _stage(stay: WorkingStay, seen: list[dict[str, Any]], work: Collection[str]) -> str:
    """The stage the task works in after `seen`: the state its last work-machine event left it in, else the lane."""
    last = next((e for e in reversed(seen) if e["machine"] in work), None)
    return stay.lane if last is None else f"{last['machine']}:{last['to']}"


def _cause(
    stay: WorkingStay, seen: list[dict[str, Any]], work: Collection[str], at: float, stalled_s: float
) -> tuple[str, str | None]:
    """Why the task is silent at `at`, from the events `seen` before it."""
    outside = [e for e in seen if e["machine"] not in work and e["machine"] != HARNESS and e["at"] > at - stalled_s]
    if outside:
        return "slow_process", f"{outside[-1]['machine']}:{outside[-1]['to']}"
    session = [e for e in seen if e["machine"] == HARNESS]
    if not session:
        return "unattributed", None
    if session[-1]["event"] in _TURN_ENDED:
        checks = next((e["to"] for e in reversed(seen) if e["machine"] == _CHECKS), None)
        return ("waiting_checks", f"{_CHECKS}:{checks}") if checks == _PENDING else ("idle", None)
    return "slow_process", _stage(stay, seen, work)


def _stages(
    stay: WorkingStay, seen: list[dict[str, Any]], work: Collection[str], ended: float
) -> Iterable[tuple[str, float]]:
    """Each stage of the stay with the seconds it lasted: from one work-machine event to the next, or to the end."""
    steps = [(stay.began, stay.lane), *((e["at"], f"{e['machine']}:{e['to']}") for e in seen if e["machine"] in work)]
    for (at, stage), (until, _next) in zip(steps, [*steps[1:], (ended, "")], strict=True):
        yield stage, until - at


def _silences(
    stay: WorkingStay, seen: list[dict[str, Any]], work: Collection[str], ended: float, stalled_s: float
) -> Iterable[tuple[float, float, tuple[str, str | None] | None]]:
    """Each stretch of the stay with no state change and no command, as when it began and ended and, when it ran
    longer than `stalled_s`, the cause it stalled on."""
    active = [stay.began, *(e["at"] for e in seen if e["machine"] in work or _is_command(e)), ended]
    for at, until in zip(active, active[1:], strict=False):
        stalled = until - at > stalled_s
        yield at, until, _cause(stay, [e for e in seen if e["at"] < until], work, until, stalled_s) if stalled else None


def _stalls(
    stay: WorkingStay, seen: list[dict[str, Any]], work: Collection[str], ended: float, stalled_s: float
) -> Iterable[tuple[tuple[str, str | None], float]]:
    """Each silence of the stay longer than `stalled_s` (no state change and no command) as its cause and the seconds
    it ran past the threshold."""
    for at, until, cause in _silences(stay, seen, work, ended, stalled_s):
        if cause is not None:
            yield cause, until - at - stalled_s


def _slots(
    stay: WorkingStay, seen: list[dict[str, Any]], work: Collection[str], start: float, ended: float, stalled_s: float
) -> Iterable[tuple[str, float]]:
    """Each silence's seconds at or after `start` with the cause that held it: `working` inside `stalled_s`, else the
    cause it stalled on, the whole silence."""
    for at, until, cause in _silences(stay, seen, work, ended, stalled_s):
        if until > max(at, start):
            yield "working" if cause is None else cause[0], until - max(at, start)
