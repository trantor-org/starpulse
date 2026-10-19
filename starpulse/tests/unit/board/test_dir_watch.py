"""The poll of a board's task folders: the files that changed, read as they land."""

import threading
import time
from pathlib import Path

from starpulse._internal.board.dir_watch import DirWatch


def test_wait_names_the_file_written_in_a_watched_folder(tmp_path: Path) -> None:
    watch = DirWatch([tmp_path])
    (tmp_path / "task-1.md").write_text("x")

    assert watch.wait(5) == {tmp_path / "task-1.md"}


def test_wait_names_a_rewritten_file(tmp_path: Path) -> None:
    (tmp_path / "task-1.md").write_text("x")
    watch = DirWatch([tmp_path])
    (tmp_path / "task-1.md").write_text("xy")

    assert watch.wait(5) == {tmp_path / "task-1.md"}
    assert watch.wait(0.05) is None


def test_wait_names_both_ends_of_a_rename_between_folders(tmp_path: Path) -> None:
    (tmp_path / "tasks").mkdir()
    (tmp_path / "completed").mkdir()
    (tmp_path / "tasks" / "task-1.md").write_text("x")
    watch = DirWatch([tmp_path / "tasks", tmp_path / "completed"])
    (tmp_path / "tasks" / "task-1.md").rename(tmp_path / "completed" / "task-1.md")

    assert watch.wait(5) == {tmp_path / "tasks" / "task-1.md", tmp_path / "completed" / "task-1.md"}


def test_wait_names_a_deleted_file_and_ignores_files_that_are_not_markdown(tmp_path: Path) -> None:
    (tmp_path / "task-1.md").write_text("x")
    watch = DirWatch([tmp_path])
    (tmp_path / "notes.tmp").write_text("x")
    (tmp_path / "task-1.md").unlink()

    assert watch.wait(5) == {tmp_path / "task-1.md"}


def test_wait_returns_none_when_nothing_changed_within_the_timeout(tmp_path: Path) -> None:
    watch = DirWatch([tmp_path])

    assert watch.wait(0.05) is None


def test_a_folder_that_appears_later_has_its_files_named(tmp_path: Path) -> None:
    later = tmp_path / "archive" / "tasks"
    watch = DirWatch([tmp_path, later])
    later.mkdir(parents=True)
    (later / "task-9.md").write_text("x")

    assert watch.wait(5) == {later / "task-9.md"}


def test_wait_sees_a_write_from_another_thread_before_its_timeout(tmp_path: Path) -> None:
    watch = DirWatch([tmp_path])
    threading.Timer(0.05, (tmp_path / "task-2.md").write_text, ["x"]).start()
    started = time.monotonic()

    assert watch.wait(30) == {tmp_path / "task-2.md"}
    assert time.monotonic() - started < 5


def test_wake_ends_the_current_and_every_later_wait_with_no_files(tmp_path: Path) -> None:
    watch = DirWatch([tmp_path])
    threading.Timer(0.05, watch.wake).start()

    assert watch.wait(30) == set()
    assert watch.wait(30) == set()
