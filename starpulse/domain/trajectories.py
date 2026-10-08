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
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from collections.abc import Collection, Iterable, Mapping, Sequence
from typing import Any

from starpulse.domain.level import Level
from starpulse.domain.level_metrics import Run, WindowPastHistory, collapse

__all__ = ["betweenness", "trajectory_analytics"]

_DAY_S = 86400.0


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
    paths = [(run, [state for _, state in steps]) for run, steps in ended]
    variants = Counter(tuple(path) for _, path in paths)
    ranked = sorted(variants.items(), key=lambda variant: (-variant[1], len(variant[0]), variant[0]))
    norm = list(ranked[0][0]) if ranked else None

    counts: dict[str, Counter[str]] = defaultdict(Counter)
    stays: dict[str, list[float]] = defaultdict(list)
    for _, steps in ended:
        for (at, state), (later, after) in zip(steps, steps[1:], strict=False):
            if state not in terminals:  # a terminal absorbs: a run that leaves one again adds no transition
                counts[state][after] += 1
                stays[state].append(later - at)
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
        "chain": _chain(counts, stays, level.goal),
        "betweenness": nodes,
        "bottleneck": {"state": bottleneck, "path_days": path_days[bottleneck]} if bottleneck else None,
        "gates": _level_gates(level, trajectories),
        "loops": _level_loops(trajectories),
        "runs": [trajectory for _, trajectory in trajectories],
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


def _chain(counts: Mapping[str, Counter[str]], stays: Mapping[str, list[float]], goal: str) -> dict[str, Any]:
    """Each state's expected days to finish and chance of reaching `goal`, solved from the transitions observed.

    With Q the transitions among the states that have a way out and R the chance of stepping into `goal` at once,
    the expected days are N h and the chance of the goal is N R, where N = (I - Q)^-1 and h is the mean stay in days.
    Both come from solving (I - Q) x = column rather than inverting.
    """
    states = list(counts)
    index = {state: i for i, state in enumerate(states)}
    matrix = [[float(i == j) for j in range(len(states))] for i in range(len(states))]
    to_goal, mean_days = [], []
    for state in states:
        out = sum(counts[state].values())
        for after, n in counts[state].items():
            if after in index:
                matrix[index[state]][index[after]] -= n / out
        to_goal.append(counts[state][goal] / out)
        mean_days.append(sum(stays[state]) / len(stays[state]) / _DAY_S)
    days, chance = _solve(matrix, [mean_days, to_goal])
    return {state: {"expected_days": days[i], "p_goal": chance[i]} for i, state in enumerate(states)}


def _solve(matrix: list[list[float]], columns: list[list[float]]) -> list[list[float]]:
    """The solutions x of `matrix x = column` for each of `columns`, by Gauss-Jordan elimination with row pivoting."""
    n = len(matrix)
    rows = [[*matrix[i], *(column[i] for column in columns)] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
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
    the step back into it. The components are found by Tarjan's algorithm, a state with no way back counting for none.
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
        if (previous, state) in back:
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
