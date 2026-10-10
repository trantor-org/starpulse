"""Session health and slice health: what one agent session did, and what the sessions that worked one task did together.

`session_health` is a pure fold of the `Signal`s the harness exports carry (`starpulse._internal.harnesses.telemetry`),
so a recorded export gives numbers that can be worked out by hand. A session is one harness's session id; it yields one
row per task it worked, in the order it reached them.

The task a signal belongs to is the one the export's launch branch names under the board's `TaskKeys`, until a `branch`
signal (a shell's `git switch` or `git checkout`) names another task. A switch to a ref that names no task leaves the
task as it was, so `git checkout -- file` or a trip back to `main` does not drop a session's work from its slice. A
session whose branch names no task is a row with `task` None, counted in session health and in no slice.

Time is the gaps between a session's consecutive signals, each given to the row of the later signal:

- `operator_wait_s`: the gap that ends at a human prompt other than the session's first.
- `idle_s`: any other gap longer than `IDLE_S`, a wait the export cannot name (a background task, a permission prompt).
- `agent_s`: every other gap.

The exports mark neither a turn's end nor a pending background task, so a wait for a background task is `agent_s` up to
`IDLE_S` and `idle_s` beyond it.

`operator_prompts` are the human prompts after a session's first; its first starts the work. `interrupts` are the interrupted turns Codex exports. `interventions` of a slice are its operator prompts plus interrupts, and it is
`escalated` when a model or effort changed between a session's main-thread requests. A slice is `clean` when one
session did its work with no intervention and no escalation; whether it settled in Review or Done is the board's fact,
which the reader joins.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from typing import Any

from starpulse._internal.level.signals import CODEX, Signal
from starpulse.contracts.adapters import TaskKeys

__all__ = ["IDLE_S", "attributed", "grouped", "session_health", "session_kind", "slice_health"]

#: A gap in a session's signals longer than this is idle time, not the agent's.
IDLE_S = 600.0
_TOKENS = ("input", "output", "cache_read", "cache_write", "reasoning")
#: `originator` values of Codex's interactive front ends; `codex_exec` is its headless one.
_CODEX_INTERACTIVE = {"codex-tui", "codex_cli_rs"}


def session_kind(session: list[Signal]) -> str:
    """`interactive`, `headless` or `unknown`: how the session was driven, from its first signals that say."""
    for s in session:
        if s.kind == "start" and s.harness == CODEX:
            return (
                "headless"
                if s.detail == "codex_exec"
                else "interactive"
                if s.detail in _CODEX_INTERACTIVE
                else "unknown"
            )
        if s.kind == "request" and s.detail in {"sdk", "repl_main_thread"}:
            return "headless" if s.detail == "sdk" else "interactive"
    return "unknown"


def _empty(s: Signal, task: str | None, kind: str) -> dict[str, Any]:
    return {
        "harness": s.harness,
        "session": s.session,
        "task": task,
        "kind": kind,
        "first_at": s.time,
        "last_at": s.time,
        "prompts": 0,
        "operator_prompts": 0,
        "requests": 0,
        "side_requests": 0,
        "tool_calls": 0,
        "tool_failures": 0,
        "tools": {},
        "rejections": {},
        "skills": {},
        "compactions": {},
        "interrupts": 0,
        "models": [],
        "efforts": [],
        "model_changes": 0,
        "effort_changes": 0,
        "tokens": dict.fromkeys(_TOKENS, 0),
        "cost_usd": None,
        "agent_s": 0.0,
        "operator_wait_s": 0.0,
        "idle_s": 0.0,
    }


def _count(row: dict[str, Any], key: str, name: str) -> None:
    row[key][name] = row[key].get(name, 0) + 1


def _note_request(row: dict[str, Any], s: Signal, last: dict[str, str]) -> None:
    if s.origin in {"main", "side"}:
        row["requests" if s.origin == "main" else "side_requests"] += 1
    for name, value in (("models", s.model), ("efforts", s.effort)):
        if value and value not in row[name]:
            row[name].append(value)
    if s.origin == "main":
        for field, change in (("model", "model_changes"), ("effort", "effort_changes")):
            value = getattr(s, field)
            if value and last.get(field) and value != last[field]:
                row[change] += 1
            if value:
                last[field] = value
    for token in _TOKENS:
        row["tokens"][token] += getattr(s, token)
    if s.cost is not None:
        row["cost_usd"] = (row["cost_usd"] or 0.0) + s.cost


def _note(row: dict[str, Any], s: Signal, last: dict[str, str]) -> None:
    if s.kind == "request":
        _note_request(row, s, last)
    elif s.kind == "tool":
        row["tool_calls"] += 1
        row["tool_failures"] += int(not s.ok)
        _count(row, "tools", s.name)
    elif s.kind == "decision" and not s.ok:
        _count(row, "rejections", s.detail or "unknown")
    elif s.kind == "skill":
        _count(row, "skills", s.name)
    elif s.kind == "compaction":
        _count(row, "compactions", s.name or "unknown")
    elif s.kind == "interrupt":
        row["interrupts"] += 1


def grouped(found: Iterable[Signal]) -> list[list[Signal]]:
    """The signals `found` as one list per harness session, each oldest first."""
    sessions: dict[tuple[str, str], list[Signal]] = defaultdict(list)
    for s in found:
        sessions[s.harness, s.session].append(s)
    return [sorted(group, key=lambda s: s.time) for group in sessions.values()]


def attributed(ordered: list[Signal], keys: TaskKeys | None) -> Iterator[tuple[str | None, Signal]]:
    """Each signal of one session, oldest first, with the task it belongs to (see the module docstring)."""
    task = keys.for_branch(ordered[0].branch) if keys else None
    for s in ordered:
        if s.kind == "branch" and keys and (named := keys.for_branch(s.name)) is not None:
            task = named
        yield task, s


def session_health(found: Iterable[Signal], keys: TaskKeys | None) -> list[dict[str, Any]]:
    """One row per (session, task) of the sessions `found` holds, oldest first; see the module docstring."""
    rows: list[dict[str, Any]] = []
    for ordered in grouped(found):
        kind = session_kind(ordered)
        row: dict[str, Any] | None = None
        by_task: dict[str | None, dict[str, Any]] = {}
        last: dict[str, dict[str, str]] = defaultdict(dict)
        prompts = 0
        before = ordered[0].time
        for task, s in attributed(ordered, keys):
            if row is None or row["task"] != task:
                row = by_task.get(task) or by_task.setdefault(task, _empty(s, task, kind))
            gap, before = s.time - before, s.time
            if s.kind == "prompt":
                prompts += 1
                row["prompts"] += 1
                row["operator_prompts"] += int(prompts > 1)
            if s.kind == "prompt" and prompts > 1:
                row["operator_wait_s"] += gap
            elif gap > IDLE_S:
                row["idle_s"] += gap
            else:
                row["agent_s"] += gap
            row["last_at"] = s.time
            _note(row, s, last[task or ""])
        rows += by_task.values()
    return sorted(rows, key=lambda r: (r["first_at"], r["harness"], r["session"]))


def slice_health(sessions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per task of the session rows `sessions`, oldest first; rows with no task are in none."""
    by_task: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sessions:
        if row["task"] is not None:
            by_task[row["task"]].append(row)
    slices = []
    for task, rows in by_task.items():
        tokens = Counter[str]()
        skills = Counter[str]()
        for row in rows:
            tokens.update(row["tokens"])
            skills.update(row["skills"])
        costs = [row["cost_usd"] for row in rows if row["cost_usd"] is not None]
        operator_prompts = sum(row["operator_prompts"] for row in rows)
        interrupts = sum(row["interrupts"] for row in rows)
        changes = sum(row["model_changes"] + row["effort_changes"] for row in rows)
        count = len({(row["harness"], row["session"]) for row in rows})
        slices.append(
            {
                "task": task,
                "sessions": count,
                "harnesses": sorted({row["harness"] for row in rows}),
                "first_at": min(row["first_at"] for row in rows),
                "last_at": max(row["last_at"] for row in rows),
                "models": list(dict.fromkeys(m for row in rows for m in row["models"])),
                "efforts": list(dict.fromkeys(e for row in rows for e in row["efforts"])),
                "steps": sum(row["requests"] for row in rows),
                "side_steps": sum(row["side_requests"] for row in rows),
                "tool_calls": sum(row["tool_calls"] for row in rows),
                "operator_prompts": operator_prompts,
                "interrupts": interrupts,
                "rejections": sum(sum(row["rejections"].values()) for row in rows),
                "interventions": operator_prompts + interrupts,
                "compactions": sum(sum(row["compactions"].values()) for row in rows),
                "skills": dict(skills),
                "escalated": changes > 0,
                "clean": count == 1 and operator_prompts + interrupts == 0 and changes == 0,
                "tokens": {name: tokens[name] for name in _TOKENS},
                "cost_usd": sum(costs) if costs else None,
                "active_s": sum(row["agent_s"] for row in rows),
                "operator_wait_s": sum(row["operator_wait_s"] for row in rows),
                "idle_s": sum(row["idle_s"] for row in rows),
            }
        )
    return sorted(slices, key=lambda s: (s["first_at"], s["task"]))
