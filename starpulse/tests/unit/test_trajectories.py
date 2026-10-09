"""Trajectory analytics on fixture machines with hand-worked answers: variants and the norm, outliers ranked by
Levenshtein distance, the absorbing chain against the closed form (I-Q)^-1, Brandes betweenness against a brute-force
reference, dominator gates computed per trajectory, never on the union graph, and the in-flight forecast, what-if and
calibration over the loop-conditioned chain."""

from collections import defaultdict, deque
from collections.abc import Iterable
from random import Random

import pytest

from starpulse._internal.domain.level import Level, Terminal
from starpulse._internal.domain.level_metrics import Run, WindowPastHistory
from starpulse._internal.domain.trajectories import WhatIfRefused, betweenness, trajectory_analytics, what_if

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


def _days(hours: float) -> float:
    return hours * H / 86400.0


def test_a_run_counts_its_back_edges_and_loops_with_the_days_each_took() -> None:
    runs = [
        _run("clean", (0, "work"), (10, "review"), (20, "done")),
        _run("loop", (0, "work"), (10, "review"), (20, "work"), (30, "review"), (40, "done")),
        # two back-edges in one strongly connected component: work<->todo and work<->review
        _run("knot", (0, "todo"), (5, "work"), (10, "todo"), (15, "work"), (20, "review"), (25, "work"), (30, "done")),
    ]

    by_task = {r["task"]: r for r in _analytics(runs)["runs"]}

    assert (by_task["clean"]["back_edges"], by_task["clean"]["sccs"], by_task["clean"]["loops"]) == (0, 0, [])
    assert (by_task["loop"]["back_edges"], by_task["loop"]["sccs"]) == (1, 1)
    assert by_task["loop"]["loops"] == [{"from": "review", "to": "work", "trips": 1, "days": _days(20)}]
    assert (by_task["knot"]["back_edges"], by_task["knot"]["sccs"]) == (2, 1)


def test_the_level_sums_each_loop_across_the_runs_that_took_it() -> None:
    runs = [
        _run("a", (0, "work"), (10, "review"), (20, "work"), (30, "review"), (40, "done")),
        # review -> work twice: back to a work first entered at 0 (15 h), then to the one entered at 15 (15 h)
        _run("b", (0, "work"), (5, "review"), (15, "work"), (20, "review"), (30, "work"), (35, "review"), (40, "done")),
        _run("c", (0, "work"), (10, "review"), (20, "done")),
    ]

    assert _analytics(runs)["loops"] == [
        {"from": "review", "to": "work", "runs": 2, "trips": 3, "days": _days(50)},
    ]


def test_a_loop_that_exists_only_in_the_union_of_two_runs_is_never_reported() -> None:
    # todo -> work -> review in one run and review -> todo in the other close a cycle no run went round
    runs = [
        _run("one", (0, "todo"), (5, "work"), (10, "review"), (20, "done")),
        _run("two", (0, "review"), (3, "todo"), (9, "done")),
    ]

    result = _analytics(runs)

    assert result["loops"] == []
    assert [(r["back_edges"], r["sccs"]) for r in result["runs"]] == [(0, 0), (0, 0)]


def _copies(runs: list[Run], n: int) -> list[Run]:
    return [Run(run.source, f"{run.task}.{i}", run.steps) for i in range(n) for run in runs]


# CHAIN_RUNS five times over, so each loop-conditioned row is seen often enough to stand on its own
FIVE = _copies(CHAIN_RUNS, 5)


