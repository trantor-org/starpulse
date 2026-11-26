"""The spend report: per task and phase, the tokens a task burned and what they weigh against the task's cell.

A phase is a task's stretch of steps (`ledger.spend_of`, a subagent's counted to its task). A step under
`qa`, `deliver` or `review-fix` (`cr-triage` too) is that phase. A step before the session's first naming signal bills to no task. Every other step is `claim` until the step that
carries the task's claim, or the first step that edits a file when no claim is in the window, and `implement` after
it, over all the task's sessions in the window; a task with no edit and no claim in the window is all `implement`.
Loading `starting-task` stays in force through the build, so that skill alone cannot split the two.

`wte` weighs a step's tokens as the provider prices them against one uncached input token: a cache write 1.25, a
cache read 0.1, an output token 5. `task_wte` sums a task's phases. A cell (kind x size x row `profile`) of at least `MIN_N` tasks
has, per phase, a `phase_norm_wte`, the median `wte` of that phase over the cell's tasks that ran it; a row whose
profile cell is under `MIN_N` falls back to the mixed kind x size cell, and its `norm_profile` says which cell it
took (its own profile, `mixed`, or null with no norm). A phase over `FLAG_RATIO` times it is `phase_above_norm`. A task's `norm_wte` sums the norms of the phases it ran, so a qa round
is weighed against peers' qa, and a task over `FLAG_RATIO` times it is `above_norm`. A `batch-umbrella` task is in no
norm cell: its size counts the members it folds in, so its spend neither takes a norm nor skews its size's.

A row's `profile` is the `<model>-<effort>` of its first main-thread step, so a subagent's model does not stand for
the session's; a row of subagent steps alone takes its first step's.

A task's rows depend only on the sessions that name it (`named`), so `task_spend` reports one task from its own
sessions' folds and its peers' stored `phase_rows`.
"""

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping
from statistics import median
from typing import Any

from starpulse.flow_metrics.model.cells import MIN_N, cell_of, profile_of

__all__ = ["FLAG_RATIO", "combine_spend", "named", "phase_rows", "task_spend"]

#: A peer's phase row, as the norms weigh it: (task, phase) to its (profile, wte).
Peers = Mapping[tuple[str, str], tuple[str, float]]

#: How many times its cell's median a task's weighted tokens must reach to be flagged.
FLAG_RATIO = 3
_SKILL_PHASE = {"qa": "qa", "deliver": "deliver", "review-fix": "review_fix", "cr-triage": "review_fix"}
_CLASSES = ("input", "output", "cache_read", "cache_write")


def _wte(tokens: Mapping[str, int]) -> float:
    return tokens["input"] + 1.25 * tokens["cache_write"] + 0.1 * tokens["cache_read"] + 5 * tokens["output"]


def _phase(step: Mapping[str, Any], editing: bool) -> str:
    skill = step["skill"]
    if skill == "deliver" and step["edits"]:
        return "implement"
    return _SKILL_PHASE.get(skill) or ("implement" if editing else "claim")


def _phases(steps: list[dict[str, Any]], claims: Mapping[str, float]) -> list[tuple[str, dict[str, Any]]]:
    """Each of `steps` with its phase, `claims` the time each task was first claimed."""
    first_edit: dict[str, float] = {}
    for step in steps:
        if step["edits"]:
            first_edit.setdefault(step["task"], step["at"])
    return [
        (
            _phase(
                step,
                step["at"] > claims[step["task"]]
                if step["task"] in claims
                else step["at"] >= first_edit.get(step["task"], 0),
            ),
            step,
        )
        for step in steps
    ]


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
        "profile": "",
    }


def named(fold: Mapping[str, Any]) -> set[str]:
    """The tasks a session's `spend` fold bills a step, a claim or a compaction to: the tasks whose rows it changes."""
    return {step["task"] for step in fold["steps"]} | set(fold.get("claims", {})) | set(fold["compactions"])


