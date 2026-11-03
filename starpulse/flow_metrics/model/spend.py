"""The spend report: per task and phase, the tokens a task burned and what they weigh against the task's cell.

A phase is a task's stretch of steps (`steps.session_owned`, a subagent's counted to its task). A step under
`qa`, `deliver` or `review-fix` (`cr-triage` too) is that phase. Every other step is `claim` until the first step
that edits a file and `implement` from it, over all the task's sessions in the window; a task with no edit in the
window is all `implement`. Loading `starting-task` stays in force through the build, so that skill alone cannot
split the two.

`wte` weighs a step's tokens as the provider prices them against one uncached input token: a cache write 1.25, a
cache read 0.1, an output token 5. `task_wte` sums a task's phases. A cell (kind x size) of at least `MIN_N` tasks
has a `norm_wte`, the median `task_wte`, and a task over `FLAG_RATIO` times it is `above_norm`.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping
from statistics import median
from typing import Any

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import Signal
from starpulse.flow_metrics.model.cells import MIN_N, cell_of
from starpulse.flow_metrics.model.session_health import attributed, by_session, session_signals
from starpulse.flow_metrics.model.steps import Owned, session_owned

__all__ = ["FLAG_RATIO", "spend_report"]

#: How many times its cell's median a task's weighted tokens must reach to be flagged.
FLAG_RATIO = 3
_EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace"}
_SKILL_PHASE = {"qa": "qa", "deliver": "deliver", "review-fix": "review_fix", "cr-triage": "review_fix"}
_CLASSES = ("input", "output", "cache_read", "cache_write")


def _wte(tokens: Mapping[str, int]) -> float:
    return tokens["input"] + 1.25 * tokens["cache_write"] + 0.1 * tokens["cache_read"] + 5 * tokens["output"]


def _edits(owned: Owned) -> bool:
    return any(call.kind == "tool" and call.name in _EDITS for call in owned.calls)


def _owned_steps(found: Iterable[Signal], keys: TaskKeys | None, analytics: Analytics | None) -> list[Owned]:
    """The captured, non-auxiliary steps of every session in `found` that belong to a task, oldest first."""
    steps = [
        o
        for group in by_session(found)
        for o in session_owned(group, keys, analytics)
        if o.step["captured"] and o.step["origin"] != "auxiliary" and o.step["task"]
    ]
    return sorted(steps, key=lambda o: o.step["at"])


def _compactions(found: Iterable[Signal], keys: TaskKeys | None, analytics: Analytics | None) -> dict[str, list[float]]:
    """The times of each task's compactions."""
    times: dict[str, list[float]] = defaultdict(list)
    for group in by_session(found):
        for task, s in attributed(session_signals(group, keys, analytics), keys):
            if task and s.kind == "compaction":
                times[task].append(s.time)
    return times


def _phase(step: dict[str, Any], editing: bool) -> str:
    return _SKILL_PHASE.get(step["skill"]) or ("implement" if editing else "claim")


def _phases(steps: list[Owned]) -> list[tuple[str, Owned]]:
    """Each of `steps` with its phase."""
    first_edit: dict[str, float] = {}
    for o in steps:
        if _edits(o):
            first_edit.setdefault(o.step["task"], o.step["at"])
    return [(_phase(o.step, o.step["at"] >= first_edit.get(o.step["task"], 0)), o) for o in steps]


def _row(task: str, phase: str) -> dict[str, Any]:
    return {
        "task": task,
        "phase": phase,
        "steps": 0,
        "side_steps": 0,
        **dict.fromkeys(_CLASSES, 0),
        "wte": 0.0,
        "peak_context": 0,
        "compactions": 0,
        "models": set(),
    }


def spend_report(
    found: Iterable[Signal],
    keys: TaskKeys | None,
    tasks: Mapping[str, Mapping[str, Any]],
    analytics: Analytics | None = None,
) -> list[dict[str, Any]]:
    """One row per (task, phase) of the steps of `found`, by task then the phase's first step; see the module
    docstring."""
    signals = list(found)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for phase, o in _phases(_owned_steps(signals, keys, analytics)):
        step = o.step
        row = rows.setdefault((step["task"], phase), _row(step["task"], phase))
        tokens = step["tokens"]
        row["steps"] += 1
        row["side_steps"] += step["origin"] == "side"
        for name in _CLASSES:
            row[name] += tokens[name]
        row["wte"] += _wte(tokens)
        row["peak_context"] = max(row["peak_context"], tokens["input"] + tokens["cache_read"] + tokens["cache_write"])
        row["models"].add(step["model"])
        row.setdefault("first_at", step["at"])
        row["last_at"] = step["at"]
    for task, times in _compactions(signals, keys, analytics).items():
        phases = sorted((r for (t, _), r in rows.items() if t == task), key=lambda r: r["first_at"])
        if not phases:
            continue
        starts = [r["first_at"] for r in phases]
        for at in times:
            phases[max(bisect_right(starts, at) - 1, 0)]["compactions"] += 1
    return _flagged(rows, tasks)


def _flagged(
    rows: dict[tuple[str, str], dict[str, Any]], tasks: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """The `rows` with each task's cell, total, norm and flag, by task then first step."""
    total: dict[str, float] = defaultdict(float)
    for (task, _), row in rows.items():
        total[task] += row["wte"]
    cells = {task: cell_of(tasks, task) or (None, None) for task in total}
    in_cell: dict[Any, list[float]] = defaultdict(list)
    for task, cell in cells.items():
        in_cell[cell].append(total[task])
    norm = {
        cell: median(values) if cell[0] is not None and len(values) >= MIN_N else None
        for cell, values in in_cell.items()
    }
    return [
        {
            **{k: sorted(v) if isinstance(v, set) else v for k, v in row.items()},
            "kind": cells[task][0],
            "size": cells[task][1],
            "task_wte": total[task],
            "norm_wte": norm[cells[task]],
            "above_norm": norm[cells[task]] is not None and total[task] > FLAG_RATIO * norm[cells[task]],
        }
        for (task, _), row in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[1]["first_at"]))
    ]
