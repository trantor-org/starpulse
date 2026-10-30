"""The two capacity dimensions the board and the harness events feed: review load and sessions held."""

from starpulse.scheduler.model.inputs import review_points, sessions_held


def _task(lane: str, *labels: str) -> dict:
    return {"id": "T", "state": lane, "labels": list(labels)}


def _held(lane: str, task: str) -> dict:
    return {"id": task, "state": lane}


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
        _held("in_progress", "A"),  # mid-turn
        _held("in_progress", "B"),  # idle on a wake: still a resident session
        _held("ready", "C"),
        _held("review", "D"),
    ]

    assert sessions_held(tasks, "in_progress", [], now=1000.0) == 2


def test_an_active_harness_session_counts_in_any_lane_once() -> None:
    tasks = [_held("in_progress", "A"), _held("ready", "B")]
    agents = [
        {"id": "A", "state": "active", "active": 990.0},  # already held In Progress
        {"id": "B", "state": "active", "active": 995.0},
        {"id": "C", "state": "stopped", "active": 999.0},
        {"id": "D", "state": "idle", "active": 999.0},
    ]

    assert sessions_held(tasks, "in_progress", agents, now=1000.0, stale_s=60.0) == 2


def test_an_active_session_with_no_event_past_the_bound_is_not_held() -> None:
    """A session killed mid-tool never gets its Stop, so its machine reads active until the history window drops it."""
    agents = [{"id": "A", "state": "active", "active": 1000.0 - 61.0}, {"id": "B", "state": "active", "active": 940.0}]

    assert sessions_held([], "in_progress", agents, now=1000.0, stale_s=60.0) == 1