def test_a_run_still_going_gets_its_loop_conditioned_row_of_terminal_chances_and_remaining_days() -> None:
    going = [
        _run("fresh", (90, "work")),
        _run("reviewing", (80, "work"), (90, "review")),
        _run("again", (60, "work"), (70, "review"), (80, "work"), (90, "review")),  # one loop round so far
    ]

    forecast = {f["task"]: f for f in _analytics([*FIVE, *going])["forecast"]}

    # By state and loops so far: work/0 -> review/0 15 of 20, -> dropped 5 of 20; review/0 -> done 10 of 15,
    # -> work/1 5 of 15; work/1 -> review/1 5 of 5; review/1 -> done 5 of 5. Mean stays 13.5h, 26/3h, 10h, 10h.
    # Q over (work/0, review/0, work/1, review/1) is nilpotent, so N = (I-Q)^-1 = I + Q + Q^2 + Q^3, whose rows are
    # work/0 (1, .75, .25, .25), review/0 (0, 1, 1/3, 1/3) and review/1 (0, 0, 0, 1).
    assert set(forecast) == {"fresh", "reviewing", "again"}  # the ended runs are the chain's, not the forecast's
    assert forecast["fresh"] == {
        "source": "a",
        "task": "fresh",
        "state": "work",
        "loops": 0,
        "since": 90 * H,
        "p": {"done": pytest.approx(0.75, abs=1e-6), "dropped": pytest.approx(0.25, abs=1e-6)},
        "p_goal": pytest.approx(0.75, abs=1e-6),
        "expected_days": pytest.approx((13.5 + 0.75 * 26 / 3 + 0.25 * 10 + 0.25 * 10) / 24, abs=1e-6),
        "n": 20,
        "pooled": False,
    }
    reviewing, again = forecast["reviewing"], forecast["again"]
    assert (reviewing["loops"], reviewing["n"], reviewing["pooled"]) == (0, 15, False)
    assert reviewing["expected_days"] == pytest.approx((26 / 3 + 10 / 3 + 10 / 3) / 24, abs=1e-6)
    assert reviewing["p"] == {"done": pytest.approx(1.0, abs=1e-6), "dropped": pytest.approx(0.0, abs=1e-6)}
    assert (again["state"], again["loops"], again["n"], again["pooled"]) == ("review", 1, 5, False)
    assert again["expected_days"] == pytest.approx(10 / 24, abs=1e-6)
    assert again["p_goal"] == pytest.approx(1.0, abs=1e-6)


def test_a_loop_count_seen_too_rarely_pools_to_the_states_unconditioned_row() -> None:
    thrice = _run(
        "thrice", (0, "work"), (10, "review"), (20, "work"), (30, "review"), (40, "work"), (50, "review"), (60, "work")
    )
    unseen = _run("new", (90, "todo"))  # no ended run ever left todo

    forecast = {f["task"]: f for f in _analytics([*FIVE, thrice, unseen])["forecast"]}

    # work after three loops was never seen; the unconditioned work row has 25 exits and is the closed form of
    # Q = [[0, .8], [.25, 0]] over (work, review): N = [[1.25, 1], [.3125, 1.25]], h = (12.8h, 9h)
    assert (forecast["thrice"]["loops"], forecast["thrice"]["n"], forecast["thrice"]["pooled"]) == (3, 25, True)
    assert forecast["thrice"]["expected_days"] == pytest.approx((1.25 * 12.8 + 1 * 9) / 24, abs=1e-6)
    assert forecast["thrice"]["p"] == {"done": pytest.approx(0.75, abs=1e-6), "dropped": pytest.approx(0.25, abs=1e-6)}
    assert forecast["new"] | {"since": None} == {
        "source": "a",
        "task": "new",
        "state": "todo",
        "loops": 0,
        "since": None,
        "p": None,
        "p_goal": None,
        "expected_days": None,
        "n": 0,
        "pooled": True,
    }


# work -> review 100 of 110, -> dropped 10 of 110; review -> work 22 of 100 (22%), -> done 68, -> dropped 10.
# Every work stay is 10h and every review stay 5h.
WHAT_IF_RUNS = [
    *(_run(f"loop{i}", (0, "work"), (10, "review"), (15, "work"), (25, "review"), (30, "done")) for i in range(22)),
    *(_run(f"clean{i}", (0, "work"), (10, "review"), (15, "done")) for i in range(46)),
    *(_run(f"lost{i}", (0, "work"), (10, "review"), (15, "dropped")) for i in range(10)),
    *(_run(f"quit{i}", (0, "work"), (10, "dropped")) for i in range(10)),
]


def _what_if(runs: list[Run], origin: str, to: str, p: float) -> dict:
    return what_if(LEVEL, MACHINE, runs, now=NOW, window_s=WINDOW, origin=origin, to=to, p=p)


