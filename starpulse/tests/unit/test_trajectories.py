"""Trajectory analytics on fixture machines with hand-worked answers: variants and the norm, outliers ranked by
Levenshtein distance, the absorbing chain against the closed form (I-Q)^-1, Brandes betweenness against a brute-force
reference, and dominator gates computed per trajectory, never on the union graph."""

from collections import defaultdict, deque
from collections.abc import Iterable

import pytest

from starpulse.domain.level import Level, Terminal
from starpulse.domain.level_metrics import Run, WindowPastHistory
from starpulse.domain.trajectories import betweenness, trajectory_analytics

H = 3600.0
NOW = 100 * H
WINDOW = 100 * H

MACHINE = {
    "states": [
        {"id": "todo", "initial": True, "final": False},
        {"id": "work", "initial": False, "final": False},
        {"id": "review", "initial": False, "final": False},
        {"id": "done", "initial": False, "final": True},
        {"id": "dropped", "initial": False, "final": True},
    ]
}
TERMINALS = (Terminal("done", "goal"), Terminal("dropped", "abandoned"))
LEVEL = Level("board", "done", TERMINALS)
GATED = Level("board", "done", TERMINALS, gates=("review",))


def _run(task: str, *steps: tuple[float, str], source: str = "a") -> Run:
    return Run(source, task, tuple((at * H, state) for at, state in steps))


def _analytics(runs: list[Run], level: Level = LEVEL, window_s: float = WINDOW) -> dict:
    return trajectory_analytics(level, MACHINE, runs, now=NOW, window_s=window_s)


# work -> review 4 of 5 and -> dropped 1 of 5; review -> done 3 of 4 and -> work 1 of 4; mean stays 12.8h and 9h
CHAIN_RUNS = [
    _run("t1", (0, "work"), (10, "review"), (20, "done")),
    _run("t2", (0, "work"), (10, "review"), (20, "work"), (30, "review"), (40, "done")),
    _run("t3", (0, "work"), (10, "dropped")),
    _run("t4", (0, "work"), (24, "review"), (30, "done")),
]


def test_variants_count_each_path_and_the_most_common_is_the_norm() -> None:
    result = _analytics(CHAIN_RUNS)

    assert result["variants"] == [
        {"path": ["work", "review", "done"], "count": 2, "share": 0.5},
        {"path": ["work", "dropped"], "count": 1, "share": 0.25},
        {"path": ["work", "review", "work", "review", "done"], "count": 1, "share": 0.25},
    ]
    assert result["norm"] == {"path": ["work", "review", "done"], "count": 2}


def test_a_step_that_repeats_the_state_before_it_is_no_new_variant() -> None:
    result = _analytics([_run("t1", (0, "work"), (5, "work"), (10, "done")), _run("t2", (0, "work"), (9, "done"))])

    assert result["variants"] == [{"path": ["work", "done"], "count": 2, "share": 1.0}]


def test_outliers_rank_by_levenshtein_distance_from_the_norm_then_by_task() -> None:
    norm = [(0, "work"), (10, "review"), (20, "done")]
    runs = [
        *(_run(f"n{i}", *norm) for i in range(3)),
        _run("z", (0, "work"), (10, "review"), (20, "dropped")),  # one substitution
        _run("y", (0, "work"), (10, "dropped")),  # one substitution, one deletion
        _run("x", (0, "work"), (10, "review"), (20, "work"), (30, "review"), (40, "done")),  # two insertions
    ]

    assert [(o["task"], o["distance"]) for o in _analytics(runs)["outliers"]] == [("x", 2), ("y", 2), ("z", 1)]
    assert _analytics(runs)["outliers"][0]["path"] == ["work", "review", "work", "review", "done"]


