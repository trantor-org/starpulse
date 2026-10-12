"""Session health and slice health: what one agent session did, and what the sessions that worked one task did together.

`session_health` is a pure fold of the `Signal`s the harness exports carry (`starpulse._internal.harnesses.telemetry`),
so a recorded export gives numbers that can be worked out by hand. A session is one harness's session id; it yields one
row per task it worked, in the order it reached them.

The task a signal belongs to is the one the export's launch branch names under the board's `TaskKeys`, until a `claim`
signal (a command or a `Skill` call the `[analytics]` `claims` patterns matched) or a `branch` signal (a shell's `git
switch` or `git checkout`) names another task. A launch branch that names no task leaves the session's first signals
with none to hold, so they belong to the first task a claim or a branch signal names: a session's work before its claim
is that task's work, as the transcript-mined `session_signals` count it, and no `task` None row precedes it. A switch to
a ref that names no task leaves the task as it was, so `git checkout -- file` or a trip back to `main` does not drop a
session's work from its slice. A session that no branch or claim ties to a task is a row with `task` None, counted in
session health and in no slice.

A shell command's claim is read twice, so a change to `claims` reaches rows stored before it: the export is matched at
ingest, which stores a `claim` signal, and `grouped` matches each stored shell command against the current patterns,
adding the claim a stored command names when the same tool result has no stored claim row (one claim per tool result).
A `Skill` call's claim is ingest-only: its arguments are never stored, so a claim pattern added later reaches only the
calls exported after it, and a stored command is matched as stored, after redaction.

A turn is every signal that shares a `prompt.id`; its end is its last signal, whichever order the exports arrived in.
A signal with no id (Codex, rows stored before ids were kept) belongs to the turn of the prompt before it. Time is read
from the events' own durations and from the turns' edges, never from the gaps between signals:

- `agent_s`: the summed `seconds` of the session's model requests (subagents' included) and tool results.
- `operator_wait_s`: from the end of the turn before to a human prompt other than the session's first; a prompt typed
  while the turn before still worked waits for nothing.
  An `[analytics]` `operator_tools` result (a question the operator answers, a plan they approve) is no prompt but
  is the same wait: the span from the last signal before it, other than its own tool decision, to the tool's start.
- `idle_s`: the same span before an `injected` prompt, a wait for something other than the operator (a background
  task, a scheduler).

A prompt is `injected` when its label says so and `human` otherwise, so a Codex prompt, which is unlabelled, is human.
`operator_prompts` are the human prompts after a task's claim: after the claim signal that brought the session to the
task, or after the session's first prompt for the task it launched on or, on a task-less launch branch, claimed first. `interrupts` are the turns Claude Code started
and never closed with a reply (one still running counts until its reply lands) and the interrupted turns Codex
exports. `steps_before_edit` is the model requests before the task's first successful file write, None until it has
one. `complete` is a session that loaded the `[analytics]` `completion_skill` and then ran the completion call for the
task. `interventions` of a slice are its operator prompts plus interrupts, and it is `escalated` when a model or effort
changed between a session's main-thread requests. A slice is `clean` when one session did its work with no
intervention and no escalation; whether it settled in Review or Done is the board's fact, which the reader joins.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from starpulse._internal.config.analytics import Analytics
from starpulse._internal.level.signals import CODEX, Signal, claim_key, claimed, main_thread_source
from starpulse.contracts.adapters import TaskKeys

__all__ = ["attributed", "grouped", "session_health", "session_kind", "slice_health"]

#: Tools whose successful result is a file written: the work on a task has begun.
_EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
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
        source = main_thread_source(s.detail)
        if s.kind == "request" and source in {"sdk", "repl_main_thread"}:
            return "headless" if source == "sdk" else "interactive"
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
        "main_model": None,
        "main_effort": None,
        "model_changes": 0,
        "effort_changes": 0,
        "tokens": dict.fromkeys(_TOKENS, 0),
        "cost_usd": None,
        "agent_s": 0.0,
        "operator_wait_s": 0.0,
        "idle_s": 0.0,
        "steps_before_edit": None,
        "complete": False,
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
            if value and row[f"main_{field}"] is None:
                row[f"main_{field}"] = value
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


def _read_time_claims(ordered: list[Signal], claims: Sequence[re.Pattern[str]], keys: TaskKeys) -> list[Signal]:
    """`ordered` with a `claim` after each shell result whose stored command names a task and that has no stored claim
    row, as ingest would have minted it."""
    stored = {s.key for s in ordered if s.kind == "claim"}
    with_claims: list[Signal] = []
    for s in ordered:
        with_claims.append(s)
        if s.kind == "tool" and s.command and claim_key(s.key) not in stored:
            if (task := claimed(s.command, claims, keys)) is not None:
                with_claims.append(
                    Signal(s.harness, s.session, "claim", s.time, claim_key(s.key), s.branch, name=task, turn=s.turn)
                )
    return with_claims


def grouped(
    found: Iterable[Signal], keys: TaskKeys | None = None, analytics: Analytics | None = None
) -> list[list[Signal]]:
    """The signals `found` as one list per harness session, each oldest first. With `keys` and `analytics`, a stored
    shell command the current `claims` match is also a claim (see the module docstring)."""
    sessions: dict[tuple[str, str], list[Signal]] = defaultdict(list)
    for s in found:
        sessions[s.harness, s.session].append(s)
    ordered = [sorted(group, key=lambda s: s.time) for group in sessions.values()]
    if keys is None or analytics is None or not analytics.claims:
        return ordered
    return [_read_time_claims(group, analytics.claims, keys) for group in ordered]


def attributed(ordered: list[Signal], keys: TaskKeys | None) -> Iterator[tuple[str | None, Signal]]:
    """Each signal of one session, oldest first, with the task it belongs to (see the module docstring)."""
    task = keys.for_branch(ordered[0].branch) if keys else None
    tasks: list[str | None] = []
    for s in ordered:
        if s.kind == "claim" and keys and keys.matches(s.name):
            task = s.name
        elif s.kind == "branch" and keys and (named := keys.for_branch(s.name)) is not None:
            task = named
        tasks.append(task)
    # A task, once named, is never unnamed, so the signals still None are those before the first naming signal.
    first = next((t for t in tasks if t is not None), None)
    for task, s in zip(tasks, ordered, strict=True):
        yield task or first, s


def _turn_ids(ordered: list[Signal]) -> list[str]:
    """The turn each signal of one session belongs to: its own `prompt.id`, else the turn its last prompt opened."""
    current = ""
    ids = []
    for s in ordered:
        if s.kind == "prompt":
            current = s.turn or s.key
        ids.append(s.turn or current)
    return ids


def _asked_since(ordered: list[Signal], at: int) -> float:
    """The time of the last signal before `ordered[at]`, passing over the decision to run the same tool."""
    before = at - 1
    while before > 0 and ordered[before].kind == "decision" and ordered[before].name == ordered[at].name:
        before -= 1
    return ordered[before].time


def session_health(
    found: Iterable[Signal], keys: TaskKeys | None, analytics: Analytics | None = None
) -> list[dict[str, Any]]:
    """One row per (session, task) of the sessions `found` holds, oldest first; see the module docstring."""
    completion = analytics.completion_skill if analytics else ""
    operator_tools = analytics.operator_tools if analytics else frozenset()
    rows: list[dict[str, Any]] = []
    for ordered in grouped(found, keys, analytics):
        kind = session_kind(ordered)
        ids = _turn_ids(ordered)
        ends: dict[str, float] = {}
        for turn, s in zip(ids, ordered, strict=True):
            ends[turn] = max(ends.get(turn, s.time), s.time)
        row: dict[str, Any] | None = None
        by_task: dict[str | None, dict[str, Any]] = {}
        last: dict[str, dict[str, str]] = defaultdict(dict)
        armed: set[str | None] = set()  # tasks whose human prompts now count as the operator's steering
        loaded: set[str | None] = set()  # tasks that loaded the completion skill
        steps: dict[str | None, int] = defaultdict(int)  # requests before a task's first edit
        open_turns: dict[str, dict[str, Any]] = {}  # a Claude Code turn's row until a reply closes it
        prompts = 0
        previous: str | None = None
        for at, (task, s) in enumerate(attributed(ordered, keys)):
            if row is None or row["task"] != task:
                row = by_task.get(task) or by_task.setdefault(task, _empty(s, task, kind))
            if s.kind in {"claim", "branch"} and task is not None and task != previous:
                armed.add(task)
            previous = task
            if s.kind == "prompt":
                prompts += 1
                row["prompts"] += 1
                injected = s.detail == "injected"
                if prompts > 1:
                    gap = max(s.time - ends[ids[at - 1]], 0.0)
                    row["idle_s" if injected else "operator_wait_s"] += gap
                if not injected and task in armed:
                    row["operator_prompts"] += 1
                if prompts == 1:
                    armed.add(task)
                if s.turn:
                    open_turns[s.turn] = row
            elif s.kind == "reply":
                open_turns.pop(s.turn, None)
            elif s.kind in {"request", "tool"}:
                row["agent_s"] += s.seconds
                if s.kind == "tool" and s.name in operator_tools and at:
                    row["operator_wait_s"] += max(s.time - s.seconds - _asked_since(ordered, at), 0.0)
                if row["steps_before_edit"] is None:
                    if s.kind == "request" and s.origin in {"main", "side"}:
                        steps[task] += 1
                    elif s.kind == "tool" and s.ok and s.name in _EDITS:
                        row["steps_before_edit"] = steps[task]
            elif s.kind == "skill" and completion and s.name == completion:
                loaded.add(task)
            elif s.kind == "deliver" and task in loaded:
                row["complete"] = True
            row["last_at"] = s.time
            _note(row, s, last[task or ""])
        for opened in open_turns.values():
            opened["interrupts"] += 1
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
                "complete": any(row["complete"] for row in rows),
                "steps_before_edit": next(
                    (r["steps_before_edit"] for r in sorted(rows, key=lambda r: r["first_at"]) if r["steps_before_edit"] is not None),
                    None,
                ),
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
