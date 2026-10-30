"""The two capacity dimensions the board and the harness events feed: review load and sessions held."""

from starpulse.scheduler.model.inputs import review_points, sessions_held


def _task(lane: str, *labels: str) -> dict:
    return {"id": "T", "state": lane, "labels": list(labels)}


def test_review_load_is_the_points_of_the_tasks_in_the_review_lane() -> None:
    tasks = [
        _task("review", "size-3", "kind-execute"),
        _task("review", "size-5"),
        _task("ready", "size-8"),  # another lane: not review load
        _task("in_progress", "size-2"),
    ]

    assert review_points(tasks, "review", unsized=3) == 8


def test_an_unsized_task_in_review_counts_the_default_weight() -> None:
    assert review_points([_task("review"), _task("review", "bug")], "review", unsized=3) == 6


def test_a_malformed_size_label_is_unsized() -> None:
    assert review_points([_task("review", "size-big", "size-")], "review", unsized=2) == 2


def test_an_empty_review_lane_is_no_load() -> None:
    assert review_points([], "review", unsized=3) == 0


def test_every_task_in_the_working_lane_is_a_held_session() -> None:
    tasks = [
        _task("in_progress"),  # mid-turn
        _task("in_progress"),  # idle on a wake: still a resident session
        _task("ready"),
        _task("review"),
    ]

    assert sessions_held(tasks, "in_progress") == 2


def test_no_working_task_holds_no_session() -> None:
    assert sessions_held([_task("ready")], "in_progress") == 0
