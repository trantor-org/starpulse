"""Board health from a history's lane changes: dwell and WIP per state, throughput and stuck tasks over a window.

`board_health` is a pure function of the lane changes the history keeps (`HealthHistory.lane_rows`), a lane named by
its state's name or id, so a fixture history gives numbers that can be worked out by hand. A task's stay in a state
runs from the lane change into it to the next change; the stay of a task still in its state has no end, so it is
counted to `now` and flagged (`open`, `counted_to_now`). History begins at a task's first recorded change: where the
task was before it is unknown, so that earlier stay is not counted.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

#: A lane change as the history keeps it: `(task, at, from, to)`, `at` in epoch seconds.
LaneRow = tuple[str, float, str | None, str]
_DAY_S = 86400.0


def _stays(rows: Iterable[LaneRow]) -> Iterable[tuple[str, str, float, float | None]]:
    """Each task's `(task, lane, start, end)` stays, oldest first; the stay it is still in has no end."""
    by_task: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for task, at, _old, new in rows:
        by_task[task].append((at, new))
    for task, changes in by_task.items():
        changes.sort(key=lambda change: change[0])
        for (start, lane), later in zip(changes, [*changes[1:], None]):
            yield task, lane, start, later[0] if later else None


def board_health(
    machine: dict, rows: Iterable[LaneRow], gaps: list[dict], *, now: float, window_s: float, stuck_s: float
) -> dict[str, Any]:
    """The Board `machine`'s health over the last `window_s` seconds up to `now`, from lane changes `rows`.

    `states` lists each state with `wip`, the tasks in it now, and for a state that is not final `visits`, `mean_s` and
    `max_s` of the stays that ended inside the window or are still going (`open` of them, counted to `now`).
    `throughput` is the entries into a final state inside the window. `stuck` is each task whose current stay in a
    state that is neither the initial nor a final one has lasted `stuck_s` or longer, longest first. `warnings` carry
    the history's recorded gaps, which mean any number here may miss entries, and each lane that is no Board state.
    """
    start = now - window_s
    states = {key: state for state in machine["states"] for key in (state["name"], state["id"])}
    wip: dict[str, int] = defaultdict(int)
    dwell: dict[str, list[float]] = defaultdict(list)
    open_stays: dict[str, int] = defaultdict(int)
    stuck: list[dict[str, Any]] = []
    done = 0
    unknown: dict[str, None] = {}
    for task, lane, began, ended in _stays(rows):
        if (state := states.get(lane)) is None:
            unknown[lane] = None
            continue
        if state["final"]:
            done += start <= began <= now
            wip[state["id"]] += ended is None
            continue
        if ended is not None and ended < start:
            continue
        length = (now if ended is None else ended) - began
        dwell[state["id"]].append(length)
        if ended is None:
            wip[state["id"]] += 1
            open_stays[state["id"]] += 1
            if not state["initial"] and length >= stuck_s:
                stuck.append(
                    {"task": task, "state": state["id"], "since": began, "dwell_s": length, "counted_to_now": True}
                )
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
