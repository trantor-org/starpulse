"""The file watch the event log wakes on: a commit to the store's files makes its descriptor readable."""

import select
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from starpulse.event_log import watch


def _store(tmp_path: Path) -> tuple[str, sqlite3.Connection]:
    """A WAL store with a connection held open, so its `-wal` file outlives a commit."""
    path = str(tmp_path / "events.sqlite")
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("CREATE TABLE t (n INTEGER)")
    return path, holder


def _readable(opened: watch.FileWatch, timeout: float = 2.0) -> bool:
    return bool(select.select([opened.fileno()], [], [], timeout)[0])


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="inotify is Linux's")
def test_inotify_reports_a_commit_by_another_connection(tmp_path: Path) -> None:
    path, holder = _store(tmp_path)
    opened = watch.open_watch(path)
    assert opened is not None
    try:
        assert not _readable(opened, 0)

        other = sqlite3.connect(path, isolation_level=None)
        other.execute("INSERT INTO t VALUES (1)")
        other.close()

        assert _readable(opened)
        assert opened.drain() is True
        assert not _readable(opened, 0)
    finally:
        opened.close()
        holder.close()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="inotify is Linux's")
def test_inotify_ignores_a_write_to_a_file_beside_the_store(tmp_path: Path) -> None:
    path, holder = _store(tmp_path)
    opened = watch.open_watch(path)
    assert opened is not None
    try:
        (tmp_path / "other.txt").write_text("beside")

        assert opened.drain() is False
    finally:
        opened.close()
        holder.close()


@pytest.mark.skipif(not hasattr(select, "kqueue"), reason="kqueue is the BSDs'")
def test_kqueue_reports_a_commit_by_another_connection(tmp_path: Path) -> None:
    path, holder = _store(tmp_path)
    opened = watch.open_watch(path)
    assert opened is not None
    try:
        other = sqlite3.connect(path, isolation_level=None)
        other.execute("INSERT INTO t VALUES (1)")
        other.close()

        assert _readable(opened)
        assert opened.drain() is True
    finally:
        opened.close()
        holder.close()


def test_a_platform_with_neither_watch_opens_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(watch, "_inotify", lambda database: None)
    monkeypatch.setattr(watch, "_kqueue", lambda database: None)

    assert watch.open_watch(str(tmp_path / "events.sqlite")) is None


class _FakeKqueue:
    def __init__(self) -> None:
        self.registered: list[SimpleNamespace] = []
        self.pending: list[SimpleNamespace] = []
        self.closed = False

    def control(self, changes: list[SimpleNamespace] | None, count: int, timeout: float | None = None) -> list[SimpleNamespace]:
        if changes is not None:
            self.registered.extend(changes)
            return []
        pending, self.pending = self.pending, []
        return pending

    def fileno(self) -> int:
        return 99

    def close(self) -> None:
        self.closed = True


def _fake_kqueue(monkeypatch: pytest.MonkeyPatch) -> _FakeKqueue:
    queue = _FakeKqueue()
    flags = {"KQ_FILTER_VNODE": -4, "KQ_EV_ADD": 1, "KQ_EV_CLEAR": 0x20}
    flags |= {"KQ_NOTE_WRITE": 2, "KQ_NOTE_EXTEND": 4, "KQ_NOTE_DELETE": 1, "KQ_NOTE_RENAME": 0x20}
    for name, value in flags.items():
        monkeypatch.setattr(select, name, value, raising=False)
    monkeypatch.setattr(select, "kqueue", lambda: queue, raising=False)
    monkeypatch.setattr(
        select,
        "kevent",
        lambda fd, kind, how, notes: SimpleNamespace(ident=fd, fflags=notes),
        raising=False,
    )
    return queue


def test_the_kqueue_adapter_watches_the_directory_and_the_files_and_picks_up_a_file_created_later(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = _fake_kqueue(monkeypatch)
    database = tmp_path / "events.sqlite"
    database.touch()

    opened = watch._kqueue(str(database))

    assert opened is not None
    assert opened.fileno() == 99
    assert len(queue.registered) == 2  # the directory and the database; the `-wal` file does not exist yet
    wal = tmp_path / "events.sqlite-wal"
    wal.touch()
    queue.pending = [SimpleNamespace(ident=queue.registered[0].ident, fflags=2)]
    assert opened.drain() is True
    assert len(queue.registered) == 3  # the directory write brought the new `-wal` file in
    assert opened.drain() is False
    opened.close()
    assert queue.closed


def test_the_kqueue_adapter_opens_a_deleted_file_again_when_it_is_recreated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    queue = _fake_kqueue(monkeypatch)
    database = tmp_path / "events.sqlite"
    wal = tmp_path / "events.sqlite-wal"
    database.touch()
    wal.touch()
    opened = watch._kqueue(str(database))
    assert opened is not None
    wal_ident = queue.registered[2].ident

    wal.unlink()
    queue.pending = [SimpleNamespace(ident=wal_ident, fflags=1)]
    assert opened.drain() is True
    wal.touch()
    queue.pending = [SimpleNamespace(ident=queue.registered[0].ident, fflags=2)]
    assert opened.drain() is True

    assert len(queue.registered) == 4
    opened.close()


def test_a_kqueue_that_cannot_open_is_no_watch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse() -> None:
        raise OSError("no descriptors")

    monkeypatch.setattr(select, "kqueue", refuse, raising=False)

    assert watch._kqueue(str(tmp_path / "events.sqlite")) is None
