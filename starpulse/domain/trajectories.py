"""Trajectory analytics for the level: how its runs travelled the machine, not only how much of them there was.

A trajectory is one run of the level's machine with its self-loops collapsed (`level_metrics.collapse`). The analytics
cover the runs that ended in a terminal inside the window, so every path they read is a whole one. They are pure
functions of those runs: a fixture gives answers that can be worked out by hand.

- Variants and the norm: each distinct path with its count, the most common being the norm; outliers are the other
  runs ranked by Levenshtein distance from the norm.
- An absorbing Markov chain over the observed transitions, terminals absorbing: from each state the expected days to
  finish and the chance of reaching the goal, from the fundamental matrix N = (I - Q)^-1.
- Betweenness: Brandes centrality on the transition graph; the state that holds the most path time is the bottleneck.
- Gates: the dominators and post-dominators of each configured gate in each run's own graph, never in the union of all
  runs' graphs, which holds paths no run took. A gate is bypassable when a run that reached the goal had a path to it
  that skips the gate, and that run's own path is the witness.
- Rework loops: per run the back-edges and non-trivial strongly connected components of its own step graph, and across
  runs each back-edge's trips and total days, summed from the runs' own figures and never found in the union graph.
- Forecast: each run still going gets its chance of each terminal and its expected days to finish from the row of the
  state it is in, conditioned on the loops it has gone round so far (a third review round is not the first), with the
  sample size behind that row. The same chain answers a what-if that changes one transition's probability, and a
  calibration report scores it on the latest fifth of the ended runs against a chain fitted without them.
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

from starpulse.domain.level import Level
from starpulse.domain.level_metrics import Run, WindowPastHistory, collapse

__all__ = ["WhatIfRefused", "betweenness", "trajectory_analytics", "what_if"]

_DAY_S = 86400.0


#: The loop count a forecast conditions on stops here: two loops and more share a row.
LOOP_CAP = 2
#: A loop-conditioned row seen leave fewer times than this pools to its state's unconditioned row.
POOL_BELOW = 5
#: One ended run in this many, the latest, is held out of the chain the calibration scores.
HELD_OUT_EVERY = 5


class WhatIfRefused(ValueError):
    """A what-if the observed chain cannot answer: no observed row to change, no probability, or no way out."""


def trajectory_analytics(
    level: Level,
    machine: Mapping[str, Any],
    runs: Iterable[Run],
    *,
    now: float,
    window_s: float,
    history_start: float | None = None,
    sources: Collection[str] = (),
) -> dict[str, Any]:
    """The analytics over the runs of `machine` that ended in a terminal in the last `window_s` seconds up to `now`.

    Raises `WindowPastHistory` when the window is longer than the history, as the level's flow numbers do. `runs` need
    only be the ones that ended in the window if the history says where it begins (`history_start`); `sources` is
    taken so the two views answer the same call.
    """
    held, first, ended = _window(level, runs, now=now, window_s=window_s, history_start=history_start)
    paths = [(run, [state for _, state in steps]) for run, steps in ended]
    variants = Counter(tuple(path) for _, path in paths)
    ranked = sorted(variants.items(), key=lambda variant: (-variant[1], len(variant[0]), variant[0]))
    norm = list(ranked[0][0]) if ranked else None

    model = _Model(level, ended)
    counts, stays = model.counts, model.stays
    edges = [(a, b) for a, out in counts.items() for b in out]
    path_days = {state: sum(lengths) / _DAY_S for state, lengths in stays.items()}
    nodes = betweenness(edges)
    bottleneck = max(path_days, key=lambda state: (path_days[state], state), default=None)

    trajectories = [(run, _trajectory(level, run, steps)) for run, steps in ended]
    return {
        "now": now,
        "window_s": window_s,
        "history_s": now - first,
        "machine": level.machine,
        "goal": level.goal,
        "ended": len(ended),
        "variants": [{"path": list(path), "count": n, "share": n / len(ended)} for path, n in ranked],
        "norm": {"path": norm, "count": ranked[0][1]} if norm else None,
        "outliers": _outliers(paths, norm) if norm else [],
        "chain": _chain(model.plain),
        "betweenness": nodes,
        "bottleneck": {"state": bottleneck, "path_days": path_days[bottleneck]} if bottleneck else None,
        "gates": _level_gates(level, trajectories),
        "loops": _level_loops(trajectories),
        "runs": [trajectory for _, trajectory in trajectories],
        "forecast": _forecast(level, machine, model, held),
        "calibration": _calibration(level, ended),
    }


def what_if(
    level: Level,
    machine: Mapping[str, Any],
    runs: Iterable[Run],
    *,
    now: float,
    window_s: float,
    history_start: float | None = None,
    sources: Collection[str] = (),
    origin: str,
    to: str,
    p: float,
) -> dict[str, Any]:
    """The change in the chance of the goal and the expected days from the usual first state when the chain's
    `origin -> to` transition has probability `p`, over the runs that ended in the window as `trajectory_analytics`
    reads them.

    `origin`'s other exits keep their shares of what is left. Refused (`WhatIfRefused`) when no ended run left
    `origin` or `to` (a terminal needs none), `to` is `origin`, `p` is no probability, `origin` has no other exit to
    give the rest to, or the changed chain never finishes.
    """
    _, first, ended = _window(level, runs, now=now, window_s=window_s, history_start=history_start)
    model = _Model(level, ended)
    counts, terminals = model.counts, {terminal.id for terminal in level.terminals}
    if not 0 <= p <= 1:
        raise WhatIfRefused(f"p must be a probability from 0 to 1, not {p}")
    for state in (origin, to):
        if state not in counts and (state == origin or state not in terminals):
            raise WhatIfRefused(f"no run that ended in the window left {state}")
    if to == origin:
        raise WhatIfRefused("a stay in one state is no transition")
    out = sum(counts[origin].values())
    was = counts[origin][to] / out
    if was == 1 and p < 1:
        raise WhatIfRefused(f"{origin} -> {to} is {origin}'s only exit: no other exit takes the rest")
    scale = (1 - p) / (1 - was) if was < 1 else 0.0
    changed = dict(counts)
    changed[origin] = Counter({after: n / out * scale for after, n in counts[origin].items() if after != to} | {to: p})
    try:
        after = _absorb(changed, model.stays, level)
    except ZeroDivisionError:
        raise WhatIfRefused(f"with {origin} -> {to} at {p} a run never finishes") from None
    firsts = Counter(steps[0][1] for _, steps in ended if steps[0][1] in counts)
    start = min(firsts, key=lambda state: (-firsts[state], state))
    before = model.plain[start]
    return {
        "now": now,
        "window_s": window_s,
        "history_s": now - first,
        "machine": level.machine,
        "goal": level.goal,
        "ended": len(ended),
        "from": origin,
        "to": to,
        "p": p,
        "was": was,
        "n": out,
        "start": start,
        **{
            key: {"before": before[key], "after": after[start][key], "change": after[start][key] - before[key]}
            for key in ("p_goal", "expected_days")
        },
        "chain": _chain(after),
    }


_Held = tuple[Run, list[tuple[float, str]]]


def _window(
    level: Level, runs: Iterable[Run], *, now: float, window_s: float, history_start: float | None
) -> tuple[list[_Held], float, list[_Held]]:
    """Every run with its collapsed steps, where the history begins, and the runs that ended in a terminal in the window
    by task; refuses (`WindowPastHistory`) a window longer than the history."""
    held = [(run, collapse(run.steps)) for run in runs]
    first = (
        history_start if history_start is not None else min((steps[0][0] for _, steps in held if steps), default=now)
    )
    if window_s > now - first:
        raise WindowPastHistory(window_s, now - first)
    start = now - window_s
    terminals = {terminal.id for terminal in level.terminals}
    ended = sorted(
        (
            (run, steps)
            for run, steps in held
            if len(steps) > 1 and steps[-1][1] in terminals and start <= steps[-1][0] <= now
        ),
        key=lambda held: (held[0].task, held[0].source),
    )
    return held, first, ended


class _Model:
    """The chain fitted on some ended runs: its transitions and stays by state, and its solved rows by state (`plain`)
    and by state and loops so far, capped at `LOOP_CAP` (`conditioned`)."""

    def __init__(self, level: Level, ended: Iterable[_Held]) -> None:
        terminals = {terminal.id for terminal in level.terminals}
        self.counts: dict[str, Counter[str]] = defaultdict(Counter)
        self.stays: dict[str, list[float]] = defaultdict(list)
        loop_counts: dict[Any, Counter[Any]] = defaultdict(Counter)
        loop_stays: dict[Any, list[float]] = defaultdict(list)
        for _, steps in ended:
            loops = [min(n, LOOP_CAP) for n in _loops_so_far(steps)]
            for i, ((at, state), (later, after)) in enumerate(zip(steps, steps[1:], strict=False)):
                if state not in terminals:  # a terminal absorbs: a run that leaves one again adds no transition
                    self.counts[state][after] += 1
                    self.stays[state].append(later - at)
                    loop_counts[state, loops[i]][after if after in terminals else (after, loops[i + 1])] += 1
                    loop_stays[state, loops[i]].append(later - at)
        self.plain = _absorb(self.counts, self.stays, level)
        self.conditioned = _absorb(loop_counts, loop_stays, level)

    def row(self, state: str, loops: int) -> tuple[dict[str, Any] | None, bool]:
        """The row a run in `state` after `loops` loops is forecast from, and whether it is pooled: the state's own row
        when its loop-conditioned one was seen leave fewer than `POOL_BELOW` times, None when neither was seen."""
        row = self.conditioned.get((state, min(loops, LOOP_CAP)))
        if row is not None and row["n"] >= POOL_BELOW:
            return row, False
        return self.plain.get(state), True


def _loops_so_far(steps: Sequence[tuple[float, str]]) -> list[int]:
    """At each step, the rework loops the run had gone round: the trips of the back-edges of its steps up to there."""
    return [sum(loop["trips"] for loop in _rework(steps[: i + 1])[0]) for i in range(len(steps))]


def _forecast(level: Level, machine: Mapping[str, Any], model: _Model, held: Iterable[_Held]) -> list[dict[str, Any]]:
    """Each run still going, by task: the state it is in since when, its loops so far, and from its row the chance of
    each terminal, of the goal and the expected days to finish, with `n`, the times that row was seen leave."""
    stop = {terminal.id for terminal in level.terminals} | {s["id"] for s in machine["states"] if s["final"]}
    going = sorted(
        ((run, steps) for run, steps in held if steps and steps[-1][1] not in stop),
        key=lambda held: (held[0].task, held[0].source),
    )
    forecast = []
    for run, steps in going:
        at, state = steps[-1]
        loops = _loops_so_far(steps)[-1]
        row, pooled = model.row(state, loops)
        forecast.append(
            {
                "source": run.source,
                "task": run.task,
                "state": state,
                "loops": loops,
                "since": at,
                "p": row["p"] if row else None,
                "p_goal": row["p_goal"] if row else None,
                "expected_days": row["expected_days"] if row else None,
                "n": row["n"] if row else 0,
                "pooled": pooled,
            }
        )
    return forecast


def _calibration(level: Level, ended: Sequence[_Held]) -> dict[str, Any]:
    """The forecast's chance of the goal scored on held-out runs: the latest `1 / HELD_OUT_EVERY` of the ended runs by
    when they ended, each of their steps before the end forecast from a chain fitted on the others, binned by decile
    of the forecast with its mean and the share of those runs that reached the goal. `calibrated` is whether every
    decile holding a forecast is within 10 points; None with nothing scored."""
    order = sorted(ended, key=lambda held: (held[1][-1][0], held[0].task, held[0].source))
    cut = len(order) - len(order) // HELD_OUT_EVERY
    model, terminals = _Model(level, order[:cut]), {terminal.id for terminal in level.terminals}
    bins: list[list[tuple[float, bool, int]]] = [[] for _ in range(10)]
    unscored = 0
    for k, (_, steps) in enumerate(order[cut:]):
        reached = steps[-1][1] == level.goal
        for (_, state), loops in zip(steps[:-1], _loops_so_far(steps), strict=False):
            if state in terminals:
                continue
            row, _ = model.row(state, loops)
            if row is None:
                unscored += 1
            else:
                bins[min(int(row["p_goal"] * 10 + 1e-9), 9)].append((row["p_goal"], reached, k))
    deciles = [
        {
            "low": i / 10,
            "high": (i + 1) / 10,
            "n": len(scored),
            "runs": len({k for *_, k in scored}),
            "predicted": sum(p for p, *_ in scored) / len(scored) if scored else None,
            "observed": sum(hit for _, hit, _ in scored) / len(scored) if scored else None,
        }
        for i, scored in enumerate(bins)
    ]
    filled = [d for d in deciles if d["n"]]
    return {
        "fit": cut,
        "held_out": len(order) - cut,
        "predictions": sum(d["n"] for d in deciles),
        "unscored": unscored,
        "deciles": deciles,
        "calibrated": all(abs(d["predicted"] - d["observed"]) <= 0.1 for d in filled) if filled else None,
    }


def _outliers(paths: Sequence[tuple[Run, list[str]]], norm: list[str]) -> list[dict[str, Any]]:
    """The runs off the norm, the furthest first and a tie by task."""
    found = [
        {"source": run.source, "task": run.task, "path": path, "distance": _levenshtein(path, norm)}
        for run, path in paths
        if path != norm
    ]
    return sorted(found, key=lambda outlier: (-outlier["distance"], outlier["task"], outlier["source"]))


def _levenshtein(a: Sequence[str], b: Sequence[str]) -> int:
    """The fewest insertions, deletions and substitutions of a state that turn `a` into `b`."""
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (x != y))
    return row[-1]


def _chain(rows: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """The chain as the body carries it: each state's expected days to finish and chance of the goal."""
    return {state: {"expected_days": row["expected_days"], "p_goal": row["p_goal"]} for state, row in rows.items()}


