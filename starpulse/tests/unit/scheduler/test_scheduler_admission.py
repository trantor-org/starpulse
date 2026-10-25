"""Admission: a task's demand against the capacity left, and the rank of the tasks that fit."""

import logging
from pathlib import Path
from typing import Any

import pytest

from starpulse._internal.config.scheduler import DIMENSIONS, Scheduler
from starpulse.scheduler.model.admission import MIN_RUNS, NO_PROFILE, decide, demand, ranks_from_trajectories_body
from starpulse.scheduler.model.ledger import Ledger, RunRecord
from starpulse.scheduler.model.sampler import Reading
from starpulse.event_log.event_log import EventLog

POLICY = Scheduler(lane="ready")  # limits: cpu 80, memory 80, sessions 2, review 20; weights fast 1, standard 2, deep 4


def _task(
    id: str = "T-1",
    size: int | None = 8,
    profile: str = "@agent-standard-high",
    deps: tuple[str, ...] = (),
    **more: Any,
) -> dict[str, Any]:
    labels = [f"size-{size}"] if size else []
    return {
        "id": id,
        "state": "ready",
        "model": profile,
        "labels": labels,
        "dependencies": list(deps),
        "workable": True,
    } | more


def _readings(policy: Scheduler = POLICY, **use: float) -> list[Reading]:
    """Every dimension at no use against `policy`'s limits, but those in `use`."""
    return [Reading(name, use.get(name, 0), policy.limits[name]) for name in DIMENSIONS]


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    return Ledger(EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"), tmp_path / "runs.jsonl")


def test_demand_starts_from_the_points_times_the_tier_weight(ledger: Ledger) -> None:
    # 8 points x the standard weight 2: 16 percent of CPU and of memory; one session; 8 points of review.
    assert demand(_task(), POLICY, ledger) == {"cpu": 16, "memory": 16, "sessions": 1, "review": 8}


def test_an_unsized_task_costs_the_default_points_and_an_unknown_tier_the_dearest_weight(ledger: Ledger) -> None:
    unsized = demand(_task(size=None, profile="@agent-mystery"), POLICY, ledger)

    assert unsized == {"cpu": 12, "memory": 12, "sessions": 1, "review": 3}  # 3 points x the deep weight 4


def test_measured_demand_replaces_the_prior_once_enough_runs_exist(ledger: Ledger) -> None:
    peak = {"cpu": 30.0, "memory": 5.0, "sessions": 1, "review": 8}
    for _ in range(MIN_RUNS):
        ledger.record(RunRecord("T-0", "standard", 8, "review", 60.0, peak))

    assert demand(_task(), POLICY, ledger) == peak


@pytest.mark.parametrize("dimension", DIMENSIONS)
def test_a_task_that_overfits_one_dimension_is_refused_while_the_others_have_headroom(
    ledger: Ledger, dimension: str
) -> None:
    # Each reading leaves less room than the 16 / 16 / 1 / 8 the task draws, on its own dimension only.
    nearly_full = {"cpu": 70, "memory": 70, "sessions": 2, "review": 15}

    [decision] = decide([_task()], "ready", _readings(**{dimension: nearly_full[dimension]}), POLICY, {}, ledger)

    assert (decision.admitted, decision.blocked_by) == (False, dimension)


def test_a_task_that_fits_every_dimension_is_admitted(ledger: Ledger) -> None:
    [decision] = decide([_task()], "ready", _readings(cpu=60, memory=60, sessions=1, review=10), POLICY, {}, ledger)

    assert (decision.admitted, decision.blocked_by) == (True, None)


# Ranking. Ten sessions allowed, so a task's dominant share is its CPU, memory or review share, not the session.
ROOMY = Scheduler(lane="ready", limits={**POLICY.limits, "sessions": 10})


def _decide(tasks: list[dict[str, Any]], ledger: Ledger, chain: dict[str, Any] | None = None, **more: Any) -> list[Any]:
    return decide(tasks, "ready", _readings(ROOMY), ROOMY, chain or {}, ledger, **more)


def _by_rank(decisions: list[Any], rank: str) -> list[str]:
    return [d.task for d in sorted((d for d in decisions if d.admitted), key=lambda d: getattr(d, rank))]


def _cheap_shallow_and_dear_deep() -> list[dict[str, Any]]:
    """`CHEAP` is small and has no dependents (depth 1); `DEAR` is big and `AFTER` waits on it (depth 2)."""
    return [
        _task("CHEAP", size=2, profile="@agent-fast-low"),
        _task("DEAR", size=8),
        _task("AFTER", size=1, profile="@agent-fast-low", deps=("DEAR",), state="waiting"),
    ]


def test_the_shadow_rank_orders_by_value_over_dominant_share_while_the_enforced_order_stays_critical_path_depth(
    ledger: Ledger,
) -> None:
    # CHEAP: value 1, dominant share 0.1 (sessions and review): 10. DEAR: value 2, dominant share 0.4 (review): 5.
    decisions = _decide(_cheap_shallow_and_dear_deep(), ledger)

    assert _by_rank(decisions, "shadow_rank") == ["CHEAP", "DEAR"]
    assert _by_rank(decisions, "enforced_rank") == ["DEAR", "CHEAP"]  # shadow is on: the deeper task goes first


def test_with_shadow_off_the_enforced_order_is_the_shadow_order(ledger: Ledger) -> None:
    decisions = _decide(_cheap_shallow_and_dear_deep(), ledger, shadow=False)

    assert _by_rank(decisions, "enforced_rank") == ["CHEAP", "DEAR"]


def test_a_decision_is_made_with_no_predictor_and_no_history_and_carries_the_ranks_and_p_goal(ledger: Ledger) -> None:
    [decision] = _decide([_task()], ledger)

    assert (decision.p_goal, decision.predictor, decision.depth) == (1.0, None, 1)
    assert (decision.shadow_rank, decision.enforced_rank) == (1, 1)


def test_p_goal_is_the_chains_chance_of_the_goal_from_the_tasks_lane(ledger: Ledger) -> None:
    chain = {"ready": {"p_goal": 0.25, "expected_days": 3.0}}

    [decision] = _decide([_task()], ledger, chain)

    assert decision.p_goal == 0.25


def test_a_per_task_p_goal_scores_the_shadow_rank_and_never_the_enforced_order(ledger: Ledger) -> None:
    tasks = [_task("A"), _task("B")]

    decisions = _decide(tasks, ledger, p_goals={"A": 0.1, "B": 0.9})

    assert {d.task: d.p_goal for d in decisions} == {"A": 0.1, "B": 0.9}
    assert _by_rank(decisions, "shadow_rank") == ["B", "A"]
    assert _by_rank(decisions, "enforced_rank") == ["A", "B"]


def test_a_task_without_a_forecast_keeps_the_lanes_chain_p_goal(ledger: Ledger) -> None:
    chain = {"ready": {"p_goal": 0.25, "expected_days": 3.0}}

    [decision] = _decide([_task("A")], ledger, chain, p_goals={"B": 0.9})

    assert decision.p_goal == 0.25


def test_a_predictor_scores_the_shadow_rank_and_never_the_enforced_order(ledger: Ledger) -> None:
    tasks = [_task("A", title="a plain fix"), _task("B", title="a risky rewrite")]

    decisions = _decide(tasks, ledger, predictor=lambda text: 0.9 if "risky" in text else 0.1)

    assert {d.task: d.predictor for d in decisions} == {"A": 0.1, "B": 0.9}
    assert _by_rank(decisions, "shadow_rank") == ["B", "A"]
    assert _by_rank(decisions, "enforced_rank") == ["A", "B"]  # equal depth: the task id breaks the tie, not the score


def test_depth_counts_the_longest_chain_of_open_tasks_waiting_on_a_task(ledger: Ledger) -> None:
    tasks = [
        _task("ROOT"),
        _task("MID", deps=("ROOT",), state="waiting"),
        _task("LEAF", deps=("MID", "ROOT"), state="waiting"),
    ]

    [decision] = _decide(tasks, ledger)

    assert decision.depth == 3


def test_only_workable_tasks_in_the_eligible_lane_are_decided(ledger: Ledger) -> None:
    tasks = [_task("OK"), _task("BLOCKED", workable=False), _task("ELSEWHERE", state="in_progress")]

    assert [d.task for d in _decide(tasks, ledger)] == ["OK"]


def test_a_refused_task_has_no_rank_and_follows_the_admitted(ledger: Ledger) -> None:
    tasks = [_task("HUGE", size=40), _task("SMALL", size=1)]  # 40 points x 2 is 80 percent of CPU; 70 are left

    decisions = decide(tasks, "ready", _readings(ROOMY, cpu=10), ROOMY, {}, ledger)

    assert [(d.task, d.admitted, d.shadow_rank, d.enforced_rank) for d in decisions] == [
        ("SMALL", True, 1, 1),
        ("HUGE", False, None, None),
    ]


@pytest.mark.parametrize("profile", ["", "@agent-mystery-high"])
def test_a_task_with_no_agent_profile_is_refused_for_it(
    ledger: Ledger, caplog: pytest.LogCaptureFixture, profile: str
) -> None:
    """Started without one, a session would run on whatever model its harness defaults to."""
    with caplog.at_level(logging.INFO, logger="starpulse.scheduler.model.admission"):
        decisions = _decide([_task("NONE", size=1, profile=profile), _task("OK")], ledger)

    assert [(d.task, d.admitted, d.blocked_by) for d in decisions] == [("OK", True, None), ("NONE", False, NO_PROFILE)]
    assert any("NONE refused (no agent profile)" in r.getMessage() for r in caplog.records)


def test_each_decision_is_logged_with_its_p_goal_and_both_ranks(
    ledger: Ledger, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="starpulse.scheduler.model.admission"):
        _decide([_task("T-9")], ledger, {"ready": {"p_goal": 0.5}})

    [line] = [r.getMessage() for r in caplog.records]
    assert "T-9" in line and "p_goal=0.50" in line and "shadow_rank=1" in line and "enforced_rank=1" in line


def test_ranks_from_trajectories_body_take_forecast_rows_in_the_eligible_lane() -> None:
    body = {
        "chain": {"ready": {"p_goal": 0.5, "expected_days": 1.0}},
        "forecast": [
            {"task": "A", "state": "ready", "p_goal": 0.1},
            {"task": "B", "state": "in_progress", "p_goal": 0.9},
            {"task": "C", "state": "ready", "p_goal": None},
        ],
    }

    ranks = ranks_from_trajectories_body(body, "ready")

    assert ranks["chain"]["ready"]["p_goal"] == 0.5
    assert ranks["p_goals"] == {"A": 0.1}


def test_a_predictor_that_fails_leaves_the_decision_without_a_score(ledger: Ledger) -> None:
    def broken(text: str) -> float:
        raise RuntimeError(text)

    [decision] = _decide([_task()], ledger, predictor=broken)

    assert (decision.admitted, decision.predictor) == (True, None)


def test_a_high_priority_leaf_outranks_a_deeper_low_priority_chain(ledger: Ledger) -> None:
    tasks = [
        _task("CHAIN", impact="low", urgency="low"),  # weight 1 x depth 3
        _task("MID", deps=("CHAIN",), state="waiting"),
        _task("END", deps=("MID",), state="waiting"),
        _task("LEAF", impact="high", urgency="high"),  # weight 9 x depth 1
    ]

    decisions = _decide(tasks, ledger)

    assert _by_rank(decisions, "enforced_rank") == ["LEAF", "CHAIN"]
    assert {d.task: d.priority for d in decisions} == {"CHAIN": "low/low", "LEAF": "high/high"}


def test_a_task_with_no_impact_or_urgency_ranks_with_the_matrixs_default_weight(ledger: Ledger) -> None:
    policy = Scheduler(lane="ready", priority_matrix={**Scheduler().priority_matrix, "default": 3})
    tasks = [
        _task("BARE"),  # no Impact or Urgency: the default weight 3 x depth 1
        _task("LOW", impact="low", urgency="low"),  # weight 1 x depth 2
        _task("AFTER", deps=("LOW",), state="waiting"),
    ]

    decisions = decide(tasks, "ready", _readings(policy), policy, {}, ledger)

    assert _by_rank(decisions, "enforced_rank") == ["BARE", "LOW"]
    assert next(d for d in decisions if d.task == "BARE").priority == "default"