def test_a_what_if_cutting_one_transition_returns_the_hand_worked_change_in_the_goal_and_the_days() -> None:
    result = _what_if(WHAT_IF_RUNS, "review", "work", 0.10)

    # With a = 10/11 (work -> review), q review -> work, d review -> done and h = (10h, 5h):
    # P(goal | work) = a d / (1 - a q) and E(days | work) = (10 + 5a) / (1 - a q).
    # Before, q = .22 and d = .68: P = 17/22, E = 200/11 h. After, q = .10 and the other exits keep their shares of
    # what is left, so d = .68 * .90 / .78 = 51/65: P = 51/65, E = 16 h.
    assert (result["from"], result["to"], result["start"], result["n"]) == ("review", "work", "work", 100)
    assert (result["was"], result["p"]) == (pytest.approx(0.22), 0.10)
    assert result["p_goal"] == {
        "before": pytest.approx(17 / 22, abs=1e-9),
        "after": pytest.approx(51 / 65, abs=1e-9),
        "change": pytest.approx(17 / 1430, abs=1e-9),
    }
    assert result["expected_days"] == {
        "before": pytest.approx(200 / 11 / 24, abs=1e-9),
        "after": pytest.approx(16 / 24, abs=1e-9),
        "change": pytest.approx(-24 / 11 / 24, abs=1e-9),
    }
    assert result["chain"]["review"]["p_goal"] == pytest.approx((51 / 65) / (1 - 0.10 * 10 / 11), abs=1e-9)


@pytest.mark.parametrize(
    ("origin", "to", "p"),
    [
        ("todo", "work", 0.5),  # no ended run left todo
        ("review", "review", 0.5),  # a stay is no transition
        ("review", "nowhere", 0.5),  # not a state of the machine
        ("review", "work", 1.5),  # not a probability
    ],
)
def test_a_what_if_on_no_observed_row_or_no_probability_is_refused(origin: str, to: str, p: float) -> None:
    with pytest.raises(WhatIfRefused):
        _what_if(WHAT_IF_RUNS, origin, to, p)


def test_a_what_if_that_leaves_no_other_exit_or_no_way_out_is_refused() -> None:
    straight = [_run("s", (0, "work"), (10, "review"), (20, "done"))]

    with pytest.raises(WhatIfRefused, match="no other exit"):
        _what_if(straight, "work", "review", 0.5)  # work's only exit is review: nothing takes the other half
    with pytest.raises(WhatIfRefused, match="never finishes"):
        _what_if(straight, "review", "work", 1.0)  # work and review would hand a run back and forth forever


def test_the_calibration_scores_held_out_runs_per_decile_against_a_chain_fitted_without_them() -> None:
    held_out = [  # the latest fifth of the ended runs, all ending after every FIVE run
        _run("h1", (50, "work"), (55, "review"), (60, "done")),
        _run("h2", (60, "work"), (65, "dropped")),
        _run("h3", (60, "work"), (65, "review"), (70, "dropped")),
        _run("h4", (70, "work"), (75, "review"), (80, "done")),
        _run("h5", (80, "work"), (85, "review"), (90, "done")),
    ]

    calibration = _analytics([*FIVE, *held_out])["calibration"]

    # fitted on FIVE alone, every held-out work/0 step predicts .75 and every review/0 step 1.0
    deciles = calibration["deciles"]
    assert (calibration["fit"], calibration["held_out"], calibration["predictions"]) == (20, 5, 9)
    assert [(d["low"], d["high"]) for d in deciles] == [(i / 10, (i + 1) / 10) for i in range(10)]
    assert deciles[7] == {"low": 0.7, "high": 0.8, "n": 5, "runs": 5, "predicted": 0.75, "observed": 0.6}
    assert deciles[9] == {"low": 0.9, "high": 1.0, "n": 4, "runs": 4, "predicted": pytest.approx(1.0), "observed": 0.75}
    assert all(d["n"] == 0 and d["predicted"] is None for i, d in enumerate(deciles) if i not in {7, 9})
    assert calibration["calibrated"] is False  # .75 against .6 is 15 points off