def _absorb(counts: Mapping[Any, Counter[Any]], stays: Mapping[Any, list[float]], level: Level) -> dict[Any, Any]:
    """Each state's expected days to finish and chance of ending in each terminal and in the goal, solved from the
    transitions observed, with `n`, the times it was seen leave.

    With Q the transitions among the states that have a way out and R the chance of stepping into a terminal at once,
    the expected days are N h and the chances N R, where N = (I - Q)^-1 and h is the mean stay in days. Both come from
    solving (I - Q) x = column rather than inverting. A target with no row of its own absorbs.
    """
    states = list(counts)
    index = {state: i for i, state in enumerate(states)}
    ends = list(dict.fromkeys([*(terminal.id for terminal in level.terminals), level.goal]))
    matrix = [[float(i == j) for j in range(len(states))] for i in range(len(states))]
    columns: list[list[float]] = [[] for _ in range(1 + len(ends))]
    for state in states:
        out = sum(counts[state].values())
        for after, n in counts[state].items():
            if after in index:
                matrix[index[state]][index[after]] -= n / out
        columns[0].append(sum(stays[state]) / len(stays[state]) / _DAY_S)
        for k, end in enumerate(ends, 1):
            columns[k].append(counts[state][end] / out)
    days, *chances = _solve(matrix, columns) if states else [[] for _ in columns]
    terminals = [terminal.id for terminal in level.terminals]
    return {
        state: {
            "n": sum(counts[state].values()),
            "expected_days": days[i],
            "p": {end: chances[k][i] for k, end in enumerate(ends) if end in terminals},
            "p_goal": chances[ends.index(level.goal)][i],
        }
        for i, state in enumerate(states)
    }


