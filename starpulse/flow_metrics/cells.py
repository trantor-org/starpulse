"""Per-transition cost and the cell report, for each kind x size cell of the board's tasks.

`transition_cost` charges every model request to the skill in force on it (`starpulse.flow_metrics.steps`), inside
the kind x size cell of the task it worked. A subagent's requests carry the parent's session and so count toward the
task that spawned it (`side_steps` of `steps` are those); a compaction's own call is no step. A step is *wasted* when
a call it owns failed, was refused by a guard or hook, or repeats the shell command of the call before it in its
session. `agent_s` is its requests' and calls' seconds and `peak_context` the most input, cache read and cache write
tokens one request held. A step of a task with no kind or no size label, or of a Codex session, is in no row.

The cell report: median steps per clean completion for each kind x size cell of the board's tasks.

A cell is the tasks whose board labels are `kind-<kind>` and `size-<size>`. Its members are the task slices
(`starpulse.flow_metrics.session_health.slice_health`) that completed, left out when a Codex session worked them, which
the steps ledger does not cover. A slice that completed *clean* counts toward the cell; the others only lower its
`clean_rate`, completions that were clean over completions.

The cell reports nothing under `MIN_N` clean completions. Otherwise its `holdout` is the latest fifth of them, rounded
up, by the end of their last session, and the medians are the holdout's: `median_steps` (main and subagent requests)
and `median_steps_before_edit`. A clean completion has no human prompt after the claim, so `median_operator_prompts`
(human prompts after the claim) is the median of the latest fifth of all the cell's completions, clean or not, the
same share of them by the same end time. A cell can improve because its tasks got easier, so the report carries `n`, `completions` and `clean_rate` beside them.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from math import ceil
from statistics import median
from typing import Any

from starpulse._internal.analytics import Analytics
from starpulse._internal.signals import CLAUDE_CODE, Signal
from starpulse.contracts.adapters import TaskKeys
from starpulse.flow_metrics.steps import owned_steps

__all__ = ["MIN_N", "cell_of", "cell_report", "transition_cost"]

#: Clean completions a cell needs to report.
MIN_N = 5
_HOLDOUT = 5


def _label(labels: Iterable[str], prefix: str) -> str | None:
    return next((label.removeprefix(prefix) for label in labels if label.startswith(prefix)), None)


def _median(values: Iterable[int | None]) -> float | None:
    held = [v for v in values if v is not None]
    return median(held) if held else None


def cell_report(slices: Iterable[dict[str, Any]], tasks: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per kind x size cell of the slices `slices` with `MIN_N` clean completions, by kind then size.

    `tasks` maps a task key to its board entry, whose `labels` name its kind and size; a task with either missing is in
    no cell."""
    cells: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for s in slices:
        labels = tasks.get(s["task"], {}).get("labels") or ()
        kind, size = _label(labels, "kind-"), _label(labels, "size-")
        if s["complete"] and kind and size and size.isdigit() and set(s["harnesses"]) == {CLAUDE_CODE}:
            cells[kind, int(size)].append(s)
    rows = []
    for (kind, size), completed in sorted(cells.items()):
        clean = sorted((s for s in completed if s["clean"]), key=lambda s: (s["last_at"], s["task"]))
        if len(clean) < MIN_N:
            continue
        holdout = clean[-ceil(len(clean) / _HOLDOUT) :]
        latest = sorted(completed, key=lambda s: (s["last_at"], s["task"]))[-ceil(len(completed) / _HOLDOUT) :]
        rows.append(
            {
                "kind": kind,
                "size": size,
                "n": len(clean),
                "completions": len(completed),
                "clean_rate": len(clean) / len(completed),
                "holdout": len(holdout),
                "median_steps": _median(s["steps"] + s["side_steps"] for s in holdout),
                "median_operator_prompts": _median(s["operator_prompts"] for s in latest),
                "median_steps_before_edit": _median(s["steps_before_edit"] for s in holdout),
            }
        )
    return rows


def cell_of(tasks: Mapping[str, Mapping[str, Any]], task: str | None) -> tuple[str, int] | None:
    labels = tasks.get(task or "", {}).get("labels") or ()
    kind, size = _label(labels, "kind-"), _label(labels, "size-")
    return (kind, int(size)) if kind and size and size.isdigit() else None


def _repeats(calls: Iterable[Signal]) -> set[str]:
    """The keys of the shell results among `calls`, oldest first, whose command is the one of the call before."""
    repeated, before = set(), None
    for call in sorted((c for c in calls if c.kind == "tool"), key=lambda c: c.time):
        if call.command and call.command == before:
            repeated.add(call.key)
        before = call.command or None
    return repeated


def transition_cost(
    found: Iterable[Signal],
    keys: TaskKeys | None,
    tasks: Mapping[str, Mapping[str, Any]],
    analytics: Analytics | None = None,
) -> list[dict[str, Any]]:
    """One row per (kind, size, skill) of the steps of `found`, by kind, size, then skill; see the module docstring."""
    owned = [o for o in owned_steps(found, keys, analytics) if o.step["captured"] and o.step["origin"] != "auxiliary"]
    by_session: dict[tuple[str, str], list[Signal]] = defaultdict(list)
    for o in owned:
        by_session[o.step["harness"], o.step["session"]] += o.calls
    repeated = set().union(*map(_repeats, by_session.values()))
    cost: dict[tuple[str, int, str], dict[str, Any]] = {}
    for o in owned:
        if (cell := cell_of(tasks, o.step["task"])) is None:
            continue
        row = cost.setdefault(
            (*cell, o.step["skill"]),
            {
                "kind": cell[0],
                "size": cell[1],
                "skill": o.step["skill"],
                "tasks": set(),
                "steps": 0,
                "side_steps": 0,
                "wasted_steps": 0,
                "agent_s": 0.0,
                "peak_context": 0,
            },
        )
        tokens = o.step["tokens"]
        row["tasks"].add(o.step["task"])
        row["steps"] += 1
        row["side_steps"] += o.step["origin"] == "side"
        row["wasted_steps"] += any((c.kind in {"tool", "decision"} and not c.ok) or c.key in repeated for c in o.calls)
        row["agent_s"] += o.seconds + sum(c.seconds for c in o.calls if c.kind == "tool")
        row["peak_context"] = max(row["peak_context"], tokens["input"] + tokens["cache_read"] + tokens["cache_write"])
    return [
        {**row, "tasks": len(row["tasks"]), "wasted_rate": row["wasted_steps"] / row["steps"]}
        for _, row in sorted(cost.items())
    ]
