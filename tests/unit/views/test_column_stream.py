"""Which changes make a held or lanes stream read its view again."""

import json
from pathlib import Path

import pytest
from starpulse.views.adapters.inbound.column_stream import Interest, column_view

UUID = "d6444e26-7301-475b-82eb-50ee2bd5d9b1"
URL = "https://claude.ai/code/session_01DTu8XJxdtoSs93ZhuGrRHa"


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


@pytest.fixture
def bridged_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    folder = tmp_path / ".claude" / "projects" / "-home-adinb-trantor"
    folder.mkdir(parents=True)
    (folder / f"{UUID}.jsonl").write_text(json.dumps({"bridgeSessionId": "cse_01DTu8XJxdtoSs93ZhuGrRHa"}) + "\n")


@pytest.mark.usefixtures("bridged_home")
@pytest.mark.parametrize(("claimed", "asked"), [(URL, UUID), (UUID, URL)])
def test_a_held_view_lists_the_task_whichever_form_of_the_session_claimed_and_asked(claimed: str, asked: str) -> None:
    columns = [{"state": "in_progress", "tasks": [_task("T-1", claimed), _task("T-2", "https://claude.ai/code/session_x")]}]

    view = column_view(columns, asked, ())

    assert [t["id"] for c in view["columns"] for t in c["tasks"]] == ["T-1"]


@pytest.mark.usefixtures("bridged_home")
def test_a_held_stream_is_touched_by_a_change_claimed_under_the_other_form_of_its_session() -> None:
    interest = _held(UUID, _task("T-1", URL))

    assert interest.touched_by(*_change("T-2", assignee=URL))
    assert not interest.touched_by(*_change("T-3", assignee="https://claude.ai/code/session_x"))