def combine_spend(folds: Iterable[Mapping[str, Any]], tasks: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """the spend report of the sessions whose `ledger.spend_of` results `folds` holds, in the order the sessions are given:
    the whole-week reference each `task_spend` answer equals its task's rows of, read by the tests rather than a route."""
    return _flagged(phase_rows(folds), tasks, {})


def task_spend(
    folds: Iterable[Mapping[str, Any]], task: str, tasks: Mapping[str, Mapping[str, Any]], peers: Peers
) -> list[dict[str, Any]]:
    """`task`'s rows of the spend report, `folds` every session naming it in the order `combine_spend` takes them and
    `peers` the other tasks' phase rows its norms weigh it against."""
    return _flagged({key: row for key, row in phase_rows(folds).items() if key[0] == task}, tasks, peers)


def phase_rows(folds: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Each (task, phase) row the sessions' `folds` sum to, before the norms; exact for a task when `folds` holds every
    session that names it."""
    held = list(folds)
    steps = sorted((step for fold in held for step in fold["steps"]), key=lambda step: step["at"])
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    main_profiled: set[tuple[str, str]] = set()
    claims: dict[str, float] = {}
    for fold in held:
        for task, at in fold.get("claims", {}).items():
            claims[task] = min(at, claims.get(task, at))
    for phase, step in _phases(steps, claims):
        key = (step["task"], phase)
        row = rows.setdefault(key, _row(step["task"], phase))
        tokens = step["tokens"]
        row["steps"] += 1
        row["side_steps"] += step["origin"] == "side"
        for name in _CLASSES:
            row[name] += tokens[name]
        row["wte"] += _wte(tokens)
        row["peak_context"] = max(row["peak_context"], tokens["input"] + tokens["cache_read"] + tokens["cache_write"])
        row["models"].add(step["model"])
        if key not in main_profiled and (step["origin"] == "main" or not row["profile"]):
            row["profile"] = profile_of(step["model"], step["effort"])
            if step["origin"] == "main":
                main_profiled.add(key)
        row.setdefault("first_at", step["at"])
        row["last_at"] = step["at"]
    compactions: dict[str, list[float]] = defaultdict(list)
    for fold in held:
        for task, times in fold["compactions"].items():
            compactions[task] += times
    for task, times in compactions.items():
        phases = sorted((r for (t, _), r in rows.items() if t == task), key=lambda r: r["first_at"])
        if not phases:
            continue
        starts = [r["first_at"] for r in phases]
        for at in times:
            phases[max(bisect_right(starts, at) - 1, 0)]["compactions"] += 1
    return rows


def _flagged(
    rows: dict[tuple[str, str], dict[str, Any]], tasks: Mapping[str, Mapping[str, Any]], others: Peers
) -> list[dict[str, Any]]:
    """The `rows` with each task's cell, total, norm and flag, by task then first step; the norms are drawn over `rows`
    and the `others` of tasks `rows` does not hold."""
    total: dict[str, float] = defaultdict(float)
    for (task, _), row in rows.items():
        total[task] += row["wte"]
    weighed = {key: peer for key, peer in others.items() if key[0] not in total} | {
        key: (row["profile"], row["wte"]) for key, row in rows.items()
    }
    cells = {task: cell_of(tasks, task) or (None, None) for task, _ in weighed}
    peers = {
        task: (None, None) if "batch-umbrella" in (tasks.get(task, {}).get("labels") or ()) else cell
        for task, cell in cells.items()
    }
    own: dict[tuple[Any, str, str], list[float]] = defaultdict(list)
    mixed: dict[tuple[Any, str], list[float]] = defaultdict(list)
    for (task, phase), (profile, wte) in weighed.items():
        own[(peers[task], phase, profile)].append(wte)
        mixed[(peers[task], phase)].append(wte)

    def norm_of(task: str, phase: str) -> tuple[float | None, str | None]:
        cell = peers[task]
        if cell[0] is None:
            return None, None
        for values, used in (
            (own[(cell, phase, rows[(task, phase)]["profile"])], rows[(task, phase)]["profile"]),
            (mixed[(cell, phase)], "mixed"),
        ):
            if len(values) >= MIN_N:
                return median(values), used
        return None, None

    def why_none(task: str) -> str:
        if cells[task][0] is None:
            return "no kind or size"
        return "batch umbrella" if peers[task][0] is None else f"under {MIN_N} peers in kind × size"

    norm = {key: norm_of(*key) for key in rows}
    phase_norms: dict[str, list[float | None]] = defaultdict(list)
    for (task, _), (value, _) in norm.items():
        phase_norms[task].append(value)
    task_norm = {
        task: None if None in norms else sum(n for n in norms if n is not None) for task, norms in phase_norms.items()
    }
    return [
        {
            **{k: sorted(v) if isinstance(v, set) else v for k, v in row.items()},
            "kind": cells[task][0],
            "size": cells[task][1],
            "task_wte": total[task],
            "norm_wte": task_norm[task],
            "above_norm": task_norm[task] is not None and total[task] > FLAG_RATIO * task_norm[task],
            "phase_norm_wte": norm[(task, phase)][0],
            "norm_profile": norm[(task, phase)][1],
            "no_norm_reason": None if norm[(task, phase)][0] is not None else why_none(task),
            "phase_above_norm": norm[(task, phase)][0] is not None and row["wte"] > FLAG_RATIO * norm[(task, phase)][0],
        }
        for (task, phase), row in sorted(rows.items(), key=lambda kv: (kv[0][0], kv[1]["first_at"]))
    ]
