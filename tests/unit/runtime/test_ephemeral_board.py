"""`ephemeral_board` builds a disposable board of tasks through StarPulse's write seam and reads their records back."""

from pathlib import Path

import pytest
from starpulse.runtime.ephemeral_board import EphemeralBoardError, TaskSeed, ephemeral_board


def test_a_board_of_seeds_returns_each_tasks_record_in_order() -> None:
    seeds = [TaskSeed("First", description="why", criteria=("one", "two")), TaskSeed("Second", labels=("x",))]
    with ephemeral_board(seeds) as board:
        titles = [record["title"] for record in board.records]
        criteria = [item["text"] for item in board.records[0]["criteria"]]
        labels = board.records[1]["labels"]
        ids = [record["id"] for record in board.records]
    assert (titles, criteria, labels) == (["First", "Second"], ["one", "two"], ["x"])
    assert len(set(ids)) == 2


def test_a_bare_title_is_a_seed() -> None:
    with ephemeral_board(["Only"]) as board:
        assert [record["title"] for record in board.records] == ["Only"]


def test_a_record_is_read_again_after_a_verb_changes_the_task() -> None:
    with ephemeral_board(["Before"]) as board:
        task = board.records[0]["id"]
        board.instance.run("task", "edit", task, "--title", "After")
        assert board.record(task)["title"] == "After"


def test_the_board_files_live_under_the_given_base_and_stay_after_the_block(tmp_path: Path) -> None:
    with ephemeral_board(["Kept"], base=tmp_path) as board:
        folder = board.instance.board
    assert folder.is_relative_to(tmp_path)
    assert any("Kept" in file.read_text() for file in (folder / "tasks").glob("*.md"))


def test_a_create_the_board_refuses_raises_with_the_reason() -> None:
    with pytest.raises(EphemeralBoardError, match="status"):
        with ephemeral_board([TaskSeed("Bad", flags=("--status", "no-such-lane"))]):
            pass