def test_only_the_runs_that_ended_inside_the_window_are_analysed() -> None:
    runs = [
        *CHAIN_RUNS,
        _run("going", (0, "work"), (50, "review")),  # not ended
        _run("early", (0, "work"), (1, "done")),  # ended before the window
    ]

    assert [v["count"] for v in _analytics(runs, window_s=90 * H)["variants"]] == [2, 1, 1]  # `early` ended at 1h
    assert [v["count"] for v in _analytics(runs)["variants"]] == [2, 1, 1, 1]


def test_a_window_longer_than_the_history_is_refused_with_the_history() -> None:
    with pytest.raises(WindowPastHistory) as refused:
        _analytics(CHAIN_RUNS, window_s=101 * H)

    assert refused.value.history_s == 100 * H


def test_no_ended_run_gives_an_empty_answer_not_zeros() -> None:
    result = _analytics([_run("going", (0, "work"))])

    assert (result["variants"], result["norm"], result["outliers"], result["chain"]) == ([], None, [], {})
    assert (result["betweenness"], result["bottleneck"]) == ({}, None)


def test_the_chain_matches_the_closed_form_of_the_fundamental_matrix() -> None:
    chain = _analytics(CHAIN_RUNS)["chain"]

    # Q = [[0, .8], [.25, 0]] over (work, review): N = (I-Q)^-1 = [[1.25, 1], [.3125, 1.25]]; h = (12.8h, 9h)
    assert chain["work"]["expected_days"] == pytest.approx((1.25 * 12.8 + 1 * 9) / 24, abs=1e-6)  # 25h
    assert chain["review"]["expected_days"] == pytest.approx((0.3125 * 12.8 + 1.25 * 9) / 24, abs=1e-6)  # 15.25h
    # R(goal) = (0, .75): P = N R
    assert chain["work"]["p_goal"] == pytest.approx(0.75, abs=1e-6)
    assert chain["review"]["p_goal"] == pytest.approx(0.9375, abs=1e-6)
    assert set(chain) == {"work", "review"}


def test_a_move_out_of_a_terminal_is_not_a_transition_of_the_chain() -> None:
    reopened = [_run("r", (0, "work"), (10, "done"), (20, "work"), (30, "done"))]

    assert _analytics(reopened)["chain"]["work"] == {"expected_days": pytest.approx(10 / 24), "p_goal": 1.0}


def _shortest_paths(succ: dict[str, set[str]], dist: dict[str, int], u: str, t: str) -> list[list[str]]:
    """Every shortest path from `u` to `t`, given each state's distance from the path's source."""
    if u == t:
        return [[t]]
    return [[u, *rest] for v in succ[u] if dist.get(v) == dist[u] + 1 for rest in _shortest_paths(succ, dist, v, t)]


