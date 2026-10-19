"""The inotify watch on a board's task folders: the files that changed, read as they land."""

import contextlib
import ctypes
import os
import resource
import threading
import time
from pathlib import Path

import pytest

from starpulse._internal.board.dir_watch import DirWatch


def test_wait_names_the_file_written_in_a_watched_folder(tmp_path: Path) -> None:
    watch = DirWatch([tmp_path])
    (tmp_path / "task-1.md").write_text("x")

    assert watch.wait(5) == {tmp_path / "task-1.md"}
    watch.close()


def test_wait_names_both_ends_of_a_rename_between_folders(tmp_path: Path) -> None:
    (tmp_path / "tasks").mkdir()
    (tmp_path / "completed").mkdir()
    (tmp_path / "tasks" / "task-1.md").write_text("x")
    watch = DirWatch([tmp_path / "tasks", tmp_path / "completed"])
    (tmp_path / "tasks" / "task-1.md").rename(tmp_path / "completed" / "task-1.md")

    assert watch.wait(5) == {tmp_path / "tasks" / "task-1.md", tmp_path / "completed" / "task-1.md"}
    watch.close()


def test_wait_names_a_deleted_file_and_ignores_files_that_are_not_markdown(tmp_path: Path) -> None:
    (tmp_path / "task-1.md").write_text("x")
    watch = DirWatch([tmp_path])
    (tmp_path / "notes.tmp").write_text("x")
    (tmp_path / "task-1.md").unlink()

    assert watch.wait(5) == {tmp_path / "task-1.md"}
    watch.close()


def test_wait_returns_none_when_nothing_changed_within_the_timeout(tmp_path: Path) -> None:
    watch = DirWatch([tmp_path])

    assert watch.wait(0.05) is None
    watch.close()


def test_a_folder_that_appears_later_asks_for_a_rescan_and_is_then_watched(tmp_path: Path) -> None:
    later = tmp_path / "archive" / "tasks"
    watch = DirWatch([tmp_path, later])
    later.mkdir(parents=True)

    assert watch.wait(5) is None  # the new folder is a rescan, then watched
    (later / "task-9.md").write_text("x")

    assert watch.wait(5) == {later / "task-9.md"}
    watch.close()


def test_wait_wakes_for_a_write_from_another_thread(tmp_path: Path) -> None:
    watch = DirWatch([tmp_path])
    threading.Timer(0.05, (tmp_path / "task-2.md").write_text, ["x"]).start()
    started = time.monotonic()

    assert watch.wait(30) == {tmp_path / "task-2.md"}
    assert time.monotonic() - started < 5
    watch.close()


def test_wait_works_when_its_fds_are_past_the_select_limit(tmp_path: Path) -> None:
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(max(soft, 2048), hard), hard))
    with contextlib.ExitStack() as held:
        for _ in range(1100):
            held.callback(os.close, os.open(os.devnull, os.O_RDONLY))
        watch = DirWatch([tmp_path])
        (tmp_path / "task-3.md").write_text("x")

        assert watch.wait(5) == {tmp_path / "task-3.md"}
        watch.wake()
        assert watch.wait(5) == set()
        watch.close()
    resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def test_a_libc_without_inotify_raises_oserror_so_the_caller_polls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Libc:
        def __getattr__(self, name: str) -> object:
            raise AttributeError(f"dlsym(RTLD_DEFAULT, {name}): symbol not found")

    monkeypatch.setattr(ctypes, "CDLL", lambda *args, **kwargs: _Libc())

    with pytest.raises(OSError, match="inotify"):
        DirWatch([tmp_path])
