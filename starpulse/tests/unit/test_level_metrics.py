"""Level aggregates on the Backlog flow metric definitions: WIP, throughput, aging, time in state and the orbit shares
equal hand-worked values, and a window longer than the history is refused with the history's length."""

import pytest

from starpulse.level import Level, Terminal
from starpulse.level_metrics import UNATTRIBUTED, Run, WindowPastHistory, level_metrics

H = 3600.0
NOW = 100 * H
WINDOW = 48 * H  # from 52h to 100h

MACHINE = {
    "states": [
        {"id": "to_do", "initial": True, "final": False},
        {"id": "work", "initial": False, "final": False},
        {"id": "review", "initial": False, "final": False},
        {"id": "done", "initial": False, "final": True},
        {"id": "dropped", "initial": False, "final": True},
    ]
}
LEVEL = Level("board", "done", (Terminal("done", "goal"), Terminal("dropped", "abandoned")))


def _run(source: str, task: str, *steps: tuple[float, str]) -> Run:
    return Run(source, task, tuple((at * H, state) for at, state in steps))


RUNS = [
    _run("a", "A1", (10, "to_do"), (60, "work"), (70, "review"), (80, "done")),
    _run("a", "A2", (40, "work"), (55, "dropped")),
    _run("a", "A3", (90, "work")),  # still working
    _run("b", "B1", (60, "work"), (90, "done")),  # first sighted already working
    _run("b", "B2", (50, "work"), (70, "review")),  # still in review
    _run(UNATTRIBUTED, "C1", (20, "to_do")),  # never left the initial state
]


def _metrics(runs=RUNS, window_s=WINDOW) -> dict:
    return level_metrics(LEVEL, MACHINE, runs, now=NOW, window_s=window_s)


def _source(metrics: dict, id: str) -> dict:
    return next(source for source in metrics["sources"] if source["id"] == id)


def test_wip_counts_the_runs_now_in_a_working_state_and_not_the_initial_or_a_final_one() -> None:
    assert _metrics()["wip"] == {"count": 2, "states": {"work": 1, "review": 1}}  # A3 and B2; not C1, A1, A2, B1


def test_throughput_is_the_goal_entries_inside_the_window_that_follow_an_observed_state() -> None:
    assert _metrics()["throughput"] == {"count": 2, "per_day": 1.0}  # A1 at 80h, B1 at 90h over two days


def test_a_run_first_sighted_in_the_goal_is_no_completion() -> None:
    runs = [*RUNS, _run("b", "B3", (95, "done"))]

    assert _metrics(runs)["throughput"]["count"] == 2


def test_a_run_that_enters_the_goal_twice_completes_twice() -> None:
    runs = [_run("a", "R", (60, "work"), (70, "done"), (80, "work"), (90, "done"))]

    assert _metrics(runs, window_s=40 * H)["throughput"]["count"] == 2


def test_an_entry_before_the_window_opened_is_no_throughput() -> None:
    runs = [_run("a", "R", (10, "work"), (20, "done"))]

    assert _metrics(runs, window_s=40 * H)["throughput"] == {"count": 0, "per_day": 0.0}


def test_aging_is_the_hours_since_a_run_first_entered_a_working_state_against_the_cycle_time_p85() -> None:
    aging = _metrics()["aging"]

    assert aging["threshold_s"] == 30 * H  # cycle times A1 20h, B1 30h; nearest rank 0.85 * 2 is the second
    assert aging["runs"] == [
        {"source": "b", "task": "B2", "state": "review", "age_s": 50 * H, "over": True},
        {"source": "a", "task": "A3", "state": "work", "age_s": 10 * H, "over": False},
    ]


def test_aging_has_no_threshold_when_no_completion_has_an_observed_start() -> None:
    aging = _metrics([_run("a", "A", (60, "work"))], window_s=40 * H)["aging"]

    assert aging["threshold_s"] is None
    assert aging["runs"] == [{"source": "a", "task": "A", "state": "work", "age_s": 40 * H, "over": False}]


def test_time_in_state_clips_each_stay_to_the_window_and_counts_an_open_stay_to_now() -> None:
    states = {state["id"]: state for state in _metrics()["time_in_state"]}

    assert states == {
        "to_do": {"id": "to_do", "visits": 2, "task_s": 56 * H, "mean_s": 28 * H},  # A1 8h, C1 48h
        "work": {"id": "work", "visits": 5, "task_s": 71 * H, "mean_s": 14.2 * H},  # 10 + 3 + 10 + 30 + 18
        "review": {"id": "review", "visits": 2, "task_s": 40 * H, "mean_s": 20 * H},  # A1 10h, B2 30h
    }