def _brute_force(edges: Iterable[tuple[str, str]]) -> dict[str, float]:
    """Betweenness by enumerating every shortest path of every ordered pair: the reference Brandes is held to."""
    succ: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for a, b in edges:
        succ[a].add(b)
        nodes |= {a, b}
    score = dict.fromkeys(nodes, 0.0)
    for s in nodes:
        dist = {s: 0}
        queue = deque([s])
        while queue:
            u = queue.popleft()
            for v in succ[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    queue.append(v)
        for t in nodes - {s}:
            if t in dist:
                found = _shortest_paths(succ, dist, s, t)
                for path in found:
                    for v in path[1:-1]:
                        score[v] += 1 / len(found)
    return score


GRAPHS = {
    "diamond": [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d")],
    "line": [("a", "b"), ("b", "c"), ("c", "d")],
    "loop": [("work", "review"), ("review", "work"), ("review", "done"), ("work", "dropped")],
    "dense": [
        ("a", "b"), ("a", "c"), ("b", "c"), ("c", "d"), ("b", "e"), ("e", "d"),
        ("d", "a"), ("d", "f"), ("e", "f"), ("f", "b"), ("c", "e"),
    ],
}  # fmt: skip


@pytest.mark.parametrize("name", GRAPHS)
def test_betweenness_matches_a_brute_force_reference(name: str) -> None:
    assert betweenness(GRAPHS[name]) == pytest.approx(_brute_force(GRAPHS[name]), abs=1e-9)


def test_betweenness_of_known_graphs_is_the_hand_worked_count() -> None:
    assert betweenness(GRAPHS["diamond"]) == {"a": 0.0, "b": 0.5, "c": 0.5, "d": 0.0}
    assert betweenness(GRAPHS["line"]) == {"a": 0.0, "b": 2.0, "c": 2.0, "d": 0.0}


def test_the_bottleneck_is_the_state_holding_the_most_path_time() -> None:
    result = _analytics(CHAIN_RUNS)

    assert result["betweenness"] == {"work": 1.0, "review": 1.0, "done": 0.0, "dropped": 0.0}
    assert result["bottleneck"] == {"state": "work", "path_days": pytest.approx(64 / 24)}  # 64h work, 36h review


def _gates(result: dict) -> dict:
    return result["gates"][0]


def test_a_gate_every_run_crossed_is_mandatory_though_the_union_graph_would_bypass_it() -> None:
    runs = [
        _run("g1", (0, "todo"), (1, "work"), (2, "review"), (3, "done")),
        _run("g2", (0, "todo"), (1, "review"), (2, "work"), (3, "done")),
    ]  # the union has todo -> work -> done, a path no run took

    assert _gates(_analytics(runs, GATED)) == {
        "gate": "review",
        "runs": 2,
        "crossed": 2,
        "mandatory": 2,
        "bypassed": 0,
        "bypassable": False,
        "witness": None,
    }


def test_a_run_that_bypasses_a_gate_marks_it_bypassable_and_returns_its_own_path_as_the_witness() -> None:
    runs = [
        _run("g1", (0, "todo"), (1, "work"), (2, "review"), (3, "done")),
        _run("g3", (0, "todo"), (1, "work"), (3, "done")),
    ]

    assert _gates(_analytics(runs, GATED)) == {
        "gate": "review",
        "runs": 2,
        "crossed": 1,
        "mandatory": 1,
        "bypassed": 1,
        "bypassable": True,
        "witness": {"task": "g3", "path": ["todo", "work", "done"]},
    }


def test_a_gate_visited_only_on_a_detour_is_bypassable_with_the_path_that_skips_it() -> None:
    runs = [_run("g4", (0, "todo"), (1, "work"), (2, "review"), (3, "work"), (4, "done"))]

    gate = _gates(_analytics(runs, GATED))

    assert (gate["crossed"], gate["mandatory"], gate["bypassable"]) == (1, 0, True)
    assert gate["witness"] == {"task": "g4", "path": ["todo", "work", "done"]}


def test_each_trajectory_lists_what_dominates_and_post_dominates_each_gate_in_its_own_graph() -> None:
    runs = [
        _run("g1", (0, "todo"), (1, "work"), (2, "review"), (3, "done")),
        _run("g3", (0, "todo"), (1, "work"), (3, "done")),
        _run("g4", (0, "todo"), (1, "work"), (2, "review"), (3, "work"), (4, "done")),
        _run("ab", (0, "work"), (1, "dropped")),
    ]

    by_task = {r["task"]: r for r in _analytics(runs, GATED)["runs"]}

    assert by_task["g1"]["gates"] == [
        {
            "gate": "review",
            "crossed": True,
            "mandatory": True,
            "dominators": ["todo", "work"],
            "post_dominators": ["done"],
            "witness": None,
        }
    ]
    assert by_task["g3"]["gates"] == [
        {
            "gate": "review",
            "crossed": False,
            "mandatory": False,
            "dominators": [],
            "post_dominators": [],
            "witness": ["todo", "work", "done"],
        }
    ]
    assert by_task["g4"]["gates"][0]["dominators"] == ["todo", "work"]
    assert by_task["g4"]["gates"][0]["post_dominators"] == ["work", "done"]
    assert (by_task["ab"]["reached_goal"], by_task["ab"]["gates"]) == (False, [])
    assert by_task["g1"]["path"] == ["todo", "work", "review", "done"]