def _solve(matrix: list[list[float]], columns: list[list[float]]) -> list[list[float]]:
    """The solutions x of `matrix x = column` for each of `columns`, by Gauss-Jordan elimination with row pivoting;
    `ZeroDivisionError` when `matrix` is singular."""
    n = len(matrix)
    rows = [[*matrix[i], *(column[i] for column in columns)] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            raise ZeroDivisionError("the matrix is singular")
        rows[col], rows[pivot] = rows[pivot], rows[col]
        rows[col] = [value / rows[col][col] for value in rows[col]]
        for r in range(n):
            if r != col and rows[r][col]:
                rows[r] = [a - rows[r][col] * b for a, b in zip(rows[r], rows[col], strict=True)]
    return [[rows[i][n + k] for i in range(n)] for k in range(len(columns))]


def betweenness(edges: Iterable[tuple[str, str]]) -> dict[str, float]:
    """Brandes betweenness centrality of each state of the directed graph `edges`, the paths it lies strictly inside
    counted once per ordered pair of states and split evenly across the shortest ones."""
    succ: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        succ[a].add(b)
        succ[b]
    score = dict.fromkeys(succ, 0.0)
    for source in succ:
        order: list[str] = []
        before: dict[str, list[str]] = defaultdict(list)
        paths = dict.fromkeys(succ, 0)
        paths[source] = 1
        dist = {source: 0}
        queue = deque([source])
        while queue:
            u = queue.popleft()
            order.append(u)
            for v in succ[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    queue.append(v)
                if dist[v] == dist[u] + 1:
                    paths[v] += paths[u]
                    before[v].append(u)
        carry = dict.fromkeys(succ, 0.0)
        for v in reversed(order):
            for u in before[v]:
                carry[u] += paths[u] / paths[v] * (1 + carry[v])
            if v != source:
                score[v] += carry[v]
    return score


def _dominators(succ: Mapping[str, Iterable[str]], entry: str) -> dict[str, set[str]]:
    """Each state's dominators: the states on every path from `entry` to it, itself and `entry` among them.

    `succ` must reach every state from `entry`, as the graph of one run's own steps does.
    """
    pred: dict[str, set[str]] = defaultdict(set)
    for a, targets in succ.items():
        for b in targets:
            pred[b].add(a)
    everything = set(succ)
    dom = {state: set(everything) for state in succ}
    dom[entry] = {entry}
    changed = True
    while changed:
        changed = False
        for state in succ:
            if state != entry:
                new = {state} | set.intersection(*(dom[p] for p in pred[state]))
                if new != dom[state]:
                    dom[state], changed = new, True
    return dom


def _shortest(succ: Mapping[str, Iterable[str]], entry: str, exit: str, avoiding: str) -> list[str]:
    """The fewest-step path from `entry` to `exit` that never enters `avoiding`; empty when every path does."""
    came: dict[str, str | None] = {entry: None}
    queue = deque([entry])
    while queue:
        u = queue.popleft()
        if u == exit:
            path = []
            while u is not None:
                path.append(u)
                u = came[u]
            return path[::-1]
        for v in succ[u]:
            if v != avoiding and v not in came:
                came[v] = u
                queue.append(v)
    return []


def _trajectory(level: Level, run: Run, steps: Sequence[tuple[float, str]]) -> dict[str, Any]:
    """One run's path, its rework loops and, when it reached the goal, how each configured gate stands in the graph of
    its own steps."""
    path = [state for _, state in steps]
    loops, sccs = _rework(steps)
    reached = path[-1] == level.goal
    gates: list[dict[str, Any]] = []
    if reached:
        succ: dict[str, set[str]] = defaultdict(set)
        back: dict[str, set[str]] = defaultdict(set)
        for a, b in zip(path, path[1:], strict=False):
            succ[a].add(b)
            back[b].add(a)
            succ[b]
            back[a]
        dom, post = _dominators(succ, path[0]), _dominators(back, path[-1])
        order = {state: path.index(state) for state in succ}  # first visit
        for gate in level.gates:
            crossed = gate in succ
            mandatory = gate in dom[path[-1]]
            gates.append(
                {
                    "gate": gate,
                    "crossed": crossed,
                    "mandatory": mandatory,
                    "dominators": sorted(dom[gate] - {gate}, key=order.get) if crossed else [],
                    "post_dominators": sorted(post[gate] - {gate}, key=order.get) if crossed else [],
                    "witness": None if mandatory else _shortest(succ, path[0], path[-1], gate),
                }
            )
    return {
        "source": run.source,
        "task": run.task,
        "path": path,
        "reached_goal": reached,
        "back_edges": len(loops),
        "sccs": sccs,
        "loops": loops,
        "gates": gates,
    }


def _rework(steps: Sequence[tuple[float, str]]) -> tuple[list[dict[str, Any]], int]:
    """A run's rework loops and its count of non-trivial strongly connected components, in the graph of its own steps.

    A loop is a back-edge of a depth-first search from the run's first state (an edge into a state still on the stack),
    reported with its `trips` (the steps that took it) and `days`: for each trip, from the target's previous visit to
    the step back into it. A step into a state the run has not yet visited is no trip, as the search can meet that state
    by a later edge. The components are found by Tarjan's algorithm, a state with no way back counting for none.
    """
    succ: dict[str, dict[str, None]] = defaultdict(dict)
    for (_, a), (_, b) in zip(steps, steps[1:], strict=False):
        succ[a][b] = None
        succ[b]
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    back: set[tuple[str, str]] = set()
    sccs = 0

    def visit(u: str) -> None:
        nonlocal sccs
        index[u] = low[u] = len(index)
        stack.append(u)
        for v in succ[u]:
            if v not in index:
                visit(v)
                low[u] = min(low[u], low[v])
            elif v in stack:
                back.add((u, v))
                low[u] = min(low[u], index[v])
        if low[u] == index[u]:
            size = 0
            while True:
                size += 1
                if stack.pop() == u:
                    break
            sccs += size > 1

    if steps:
        visit(steps[0][1])
    seen: dict[str, float] = {}
    found: dict[tuple[str, str], list[float]] = {}
    previous = None
    for at, state in steps:
        if (previous, state) in back and state in seen:
            trips = found.setdefault((previous, state), [0, 0.0])
            trips[0] += 1
            trips[1] += (at - seen[state]) / _DAY_S
        seen[state] = at
        previous = state
    loops = [{"from": a, "to": b, "trips": int(n), "days": days} for (a, b), (n, days) in found.items()]
    return sorted(loops, key=lambda loop: (-loop["days"], loop["from"], loop["to"])), sccs


def _level_loops(trajectories: Sequence[tuple[Run, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Each back-edge any run took, with how many runs took it and its trips and days summed over them, the longest
    first. It reads each run's own loops, so a cycle that only the union of two runs' steps closes is never in it."""
    total: dict[tuple[str, str], dict[str, Any]] = {}
    for _, trajectory in trajectories:
        for loop in trajectory["loops"]:
            row = total.setdefault((loop["from"], loop["to"]), {"runs": 0, "trips": 0, "days": 0.0})
            row["runs"] += 1
            row["trips"] += loop["trips"]
            row["days"] += loop["days"]
    rows = [{"from": a, "to": b, **row} for (a, b), row in total.items()]
    return sorted(rows, key=lambda row: (-row["days"], row["from"], row["to"]))


def _level_gates(level: Level, trajectories: Sequence[tuple[Run, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Each configured gate over the runs that reached the goal: how many crossed it, how many had to, and the
    shortest witness among the runs that did not."""
    reached = [(run, trajectory) for run, trajectory in trajectories if trajectory["reached_goal"]]
    summary = []
    for i, gate in enumerate(level.gates):
        entries = [(run, trajectory["gates"][i]) for run, trajectory in reached]
        bypassed = [(run, entry["witness"]) for run, entry in entries if not entry["mandatory"]]
        witness = min(bypassed, key=lambda b: (len(b[1]), b[0].task, b[0].source), default=None)
        summary.append(
            {
                "gate": gate,
                "runs": len(entries),
                "crossed": sum(entry["crossed"] for _, entry in entries),
                "mandatory": len(entries) - len(bypassed),
                "bypassed": len(bypassed),
                "bypassable": bool(bypassed),
                "witness": {"task": witness[0].task, "path": witness[1]} if witness else None,
            }
        )
    return summary
