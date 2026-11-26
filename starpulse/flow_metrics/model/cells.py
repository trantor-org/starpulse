"""The kind x size cell of a board task, and what a session's cost fold adds to the skill-cost series.

A cell is the tasks whose board labels are `kind-<kind>` and `size-<size>`; a `batch-umbrella` is in none, and its
norm sums its members' cells. A cost row (`ledger.cost_of`) charges the
agent seconds of a task's steps to the skill in force on them; a task with no kind or no size label is in no cell.
`cost_increase` is what the skill-cost worker adds to its series from one fold to the next.
"""

from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["MIN_N", "cell_of", "cost_increase", "is_umbrella", "norm_cells", "profile_of"]

#: Clean completions a cell needs to report.
MIN_N = 5


def _label(labels: Iterable[str], prefix: str) -> str | None:
    return next((label.removeprefix(prefix) for label in labels if label.startswith(prefix)), None)


def cell_of(tasks: Mapping[str, Mapping[str, Any]], task: str | None) -> tuple[str, int] | None:
    labels = tasks.get(task or "", {}).get("labels") or ()
    kind, size = _label(labels, "kind-"), _label(labels, "size-")
    return (kind, int(size)) if kind and size and size.isdigit() else None


def is_umbrella(tasks: Mapping[str, Mapping[str, Any]], task: str | None) -> bool:
    return "batch-umbrella" in (tasks.get(task or "", {}).get("labels") or ())


def norm_cells(tasks: Mapping[str, Mapping[str, Any]], task: str) -> list[tuple[str, int] | None]:
    """The cells `task`'s norm sums: its own, or a `batch-umbrella`'s one per stored member (`members`, kind and size
    by key), None for a member the record holds no kind or size for; none for an umbrella with no record."""
    if not is_umbrella(tasks, task):
        return [cell_of(tasks, task)]
    return [
        (member["kind"], int(member["size"]))
        if member.get("kind") and str(member.get("size")).isdigit()
        else None
        for member in (tasks[task].get("members") or {}).values()
    ]


def profile_of(model: str, effort: str) -> str:
    """The profile a session ran as, `<model>-<effort>`, each `unknown` when unrecorded."""
    return f"{model or 'unknown'}-{effort or 'unknown'}"


def cost_increase(
    before: list[dict[str, Any]], after: list[dict[str, Any]], tasks: Mapping[str, Mapping[str, Any]]
) -> dict[tuple[str, int, str], tuple[float, int]]:
    """The agent seconds and the tasks newly entered per (kind, size, skill) that `after`, a session's `ledger.cost_of` rows,
    adds to `before`, its rows when last folded, never a negative sum; a task of no cell adds nothing."""
    held = {(row["task"], row["skill"]): row["agent_s"] for row in before}
    added: dict[tuple[str, int, str], tuple[float, int]] = {}
    for row in after:
        if (cell := cell_of(tasks, row["task"])) is None:
            continue
        key = (row["task"], row["skill"])
        seconds, entered = max(0.0, row["agent_s"] - held.get(key, 0.0)), key not in held
        if seconds or entered:
            was = added.get((*cell, row["skill"]), (0.0, 0))
            added[(*cell, row["skill"])] = (was[0] + seconds, was[1] + entered)
    return added
