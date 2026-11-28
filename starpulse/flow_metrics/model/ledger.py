"""The per-session ledger: a session's `steps`, `cost` and `spend` folds, advanced one export at a time.

A session's folds are pure functions of its signals, and StarPulse keeps no signal past its fold. The ledger is the
state that lets an export be folded without the signals before it: the step rows already settled, the raw signals of
the stretch not yet settled (the tail), and the `carry` the settled stretch ends on, so folding the tail from the carry
gives what folding the whole session gives.

`apply` merges an export into the tail, settles a prefix of it, and returns the rows of the whole session. A prefix
settles only at a cut where nothing is in flight: every signal of the prefix ended before any of the rest began, every
call of either part has a request that began at or before it in the same part, and the prefix is older than
`settle_s` behind the newest signal. A signal at or before the last cut is dropped, so an export replayed a day later
changes nothing, and one whose key the tail holds is dropped as a replay. A signal later than `settle_s` to arrive, or a
request whose stream ran longer than that, is not folded as the whole session would have: the ledger gives up exactness
there rather than keep every signal.

The carry is the task and first task named, the skill in force, the last shell command a call ran (the repeat
check), each task's first claim and compaction times, and the claims and compactions that came before any task was
named, which belong to the first one. A settled row whose task was not yet named takes the first task named later.
"""

import math
from collections.abc import Iterable
from dataclasses import asdict
from typing import Any, NamedTuple

from starpulse.contracts.adapters import TaskKeys
from starpulse.contracts.analytics import Analytics
from starpulse.contracts.signals import Signal, signal_of
from starpulse.flow_metrics.model.session_health import attribution, session_signals
from starpulse.flow_metrics.model.steps import NO_SKILL, owned_of

__all__ = ["Folded", "apply", "cost_of", "given", "last_claim", "spend_of", "steps_of"]

#: How far behind its newest signal a session's signals settle, longer than a model request or a tool call runs.
SETTLE_S = 600.0
_EDITS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace"}
_CALLS = {"tool", "skill", "decision"}


class Folded(NamedTuple):
    """`state`, what to store for the session; `rows`, every step row of it, settled then open; `carry`, the carry at
    the end of the open rows."""

    state: dict[str, Any]
    rows: list[dict[str, Any]]
    carry: dict[str, Any]


def _carry() -> dict[str, Any]:
    return {
        "task": None,
        "first": None,
        "skill": NO_SKILL,
        "before": None,
        "claims": {},
        "compactions": {},
        "unnamed_claim": None,
        "unnamed_compactions": [],
    }


def _repeats(calls: Iterable[Signal], before: str | None) -> tuple[set[str], str | None]:
    """The keys of the shell results among `calls`, oldest first, whose command is the one of the call before (`before`
    for the first), and the command of the last call."""
    repeated = set()
    for call in sorted((c for c in calls if c.kind == "tool"), key=lambda c: c.time):
        if call.command and call.command == before:
            repeated.add(call.key)
        before = call.command or None
    return repeated, before


