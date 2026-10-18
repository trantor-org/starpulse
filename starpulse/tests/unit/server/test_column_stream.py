"""Which changes make a held or lanes stream read its view again."""

from starpulse._internal.server.column_stream import Interest


def _task(
    task_id: str, assignee: str = "", state: str = "in_progress", dependencies: tuple[str, ...] = (), prs: tuple = ()
) -> dict:
    return {"id": task_id, "assignee": assignee, "lane": state, "dependencies": list(dependencies), "prs": list(prs)}


def _view(*tasks: dict) -> dict:
    return {"columns": [{"state": "in_progress", "name": "In Progress", "tasks": list(tasks)}]}


def _change(task_id: str, assignee: str = "", state: str = "in_progress") -> tuple[str, dict]:
    return "task", {"id": task_id, "agent": {"id": task_id, "assignee": assignee, "state": state}, "settled": None}


def _held(assignee: str, *tasks: dict) -> Interest:
    return Interest(_view(*tasks), assignee, ())


def test_a_held_stream_is_touched_by_its_own_tasks_before_or_after_a_change() -> None:
    interest = _held("a", _task("T-1", "a"))

    assert interest.touched_by(*_change("T-1", assignee="b"))  # handed away: it held it before
    assert interest.touched_by(*_change("T-2", assignee="a"))  # taken: it holds it after
    assert not interest.touched_by(*_change("T-3", assignee="b"))


def test_a_held_stream_is_touched_by_a_dependency_of_its_tasks_and_by_a_removal() -> None:
    interest = _held("a", _task("T-1", "a", dependencies=("T-0",)))

    assert interest.touched_by(*_change("T-0", assignee="b", state="done"))
    assert interest.touched_by("task", {"id": "T-1", "agent": None, "settled": {"state": "archived"}})
    assert not interest.touched_by("task", {"id": "T-9", "agent": None, "settled": None})


def test_a_lanes_stream_is_touched_only_by_a_change_into_or_out_of_its_states() -> None:
    interest = Interest(_view(_task("T-1")), None, ("in_progress",))

    assert interest.touched_by(*_change("T-1", state="review"))
    assert interest.touched_by(*_change("T-2", state="in_progress"))
    assert not interest.touched_by(*_change("T-3", state="ready"))


def test_other_kinds_touch_a_stream_only_when_the_view_reads_them() -> None:
    plain, pulled = _held("a", _task("T-1", "a")), _held("a", _task("T-1", "a", prs=({"url": "u"},)))

    assert plain.touched_by("snapshot", {})
    assert not plain.touched_by("pulls", {"pulls": {}})
    assert pulled.touched_by("pulls", {"pulls": {}})
    assert not pulled.touched_by("claim", {})
    assert not pulled.touched_by("dags", {})