def test_too_few_ended_runs_hold_none_out_and_score_nothing() -> None:
    calibration = _analytics(CHAIN_RUNS)["calibration"]

    assert (calibration["fit"], calibration["held_out"], calibration["predictions"]) == (4, 0, 0)
    assert calibration["calibrated"] is None


HUB_STATES = ("waiting", "ready", "in_progress", "needs_attention", "review", "done", "archived")
HUB = {"states": [{"id": s, "initial": s == "waiting", "final": s in {"done", "archived"}} for s in HUB_STATES]}
HUB_LEVEL = Level("board", "done", (Terminal("done", "goal"), Terminal("archived", "abandoned")))


def _hub(runs: list[Run]) -> dict:
    return trajectory_analytics(HUB_LEVEL, HUB, runs, now=NOW, window_s=WINDOW)


def test_regression_a_loop_target_the_search_met_first_is_not_a_trip_and_never_raises() -> None:
    # TASK-1 on the live hub: the depth-first search reaches in_progress by ready, so done -> in_progress is a back-edge
    # of the whole path, yet that step is the first visit of in_progress and has no earlier one to loop back to
    task_1 = _run(
        "TASK-1",
        (0, "done"),
        (1, "ready"),
        (2, "done"),
        (3, "in_progress"),
        (4, "ready"),
        (5, "in_progress"),
        (6, "archived"),
    )
    # TASK-1258: waiting -> needs_attention is likewise a back-edge whose step is needs_attention's first visit
    task_1258 = _run(
        "TASK-1258",
        *enumerate(
            ("waiting", "ready", "in_progress", "waiting", "needs_attention", "in_progress", "needs_attention")
            + ("in_progress", "review", "done")
        ),
    )

    result = _hub([task_1, task_1258])
    by_task = {r["task"]: r for r in result["runs"]}

    assert by_task["TASK-1"]["loops"] == [
        {"from": "in_progress", "to": "ready", "trips": 1, "days": _days(3)},
        {"from": "ready", "to": "done", "trips": 1, "days": _days(2)},
    ]
    assert (by_task["TASK-1"]["back_edges"], by_task["TASK-1"]["sccs"]) == (2, 1)
    assert by_task["TASK-1258"]["loops"] == [
        {"from": "needs_attention", "to": "in_progress", "trips": 2, "days": pytest.approx(_days(5))},
        {"from": "in_progress", "to": "waiting", "trips": 1, "days": pytest.approx(_days(3))},
    ]
    assert (by_task["TASK-1258"]["back_edges"], by_task["TASK-1258"]["sccs"]) == (2, 1)


def test_no_walk_over_the_board_machine_makes_the_analytics_raise() -> None:
    rng = Random(3308)
    runs = []
    for i in range(400):
        length = rng.randint(1, 14)
        states = [rng.choice(HUB_STATES) for _ in range(length)]
        if i % 4:  # three of four end in a terminal, the rest are still going
            states.append(rng.choice(("done", "archived")))
        runs.append(_run(f"w{i}", *((float(at), state) for at, state in enumerate(states))))

    result = _hub(runs)

    assert result["ended"] > 0 and result["forecast"]
    for trajectory in result["runs"]:
        assert trajectory["back_edges"] == len(trajectory["loops"])
        assert all(loop["trips"] >= 1 and loop["days"] >= 0 for loop in trajectory["loops"])
    assert all(f["loops"] >= 0 for f in result["forecast"])


def test_a_run_swept_from_the_goal_into_a_settle_ended_in_the_goal_when_it_reached_it() -> None:
    swept = {"states": MACHINE["states"] + [{"id": "completed", "initial": False, "final": True}]}
    runs = [
        _run("t1", (0, "work"), (10, "review"), (20, "done"), (30, "completed")),
        _run("t2", (0, "work"), (10, "review"), (25, "done")),
    ]

    result = trajectory_analytics(LEVEL, swept, runs, now=NOW, window_s=WINDOW)

    assert result["ended"] == 2
    assert result["variants"] == [{"path": ["work", "review", "done"], "count": 2, "share": 1.0}]
    assert {run["task"]: run["reached_goal"] for run in result["runs"]} == {"t1": True, "t2": True}
