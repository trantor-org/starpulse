"""Board health from a history's lane changes: dwell and WIP per state, throughput and stuck tasks over a window.

`board_health` is a pure function of the lane changes the history keeps (`HealthHistory.lane_rows`), a lane named by
its state's name or id, so a fixture history gives numbers that can be worked out by hand. A task's stay in a state
runs from the lane change into it to the next change; the stay of a task still in its state has no end, so it is
counted to `now` and flagged (`open`, `counted_to_now`). History begins at a task's first recorded change: where the
task was before it is unknown, so that earlier stay is not counted.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

from starpulse.upstream_backlog import lane_id

#: A lane change as the history keeps it: `(task, at, from, to)`, `at` in epoch seconds.
LaneRow = tuple[str, float, str | None, str]
_DAY_S = 86400.0


class Stay(NamedTuple):
    """One task's stay in a lane from `began` to `ended`, which is None while it is still there."""

    task: str
    lane: str
    began: float
    ended: float | None


@dataclass(frozen=True)
class LaneStays:
    """What `stay_health` reads of a lane history, enough to answer for a window without every stay ever kept.

    `stays` hold every stay that ended in the window or is still going in a state that is not final, and every entry
    into a final state in it; more are harmless. `open_by_lane` is how many tasks are in each lane now, and `lanes`
    every lane the history has recorded.
    """

    stays: Sequence[Stay]
    open_by_lane: Mapping[str, int]
    lanes: Sequence[str]


def _stays(rows: Iterable[LaneRow]) -> Iterable[Stay]:
    """Each task's stays, oldest first; the stay it is still in has no end."""
    by_task: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for task, at, _old, new in rows:
        by_task[task].append((at, new))
    for task, changes in by_task.items():
        changes.sort(key=lambda change: change[0])
        for (start, lane), later in zip(changes, [*changes[1:], None]):
            yield Stay(task, lane, start, later[0] if later else None)


def lane_stays(rows: Iterable[LaneRow]) -> LaneStays:
    """Every stay `rows` hold, with the tasks now in each lane and the lanes in the order they first appear."""
    stays = list(_stays(rows))
    return LaneStays(
        stays, Counter(stay.lane for stay in stays if stay.ended is None), list(dict.fromkeys(s.lane for s in stays))
    )


def board_health(
    machine: dict, rows: Iterable[LaneRow], gaps: list[dict], *, now: float, window_s: float, stuck_s: float
) -> dict[str, Any]:
    """The Board `machine`'s health over the last `window_s` seconds up to `now`, from lane changes `rows`; see
    `stay_health`."""
    return stay_health(machine, lane_stays(rows), gaps, now=now, window_s=window_s, stuck_s=stuck_s)


def stay_health(
    machine: dict, held: LaneStays, gaps: list[dict], *, now: float, window_s: float, stuck_s: float
) -> dict[str, Any]:
    """The Board `machine`'s health over the last `window_s` seconds up to `now`, from the lane stays `held`.

    `states` lists each state with `wip`, the tasks in it now, and for a state that is not final `visits`, `mean_s` and
    `max_s` of the stays that ended inside the window or are still going (`open` of them, counted to `now`).
    `throughput` is the entries into a final state inside the window. `stuck` is each task whose current stay in a
    state that is neither the initial nor a final one has lasted `stuck_s` or longer, longest first. `warnings` carry
    the history's recorded gaps, which mean any number here may miss entries, and each lane that is no Board state.
    """
    start = now - window_s
    states = {key: state for state in machine["states"] for key in (state["name"], state["id"])}
    wip: dict[str, int] = defaultdict(int)
    for lane, tasks in held.open_by_lane.items():
        if (state := states.get(lane)) is not None:
            wip[state["id"]] += tasks
    dwell: dict[str, list[float]] = defaultdict(list)
    open_stays: dict[str, int] = defaultdict(int)
    stuck: list[dict[str, Any]] = []
    done = 0
    for task, lane, began, ended in held.stays:
        if (state := states.get(lane)) is None:
            continue
        if state["final"]:
            done += start <= began <= now
            continue
        if ended is not None and ended < start:
            continue
        length = (now if ended is None else ended) - began
        dwell[state["id"]].append(length)
        if ended is None:
            open_stays[state["id"]] += 1
            if not state["initial"] and length >= stuck_s:
                stuck.append(
                    {"task": task, "state": state["id"], "since": began, "dwell_s": length, "counted_to_now": True}
                )
    unknown = [lane for lane in held.lanes if lane not in states]
    return {
        "now": now,
        "window_s": window_s,
        "stuck_after_s": stuck_s,
        "states": [_state(state, wip, dwell, open_stays) for state in machine["states"]],
        "throughput": {"count": done, "per_day": done / (window_s / _DAY_S)},
        "stuck": sorted(stuck, key=lambda entry: -entry["dwell_s"]),
        "warnings": [
            *({"kind": "gap", **gap, "message": _gap_message(gap)} for gap in gaps),
            *({"kind": "unknown_lane", "lane": lane, "message": _lane_message(lane)} for lane in unknown),
        ],
    }


def _state(state: dict, wip: dict[str, int], dwell: dict[str, list[float]], open_stays: dict[str, int]) -> dict:
    entry = {"id": state["id"], "name": state["name"], "final": state["final"], "wip": wip[state["id"]]}
    if state["final"]:
        return entry
    lengths = dwell[state["id"]]
    return entry | {
        "visits": len(lengths),
        "mean_s": sum(lengths) / len(lengths) if lengths else None,
        "max_s": max(lengths, default=None),
        "open": open_stays[state["id"]],
    }


def _gap_message(gap: dict) -> str:
    return (
        f"{gap['lost']} entries of {gap['stream']} between {gap['after_id']} and {gap['before_id']} were trimmed "
        "before the history read them, so counts and dwell may miss them"
    )


def _lane_message(lane: str) -> str:
    return f"lane {lane!r} is not a state of the Board machine, so its stays are not counted"


def move_shares(machine: dict, rows: Iterable[LaneRow], *, start: float, end: float) -> dict[str, float]:
    """Each Board state's share of the lane moves in `[start, end)`, from lane changes `rows`.

    A move counts toward the state it left and the state it entered, so a state's share is its part of the traffic
    through the Board; a first sighting enters a state and leaves none. A lane that is no state of `machine` counts
    toward none; a status counts for the state its `lane_id` names, so "Needs attention" is "Needs Attention". The shares sum to 1, or are all 0 when the window holds no move.
    """
    states = {key: state["id"] for state in machine["states"] for key in (state["name"], state["id"])}
    counts = dict.fromkeys((state["id"] for state in machine["states"]), 0)
    for _task, at, old, new in rows:
        if start <= at < end:
            for lane in filter(None, (old, new)):
                if (state := states.get(lane) or states.get(lane_id(lane))) is not None:
                    counts[state] += 1
    total = sum(counts.values())
    return {state: count / total if total else 0.0 for state, count in counts.items()}
