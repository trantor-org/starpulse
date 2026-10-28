"""Board health from a history's lane changes: dwell and WIP per state, throughput and stuck tasks over a window.

`stay_health` is a pure function of the lane stays the history keeps (`lane_stays` over `HealthHistory.lane_rows`), a lane named by
its state's name or id, so a fixture history gives numbers that can be worked out by hand. A task's stay in a state
runs from the lane change into it to the next change; the stay of a task still in its state has no end, so it is
counted to `now` and flagged (`open`, `counted_to_now`). History begins at a task's first recorded change: where the
task was before it is unknown, so that earlier stay is not counted.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from starpulse.machine_engine.model.stays import Dwell, LaneStays

_DAY_S = 86400.0


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
    states = {key: state for state in machine["states"] for key in (state["name"], state["id"])}
    wip: dict[str, int] = defaultdict(int)
    for lane, tasks in held.open_by_lane.items():
        if (state := states.get(lane)) is not None:
            wip[state["id"]] += tasks
    dwell: dict[str, Dwell] = {}
    open_stays: dict[str, int] = defaultdict(int)
    stuck: list[dict[str, Any]] = []

    def visited(state_id: str, found: Dwell) -> None:
        before = dwell.get(state_id, Dwell(0, 0.0, found.longest))
        dwell[state_id] = Dwell(
            before.visits + found.visits, before.total + found.total, max(before.longest, found.longest)
        )

    for lane, found in held.ended.items():
        if (state := states.get(lane)) is not None and not state["final"]:
            visited(state["id"], found)
    for lane, found in held.going.items():
        if (state := states.get(lane)) is not None and not state["final"]:
            visited(state["id"], found)
            open_stays[state["id"]] += found.visits
    for task, lane, began, _ended in held.stuck:
        state = states.get(lane)
        if state is None or state["final"] or state["initial"]:
            continue
        length = now - began
        if length >= stuck_s:
            stuck.append(
                {"task": task, "state": state["id"], "since": began, "dwell_s": length, "counted_to_now": True}
            )
    done = sum(n for lane, n in held.entered.items() if (state := states.get(lane)) is not None and state["final"])
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


def _state(state: dict, wip: dict[str, int], dwell: dict[str, Dwell], open_stays: dict[str, int]) -> dict:
    entry = {"id": state["id"], "name": state["name"], "final": state["final"], "wip": wip[state["id"]]}
    if state["final"]:
        return entry
    found = dwell.get(state["id"])
    return entry | {
        "visits": found.visits if found else 0,
        "mean_s": found.total / found.visits if found else None,
        "max_s": found.longest if found else None,
        "open": open_stays[state["id"]],
    }


def _gap_message(gap: dict) -> str:
    return (
        f"{gap['lost']} entries of {gap['stream']} between {gap['after_id']} and {gap['before_id']} were trimmed "
        "before the history read them, so counts and dwell may miss them"
    )


def _lane_message(lane: str) -> str:
    return f"lane {lane!r} is not a state of the Board machine, so its stays are not counted"