def test_each_source_with_ended_runs_has_terminal_shares_that_sum_to_one() -> None:
    metrics = _metrics()

    assert _source(metrics, "a")["ended"] == {"done": 1, "dropped": 1}
    assert _source(metrics, "a")["terminal_share"] == {"done": 0.5, "dropped": 0.5}
    assert _source(metrics, "b")["terminal_share"] == {"done": 1.0, "dropped": 0.0}
    assert metrics["orbit"]["terminals"] == {"done": {"ended": 2}, "dropped": {"ended": 1}}


def test_each_source_with_working_time_has_state_shares_that_sum_to_one() -> None:
    metrics = _metrics()

    assert _source(metrics, "a")["time_share"] == {"work": pytest.approx(23 / 33), "review": pytest.approx(10 / 33)}
    assert _source(metrics, "b")["time_share"] == {"work": pytest.approx(48 / 78), "review": pytest.approx(30 / 78)}
    for source in ("a", "b"):
        assert sum(_source(metrics, source)["time_share"].values()) == pytest.approx(1.0)
    assert metrics["orbit"]["working"] == {"work": {"task_s": 71 * H}, "review": {"task_s": 40 * H}}


def test_a_source_with_nothing_ended_or_worked_has_no_shares_rather_than_zero_ones() -> None:
    source = _source(_metrics(), UNATTRIBUTED)

    assert source["terminal_share"] == {}
    assert source["time_share"] == {}


def test_a_source_reports_its_dwell_in_each_working_state() -> None:
    assert _source(_metrics(), "a")["dwell"] == {
        "work": {"visits": 3, "task_s": 23 * H, "mean_s": 23 * H / 3},
        "review": {"visits": 1, "task_s": 10 * H, "mean_s": 10 * H},
    }


def test_the_orbit_working_states_narrow_which_states_the_time_shares_cover() -> None:
    level = Level("board", "done", LEVEL.terminals, orbit=LEVEL.orbit.__class__("working", ("work",)))

    metrics = level_metrics(level, MACHINE, RUNS, now=NOW, window_s=WINDOW)

    assert _source(metrics, "a")["time_share"] == {"work": 1.0}
    assert list(metrics["orbit"]["working"]) == ["work"]


def test_a_window_longer_than_the_history_is_refused_with_the_history_length() -> None:
    with pytest.raises(WindowPastHistory) as refused:
        _metrics(window_s=91 * H)

    assert refused.value.history_s == 90 * H  # the first step is at 10h
    assert "90" in str(refused.value)


def test_a_window_as_long_as_the_history_is_answered() -> None:
    assert _metrics(window_s=90 * H)["throughput"]["count"] == 2


def test_a_history_with_no_runs_refuses_every_window() -> None:
    with pytest.raises(WindowPastHistory) as refused:
        _metrics([])

    assert refused.value.history_s == 0


def test_arrivals_list_each_entry_into_a_terminal_inside_the_window_oldest_first() -> None:
    arrivals = _metrics()["arrivals"]

    assert arrivals == [
        {"source": "a", "state": "dropped", "at": 55 * H},
        {"source": "a", "state": "done", "at": 80 * H},
        {"source": "b", "state": "done", "at": 90 * H},
    ]


def test_an_arrival_before_the_window_or_a_first_sighting_in_a_terminal_is_not_listed() -> None:
    runs = [_run("a", "old", (10, "work"), (20, "done")), _run("a", "seen", (95, "done"))]

    assert _metrics(runs)["arrivals"] == []


def test_the_answer_carries_the_levels_config_for_the_page_to_draw() -> None:
    config = Level(
        "board",
        "done",
        (Terminal("done", "goal"), Terminal("dropped", "abandoned")),
        gates=("review",),
        title="Flow",
        subject="story",
        runs="sessions",
    )

    answer = level_metrics(config, MACHINE, RUNS, now=NOW, window_s=WINDOW)

    assert answer["level"] == {
        "title": "Flow",
        "subject": "story",
        "runs": "sessions",
        "gates": ["review"],
        "terminals": [{"id": "done", "role": "goal"}, {"id": "dropped", "role": "abandoned"}],
        "orbit": {"suns": "terminal", "working": []},
        "facets": [],
        "activity": {"measure": "share", "pace": "min"},
    }


def test_a_source_is_shared_unless_no_forwarder_named_it() -> None:
    metrics = _metrics()

    assert [(s["id"], s["shared"]) for s in metrics["sources"]] == [("a", True), ("b", True), (UNATTRIBUTED, False)]
