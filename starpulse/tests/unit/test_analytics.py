"""Board health from lane changes: dwell, WIP and throughput equal hand-computed values, an open stay counts to now."""

from starpulse.projections.analytics import board_health
from starpulse.tests.machines import MACHINES

H = 3600.0
NOW = 100 * H
WINDOW = 48 * H  # from 52h to 100h
STUCK = 24 * H

#: (task, at, from, to) as the history keeps them.
ROWS = [
    ("A", 50 * H, None, "To Do"),
    ("A", 60 * H, "To Do", "Ready"),
    ("A", 70 * H, "Ready", "In Progress"),
    ("A", 80 * H, "In Progress", "Review"),
    ("A", 90 * H, "Review", "Done"),
    ("B", 60 * H, None, "Ready"),
    ("B", 70 * H, "Ready", "In Progress"),
    ("B", 85 * H, "In Progress", "Review"),
    ("B", 86 * H, "Review", "In Progress"),
    ("B", 95 * H, "In Progress", "Done"),
    ("C", 30 * H, None, "Ready"),  # left Ready before the window opened
    ("C", 40 * H, "Ready", "In Progress"),  # and is still in progress
    ("D", 99 * H, None, "Ready"),  # still ready, for an hour
    ("E", 10 * H, None, "To Do"),  # still in the initial lane
    ("F", 30 * H, None, "In Progress"),
    ("F", 40 * H, "In Progress", "Done"),  # done before the window opened
]
BOARD = MACHINES["board"]


def _health(rows=ROWS, gaps=(), window_s=WINDOW, stuck_s=STUCK) -> dict:
    return board_health(BOARD, rows, list(gaps), now=NOW, window_s=window_s, stuck_s=stuck_s)


def _states(health: dict) -> dict:
    return {state["id"]: state for state in health["states"]}


def test_dwell_per_state_is_the_visits_that_ended_in_the_window_or_are_open() -> None:
    states = _states(_health())

    assert {k: states["to_do"][k] for k in ("visits", "mean_s", "max_s", "open")} == {
        "visits": 2,
        "mean_s": 50 * H,  # A 10h, E 90h to now
        "max_s": 90 * H,
        "open": 1,
    }
    assert {k: states["ready"][k] for k in ("visits", "mean_s", "max_s", "open")} == {
        "visits": 3,  # A 10h, B 10h, D 1h to now; C left Ready before the window
        "mean_s": 7 * H,
        "max_s": 10 * H,
        "open": 1,
    }
    assert {k: states["in_progress"][k] for k in ("visits", "mean_s", "max_s", "open")} == {
        "visits": 4,  # A 10h, B 15h and 9h, C 60h to now; F left before the window
        "mean_s": 23.5 * H,
        "max_s": 60 * H,
        "open": 1,
    }
    assert {k: states["review"][k] for k in ("visits", "mean_s", "max_s", "open")} == {
        "visits": 2,  # A 10h, B 1h
        "mean_s": 5.5 * H,
        "max_s": 10 * H,
        "open": 0,
    }


def test_wip_is_the_tasks_now_in_each_state_and_a_final_state_has_no_dwell() -> None:
    states = _states(_health())

    assert {sid: s["wip"] for sid, s in states.items()} == {
        "to_do": 1,
        "ready": 1,
        "in_progress": 1,
        "review": 0,
        "done": 3,
    }
    assert states["done"] == {"id": "done", "name": "Done", "final": True, "wip": 3}


def test_throughput_is_the_entries_to_a_final_state_in_the_window() -> None:
    assert _health()["throughput"] == {"count": 2, "per_day": 1.0}  # A and B; F finished before the window


def test_a_task_still_in_its_state_counts_dwell_to_now_and_is_flagged_so() -> None:
    health = _health()

    assert health["stuck"] == [
        {
            "task": "C",
            "state": "in_progress",
            "since": 40 * H,
            "dwell_s": 60 * H,
            "counted_to_now": True,
        }
    ]  # D is under the threshold, E is in the initial lane, A and B are done
    assert _states(health)["in_progress"]["open"] == 1
    assert health["now"] == NOW


def test_a_shorter_stuck_threshold_lists_the_longest_stay_first() -> None:
    stuck = _health(stuck_s=0.5 * H)["stuck"]

    assert [(s["task"], s["dwell_s"]) for s in stuck] == [("C", 60 * H), ("D", 1 * H)]


def test_the_window_and_threshold_are_reported() -> None:
    health = _health()

    assert (health["window_s"], health["stuck_after_s"]) == (WINDOW, STUCK)


def test_recorded_history_gaps_appear_as_warnings() -> None:
    gap = {"stream": "machine:events", "after_id": "5-0", "before_id": "9-0", "lost": 3}

    assert _health()["warnings"] == []
    (warning,) = _health(gaps=[gap])["warnings"]
    assert warning | {"message": ""} == {"kind": "gap", **gap, "message": ""}
    assert "3" in warning["message"] and "machine:events" in warning["message"]


def test_a_lane_that_is_not_a_board_state_is_a_warning_and_leaves_the_numbers_alone() -> None:
    rows = [*ROWS, ("G", 90 * H, None, "Blocked")]

    health = _health(rows)

    assert {k: v for k, v in health.items() if k != "warnings"} == {
        k: v for k, v in _health().items() if k != "warnings"
    }
    (warning,) = health["warnings"]
    assert warning["kind"] == "unknown_lane" and "Blocked" in warning["message"]


def test_a_lane_may_name_its_state_by_id() -> None:
    by_id = [(task, at, old, new and new.lower().replace(" ", "_")) for task, at, old, new in ROWS]

    assert _health(by_id) == _health()
