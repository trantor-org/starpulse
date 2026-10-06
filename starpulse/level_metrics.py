"""The level's flow numbers: WIP, throughput, time in state and aging on the Backlog flow metric definitions, plus the
shares and dwell the orbit card draws, from the runs of one machine merged across sources.

`level_metrics` is a pure function of the runs a history keeps (`HistoryStore.level_runs`), so a fixture history gives
numbers that can be worked out by hand. A run's `steps` are the states it entered and when; a run's first step is where
it was first seen, not a transition, so the stay before it is unknown and no completion or ending is counted for it. A
stay runs from one step to the next, and the stay a run is still in has no end and counts to `now`. History begins at
the first step any run holds: a window that reaches before it is refused, never answered with the missing days as zero.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from starpulse.level import Level

__all__ = ["UNATTRIBUTED", "Run", "WindowPastHistory", "level_metrics"]

#: The source of a run that no forwarder named: it counts in the aggregate and no one's Board holds it.
UNATTRIBUTED = "unattributed"
_DAY_S = 86400.0
#: Completions this far back set the aging threshold, whatever window the numbers are asked over.
_AGING_WINDOW_S = 12 * 7 * _DAY_S
_AGING_FRACTION = 0.85


class WindowPastHistory(ValueError):
    """The window reaches before the history begins; `history_s` is how much history there is."""

    def __init__(self, window_s: float, history_s: float) -> None:
        super().__init__(
            f"the window of {window_s / 3600:g} hours is longer than the history ({history_s / 3600:g} hours); "
            f"ask for at most {history_s / 3600:g}"
        )
        self.history_s = history_s


@dataclass(frozen=True)
class Run:
    """One task's trajectory on the level's machine: its reporting `source` and the `(at, state)` steps it took."""

    source: str
    task: str
    steps: tuple[tuple[float, str], ...]


def level_metrics(level: Level, machine: dict, runs: Iterable[Run], *, now: float, window_s: float) -> dict[str, Any]:
    """The level's numbers over the last `window_s` seconds up to `now`, for `runs` of `machine`.

    `wip` counts the runs now in a working state: the level's `orbit.working`, else each state that is neither the
    initial one nor a terminal. `throughput` is the entries into the goal inside the window. `time_in_state` clips
    each stay to the window. `aging` lists each working run's age since it first entered a working state, against the 85th-percentile cycle time of the completions of the
    trailing 12 weeks. `sources` carry each source's ended runs with their terminal shares, its dwell per working state
    with its time shares: a source with nothing ended or no working time has no shares, not zero ones. Raises
    `WindowPastHistory` when the window is longer than the history.
    """
    held = [(run, _collapse(run.steps)) for run in runs]
    first = min((steps[0][0] for _, steps in held if steps), default=now)
    if window_s > now - first:
        raise WindowPastHistory(window_s, now - first)
    start = now - window_s
    states = machine["states"]
    terminals = [terminal.id for terminal in level.terminals]
    working = list(level.orbit.working) or [
        s["id"] for s in states if not (s["initial"] or s["final"] or s["id"] in terminals)
    ]
    waiting = [s["id"] for s in states if not (s["final"] or s["id"] in terminals)]

    wip: dict[str, int] = defaultdict(int)
    ended = {id: dict.fromkeys(terminals, 0) for id in {run.source for run, _ in held}}
    time: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    working_runs: list[dict[str, Any]] = []
    cycles: list[float] = []
    completed = 0
    for run, steps in held:
        for (at, state), later in zip(steps, [*steps[1:], None], strict=True):
            if (stay := _clip(at, later[0] if later else None, start, now)) is not None:
                time[run.source][state].append(stay)
        for at, state in steps[1:]:
            if state in terminals and start <= at <= now:
                ended[run.source][state] += 1
            if state == level.goal and start <= at <= now:
                completed += 1
        if steps and steps[-1][1] in working:
            wip[steps[-1][1]] += 1
            began = next(at for at, state in steps if state in working)
            working_runs.append(
                {"source": run.source, "task": run.task, "state": steps[-1][1], "age_s": now - began, "began": began}
            )
        cycles.extend(_cycles(steps, working, level.goal, now))
    threshold = _nearest_rank(cycles, _AGING_FRACTION)

    totals = {
        state: [s for lengths in time.values() for s in lengths.get(state, [])]
        for state in dict.fromkeys([*waiting, *working])
    }
    return {
        "now": now,
        "window_s": window_s,
        "history_s": now - first,
        "machine": level.machine,
        "goal": level.goal,
        "wip": {"count": sum(wip.values()), "states": dict(wip)},
        "throughput": {"count": completed, "per_day": completed / (window_s / _DAY_S)},
        "time_in_state": [_stays(state, totals[state]) for state in waiting],
        "aging": {
            "threshold_s": threshold,
            "runs": [
                {k: v for k, v in entry.items() if k != "began"}
                | {"over": threshold is not None and entry["age_s"] > threshold}
                for entry in sorted(working_runs, key=lambda entry: entry["began"])
            ],
        },
        "orbit": {
            "suns": level.orbit.suns,
            "terminals": {id: {"ended": sum(by[id] for by in ended.values())} for id in terminals},
            "working": {state: {"task_s": sum(totals[state])} for state in working},
        },
        "sources": [
            _source(id, ended[id], time[id], working, sum(1 for e in working_runs if e["source"] == id))
            for id in sorted(ended)
        ],
    }


def _collapse(steps: Sequence[tuple[float, str]]) -> list[tuple[float, str]]:
    """The steps oldest first, a step that repeats the state before it dropped: staying put is no transition."""
    kept: list[tuple[float, str]] = []
    for at, state in sorted(steps, key=lambda step: step[0]):
        if not kept or kept[-1][1] != state:
            kept.append((at, state))
    return kept


def _clip(began: float, ended: float | None, start: float, now: float) -> float | None:
    """The seconds of the stay `began` to `ended` (None: still going) inside `start` to `now`, None when none."""
    low, high = max(began, start), min(now if ended is None else ended, now)
    return high - low if high > low else None


def _stays(state: str, lengths: list[float]) -> dict[str, Any]:
    total = sum(lengths)
    return {"id": state, "visits": len(lengths), "task_s": total, "mean_s": total / len(lengths) if lengths else None}


def _cycles(steps: list[tuple[float, str]], working: list[str], goal: str, now: float) -> Iterable[float]:
    """Each completion of the trailing 12 weeks as seconds from the run's first working step; none if unobserved."""
    began = next((at for at, state in steps if state in working), None)
    if began is None:
        return
    for at, state in steps[1:]:
        if state == goal and now - _AGING_WINDOW_S <= at <= now and began <= at:
            yield at - began


def _nearest_rank(values: list[float], fraction: float) -> float | None:
    """The smallest value whose 1-based rank is at least `fraction` of the count, None for no values."""
    ranked = sorted(values)
    return next((value for rank, value in enumerate(ranked, 1) if rank >= fraction * len(ranked)), None)


def _source(
    id: str, ended: dict[str, int], time: dict[str, list[float]], working: list[str], wip: int
) -> dict[str, Any]:
    dwell = {state: _stays(state, time[state]) for state in working if time.get(state)}
    worked = sum(entry["task_s"] for entry in dwell.values())
    runs_ended = sum(ended.values())
    return {
        "id": id,
        "wip": wip,
        "ended": ended,
        "terminal_share": {t: n / runs_ended for t, n in ended.items()} if runs_ended else {},
        "dwell": {state: {k: v for k, v in entry.items() if k != "id"} for state, entry in dwell.items()},
        "time_share": {state: entry["task_s"] / worked for state, entry in dwell.items()} if worked else {},
    }
