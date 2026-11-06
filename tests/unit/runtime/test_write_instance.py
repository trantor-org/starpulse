"""`write_instance` serves a config's board with its write routes, and a verb run through it writes a task file."""

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest
from starpulse.runtime.write_instance import WriteInstance, write_instance


def _board(base: Path) -> None:
    (base / "starpulse.toml").write_text('[board]\npath = "board"\n')


def test_a_verb_creates_a_task_file_and_a_second_verb_edits_the_task_it_made(tmp_path: Path) -> None:
    _board(tmp_path)
    with write_instance(tmp_path) as instance:
        created = instance.run("task", "create", "First")
        task = json.loads(created.stdout)["task"]
        edited = instance.run("task", "edit", task, "--title", "Second")
    assert (created.returncode, edited.returncode) == (0, 0), (created, edited)
    assert any("Second" in file.read_text() for file in (tmp_path / "board" / "tasks").glob("*.md"))


def test_a_verb_naming_a_task_the_polling_thread_never_placed_is_placed_by_the_retry(tmp_path: Path) -> None:
    _board(tmp_path)
    with write_instance(tmp_path) as instance:
        task = json.loads(instance.run("task", "create", "First").stdout)["task"]
        for backlog in instance.backlogs:
            backlog.stop()  # a starved or dead polling thread: only a scan the caller runs can place the task now
        time.sleep(0.2)
        edited = instance.run("task", "edit", task, "--title", "Second")
    assert edited.returncode == 0, edited


def test_a_verb_the_board_refuses_exits_nonzero_with_the_reason(tmp_path: Path) -> None:
    _board(tmp_path)
    with write_instance(tmp_path) as instance:
        refused = instance.run("task", "edit", "task-99", "--title", "Nope")
    assert refused.returncode == 4
    assert "task-99" in refused.stdout + refused.stderr


def test_no_board_thread_outlives_the_block(tmp_path: Path) -> None:
    """Each instance once left its `board-state` and `claim-ttl` threads waiting forever, so a suite that opens one per
    test ran out of threads."""
    _board(tmp_path)
    before = set(threading.enumerate())
    with write_instance(tmp_path) as instance:
        instance.run("task", "create", "First")
    board_threads = {"board-state", "claim-ttl"}
    left = [thread.name for thread in threading.enumerate() if thread not in before and thread.name in board_threads]
    assert left == []


@pytest.mark.unmigrated
def test_its_scratch_store_is_migrated_before_the_board_publishes_to_it(tmp_path: Path) -> None:
    """A store opens only once `starpulse migrate` ran, and nothing outside the block can migrate the scratch one."""
    _board(tmp_path)
    with write_instance(tmp_path) as instance:
        created = instance.run("task", "create", "First")
    assert created.returncode == 0


@pytest.mark.parametrize("reply", ["{task} is not on the board", "{task} has no record to read"])
def test_a_verb_naming_a_task_whose_file_exists_runs_again_until_the_feed_has_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    _board(tmp_path)
    with write_instance(tmp_path) as instance:
        task = json.loads(instance.run("task", "create", "First").stdout)["task"]
        answers = [subprocess.CompletedProcess([], 4, "", reply.format(task=task)), subprocess.CompletedProcess([], 0, "", "")]
        monkeypatch.setattr(WriteInstance, "_once", lambda self, argv: answers.pop(0))
        done = instance.run("task", "edit", task, "--title", "Second")
    assert (done.returncode, answers) == (0, [])