def _fold(
    signals: list[Signal], carry: dict[str, Any] | None, keys: TaskKeys | None, analytics: Analytics | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The rows of `signals`, a stretch of one session, and the carry at its end, `carry` being the one its earlier
    stretch ended on (None for the session's first)."""
    held = carry or _carry()
    pairs, task, first, named_at = attribution(
        session_signals(signals, keys, analytics), keys, (held["task"], held["first"]) if carry else None
    )
    owned = owned_of(pairs, held["skill"])
    kept = [o for o in owned if o.step["captured"] and o.step["origin"] != "auxiliary"]
    repeated, before = _repeats((c for o in kept for c in o.calls), held["before"])
    rows = [
        {
            "step": o.step,
            "agent_s": o.seconds + sum(c.seconds for c in o.calls if c.kind == "tool"),
            "wasted": any((c.kind in {"tool", "decision"} and not c.ok) or c.key in repeated for c in o.calls),
            "edits": any(c.kind == "tool" and c.name in _EDITS for c in o.calls),
            "named": o.step["at"] >= named_at,
        }
        for o in owned
    ]
    claims = dict(held["claims"])
    compactions = {t: list(times) for t, times in held["compactions"].items()}
    unnamed_claim, unnamed_compactions = held["unnamed_claim"], list(held["unnamed_compactions"])
    for named, s in pairs:
        if s.kind == "claim":
            if named:
                claims.setdefault(named, s.time)
            elif unnamed_claim is None:
                unnamed_claim = s.time
        elif s.kind == "compaction":
            if named:
                compactions.setdefault(named, []).append(s.time)
            else:
                unnamed_compactions.append(s.time)
    if first:  # what came before the first task was named is that task's
        if unnamed_claim is not None:
            claims[first] = min(claims.get(first, unnamed_claim), unnamed_claim)
            unnamed_claim = None
        if unnamed_compactions:
            compactions[first] = sorted([*unnamed_compactions, *compactions.get(first, [])])
            unnamed_compactions = []
    return rows, {
        "task": task,
        "first": first,
        "skill": owned[-1].step["skill"] if owned else held["skill"],
        "before": before,
        "claims": claims,
        "compactions": compactions,
        "unnamed_claim": unnamed_claim,
        "unnamed_compactions": unnamed_compactions,
    }


def _start(s: Signal) -> float:
    return s.time - s.seconds if s.kind == "request" or s.kind in _CALLS else s.time


def _settle_point(raw: list[Signal], settled: bool, settle_s: float) -> int:
    """How many of `raw`, oldest first, can settle: the most of them that is a cut (see the module docstring), or 0."""
    n = len(raw)
    horizon = raw[-1].time - settle_s if raw else math.inf
    after = [(math.inf, math.inf, math.inf)] * (n + 1)  # the earliest start of any signal, request and call after i
    for i in range(n - 1, -1, -1):
        start, s = _start(raw[i]), raw[i]
        after[i] = (
            min(after[i + 1][0], start),
            min(after[i + 1][1], start if s.kind == "request" else math.inf),
            min(after[i + 1][2], start if s.kind in _CALLS else math.inf),
        )
    before = [(math.inf, math.inf)]  # the earliest start of any request and call before i
    for s in raw:
        before.append(
            (
                min(before[-1][0], _start(s) if s.kind == "request" else math.inf),
                min(before[-1][1], _start(s) if s.kind in _CALLS else math.inf),
            )
        )
    for p in range(n - 1, 0, -1):
        ends_first = raw[p - 1].time <= horizon and raw[p - 1].time < after[p][0]
        rest_owned = after[p][1] <= after[p][2]
        prefix_owned = before[p][0] <= before[p][1] or (not settled and before[p][0] < math.inf)
        if ends_first and rest_owned and prefix_owned:
            return p
    return 0


def apply(
    state: dict[str, Any] | None,
    incoming: Iterable[Signal],
    keys: TaskKeys | None,
    analytics: Analytics | None = None,
    settle_s: float = SETTLE_S,
) -> Folded:
    """`state`, one session's stored ledger (None for its first export), advanced by `incoming`, the signals an export
    brings; see the module docstring."""
    held = state or {"rows": [], "tail": [], "cut": None, "carry": None, "last_claim": None}
    cut, tail = held["cut"], held["tail"]
    seen, fresh, latest = {s["key"] for s in tail}, [], held["last_claim"]
    for s in incoming:
        if s.kind == "claim" and s.name and (latest is None or s.time > latest[1]):
            latest = [s.name, s.time]
        if (cut is None or s.time > cut) and s.key not in seen:
            seen.add(s.key)
            fresh.append(s)
    raw = sorted([*map(signal_of, tail), *fresh], key=lambda s: s.time)
    settled, carry = held["rows"], held["carry"]
    p = _settle_point(raw, bool(settled), settle_s)
    if p:
        added, carry = _fold(raw[:p], carry, keys, analytics)
        settled, cut = [*settled, *added], raw[p - 1].time
    open_rows, end = _fold(raw[p:], carry, keys, analytics)
    if end["first"]:  # a session that named no task before takes the first it names for its earlier steps
        for row in settled:
            row["step"]["task"] = row["step"]["task"] or end["first"]
    stored = {
        "rows": settled,
        "tail": [asdict(s) for s in raw[p:]],
        "cut": cut,
        "carry": carry,
        "last_claim": latest,
    }
    return Folded(stored, [*settled, *open_rows], end)


def last_claim(state: dict[str, Any] | None) -> tuple[str, float] | None:
    """The task a session's stored `state` last claimed and when, or None when it claimed none."""
    claim = state and state["last_claim"]
    return (claim[0], claim[1]) if claim else None


def steps_of(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The `steps` fold of a session: its step rows as plain JSON data."""
    return [row["step"] for row in rows]


def cost_of(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The `cost` fold of a session: one row per (task, skill) of its steps, as plain JSON data, with the steps, the
    subagent's, the wasted ones, the seconds and the peak context `transition_cost` sums per cell."""
    cost: dict[tuple[str | None, str], dict[str, Any]] = {}
    for row in rows:
        step = row["step"]
        if not step["captured"] or step["origin"] == "auxiliary":
            continue
        part = cost.setdefault(
            (step["task"], step["skill"]),
            {
                "task": step["task"],
                "skill": step["skill"],
                "steps": 0,
                "side_steps": 0,
                "wasted_steps": 0,
                "agent_s": 0.0,
                "peak_context": 0,
            },
        )
        tokens = step["tokens"]
        part["steps"] += 1
        part["side_steps"] += step["origin"] == "side"
        part["wasted_steps"] += row["wasted"]
        part["agent_s"] += row["agent_s"]
        part["peak_context"] = max(part["peak_context"], tokens["input"] + tokens["cache_read"] + tokens["cache_write"])
    return list(cost.values())


def spend_of(folded: Folded, harness: str, session: str) -> dict[str, Any]:
    """The `spend` fold of the session `session` of `harness`: its captured, non-auxiliary steps that belong to a
    task and come at or after the session's first naming signal, each with whether it `edits`, and each task's first claim time and compaction times, as plain JSON data
    `combine_spend` reads."""
    return {
        "harness": harness,
        "session": session,
        "steps": [
            {**row["step"], "edits": row["edits"]}
            for row in folded.rows
            if _spent(row) and row["step"]["task"] and row["named"]
        ],
        "claims": folded.carry["claims"],
        "compactions": folded.carry["compactions"],
    }


def _spent(row: dict[str, Any]) -> bool:
    return row["step"]["captured"] and row["step"]["origin"] != "auxiliary"


def given(state: dict[str, Any] | None, folded: Folded) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """The captured, non-auxiliary steps of `folded` that the session's stored `state` (None for its first export) has
    not given out yet: those a task's Stays take, which name a task at or after the session's first naming signal, and
    those none does; and the request keys to store under `given`, of the steps past the settle cut a later export may
    meet again, so each step is given out once."""
    cut = state["cut"] if state else None
    held = set(state.get("given", ())) if state else set()
    taken: list[dict[str, Any]] = []
    untaken: list[dict[str, Any]] = []
    for row in folded.rows:
        step = row["step"]
        if _spent(row) and (cut is None or step["at"] > cut) and step["key"] not in held:
            (taken if step["task"] and row["named"] else untaken).append(step)
    now = folded.state["cut"]
    return taken, untaken, [r["step"]["key"] for r in folded.rows if now is None or r["step"]["at"] > now]
