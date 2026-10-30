"""A native create writes the three creation bookkeeping fields as front matter, the feed and DTO read them back, and an edit sets and clears each."""

from pathlib import Path

from starpulse.board.adapters import native
from starpulse.board.adapters.upstream_backlog import UpstreamBacklog, _split
from starpulse.board.feed.shared import task_agent
from starpulse.contracts.api.dto.task import RawTask

KEYS = {
    "adrNeeded": "adr_needed",
    "duplicateSearch": "duplicate_search",
    "duplicateResolution": "duplicate_resolution",
}
DETAILS = {
    "adrNeeded": "Changes the create contract.",
    "duplicateSearch": "StarPulse create front matter adrNeeded duplicateSearch",
    "duplicateResolution": "TASK-9804 consumes these fields; none is a duplicate.",
}


def _board_root(base: Path) -> Path:
    return base / ".starpulse" / "board"


def _task_front(base: Path) -> dict:
    (path,) = (_board_root(base) / "tasks").iterdir()
    return _split(path.read_text())[0]


def test_create_front_matter_writes_the_three_fields_to_the_task_file(tmp_path: Path) -> None:
    built = native.board({}, tmp_path)

    assert built.create("Carry bookkeeping", DETAILS, actor="adin").ok

    front = _task_front(tmp_path)
    assert {key: front[key] for key in KEYS.values()} == {key: DETAILS[field] for field, key in KEYS.items()}


def test_create_front_matter_leaves_out_the_fields_a_create_does_not_name(tmp_path: Path) -> None:
    built = native.board({}, tmp_path)

    assert built.create("Carry bookkeeping", {}, actor="adin").ok

    assert not any(key in _task_front(tmp_path) for key in KEYS.values())


def test_create_front_matter_reaches_the_board_feed_and_dto(tmp_path: Path) -> None:
    built = native.board({}, tmp_path)
    assert built.create("Carry bookkeeping", DETAILS, actor="adin").ok
    tasks = []
    UpstreamBacklog(_board_root(tmp_path), tasks.append).scan()

    (task,) = tasks
    agent = task_agent(task)

    assert (agent["adr_needed"], agent["duplicate_search"], agent["duplicate_resolution"]) == (
        "Changes the create contract.",
        "StarPulse create front matter adrNeeded duplicateSearch",
        "TASK-9804 consumes these fields; none is a duplicate.",
    )
    assert RawTask.model_validate(agent).duplicate_resolution == "TASK-9804 consumes these fields; none is a duplicate."


def test_an_edit_sets_and_clears_each_creation_front_matter_field(tmp_path: Path) -> None:
    built = native.board({}, tmp_path)
    task = built.create("Carry bookkeeping", {}, actor="adin").output

    for field, key in KEYS.items():
        assert built.edit(task, {field: f"{key} set"}, "").ok
        assert _task_front(tmp_path)[key] == f"{key} set"
        assert built.edit(task, {field: ""}, "").ok
        assert key not in _task_front(tmp_path)
