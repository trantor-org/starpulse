"""Retired tasks on the native board: `retire` moves a finished task's file into the history store's
`starpulse_retired_tasks`, `retired` reads it back, `restore` returns it, `import_retired` takes one a client kept, and
numbering and dependency states still count it."""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from starpulse._internal.board.native import board
from starpulse._internal.board.seam import Board
from starpulse._internal.board.upstream_backlog import UpstreamBacklog
from starpulse._internal.board.view import board_flow, task_view
from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.feed.board_feed import BoardFeed
from starpulse._internal.server import writes
from starpulse._internal.server.server import assemble
from starpulse.tests.unit.board.test_native import native_root, write_task
from starpulse.tests.unit.board.test_native_rules import done_needs


@pytest.fixture
def started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Board, Path]:
    """The default native board, started on a history store in `tmp_path`, holding a Done `task-5`."""
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    built, feed = assemble(load(None), tmp_path, None, ())
    write_task(tmp_path, "task-5", "Done")
    built.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"))
    return built, tmp_path


def _path(base: Path, task: str = "task-5", folder: str = "tasks") -> Path:
    return native_root(base) / folder / f"{task} - Title.md"


def test_a_retired_done_task_leaves_the_board_and_its_file_is_kept_byte_for_byte(
    started: tuple[Board, Path],
) -> None:
    built, base = started
    assert built.retire is not None and built.retired is not None
    text = _path(base).read_bytes().decode()

    written = built.retire("task-5")

    assert written.ok, written.output
    assert not _path(base).exists()
    assert built.retired("task-5") == [{"task": "task-5", "name": "task-5 - Title.md", "text": text}]
    assert built.retired("TASK-5") == built.retired("task-5")
    assert built.retired("") == built.retired("task-5")
    assert built.retired("task-6") == []


def test_a_retired_task_may_come_from_completed_or_the_archive_whatever_its_status(
    started: tuple[Board, Path],
) -> None:
    built, base = started
    assert built.retire is not None and built.retired is not None and built.complete is not None
    assert built.archive is not None
    write_task(base, "task-6", "In Progress")
    assert built.complete("task-5").ok
    assert built.archive("task-6", "").ok

    assert built.retire("task-5").ok
    assert built.retire("task-6").ok

    assert [row["task"] for row in built.retired("")] == ["task-5", "task-6"]
    assert list(native_root(base).glob("**/*.md")) == []


def test_retiring_an_open_or_unknown_task_is_refused_and_keeps_its_file(started: tuple[Board, Path]) -> None:
    built, base = started
    assert built.retire is not None and built.retired is not None
    open_task = write_task(base, "task-6", "In Progress")

    assert not built.retire("task-6").ok
    assert not built.retire("task-404").ok

    assert open_task.is_file()
    assert built.retired("") == []


def test_retiring_a_task_whose_number_is_kept_with_other_text_is_refused_and_keeps_its_file(
    started: tuple[Board, Path],
) -> None:
    built, base = started
    assert built.retire is not None and built.retired is not None
    kept = _path(base).read_bytes().decode()
    assert built.retire("task-5").ok
    rewritten = write_task(base, "task-5", "Done", priority="high")

    refused = built.retire("task-5")

    assert not refused.ok and "task-5" in refused.output
    assert rewritten.is_file()
    assert [row["text"] for row in built.retired("task-5")] == [kept]


def test_a_board_that_has_not_started_keeps_no_retired_tasks(tmp_path: Path) -> None:
    built = board({}, tmp_path)
    write_task(tmp_path, "task-5", "Done")
    assert built.retire is not None and built.retired is not None

    assert not built.retire("task-5").ok
    assert built.retired("") == []
    assert _path(tmp_path).is_file()


def test_a_restore_returns_a_retired_task_to_tasks_unchanged(started: tuple[Board, Path]) -> None:
    built, base = started
    assert built.retire is not None and built.retired is not None and built.restore is not None
    before = _path(base).read_bytes()
    assert built.retire("task-5").ok

    restored = built.restore("task-5")

    assert restored.ok, restored.output
    assert _path(base).read_bytes() == before
    assert built.retired("task-5") == []


def test_a_restore_of_a_retired_task_never_replaces_a_file_and_keeps_the_row(started: tuple[Board, Path]) -> None:
    built, base = started
    assert built.retire is not None and built.retired is not None and built.restore is not None
    assert built.retire("task-5").ok
    other = write_task(base, "task-6", "To Do")
    other.rename(_path(base))  # another task's file under task-5's name

    assert not built.restore("task-5").ok

    assert len(built.retired("task-5")) == 1


def test_a_new_task_numbers_past_the_retired_tasks(started: tuple[Board, Path]) -> None:
    built, _ = started
    assert built.retire is not None and built.create is not None
    assert built.retire("task-5").ok

    assert built.create("Next", {}).output == "task-6"


def test_a_dependency_on_a_retired_task_is_in_the_state_it_was_retired_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(UpstreamBacklog, "start", lambda self, interval, scanned: (self.scan(), scanned()))
    settings = replace(load(None), board={"rules": [done_needs({"dependencies": {"all_in": ["Done"]}})]})
    built, feed = assemble(settings, tmp_path, None, ())
    write_task(tmp_path, "task-5", "Done")
    write_task(tmp_path, "task-1", "In Progress", dependencies="[task-5]")
    built.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"))
    assert built.retire is not None and built.writer is not None
    assert built.retire("task-5").ok

    assert built.writer("task-1", "Done", "operator").ok


def test_an_imported_retired_task_is_kept_and_the_same_import_again_is_accepted(started: tuple[Board, Path]) -> None:
    built, base = started
    assert built.import_retired is not None and built.retired is not None
    text = "---\nid: task-3\ntitle: Old\nstatus: Done\n---\n"

    first = built.import_retired("task-3 - Old.md", text)
    again = built.import_retired("task-3 - Old.md", text)

    assert (first.ok, first.output, again.ok) == (True, "task-3", True)
    assert built.retired("task-3") == [{"task": "task-3", "name": "task-3 - Old.md", "text": text}]


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("task-3 - Old.md", "---\nid: task-3\ntitle: Other\nstatus: Done\n---\n"),  # differs from the kept task-3
        ("task-5 - Title.md", "---\nid: task-5\ntitle: Title\nstatus: Done\n---\n"),  # task-5 is on the board
        ("task-7 - New.md", "no front matter"),
        ("../task-7.md", "---\nid: task-7\nstatus: Done\n---\n"),  # a name that is no plain file name
    ],
    ids=["differs-from-the-kept-copy", "on-the-board", "no-id", "not-a-file-name"],
)
def test_an_import_of_a_retired_task_is_refused_when_it_conflicts_or_names_no_task(
    started: tuple[Board, Path], name: str, text: str
) -> None:
    built, _ = started
    assert built.import_retired is not None and built.retired is not None
    assert built.import_retired("task-3 - Old.md", "---\nid: task-3\ntitle: Old\nstatus: Done\n---\n").ok

    assert not built.import_retired(name, text).ok

    assert [row["task"] for row in built.retired("")] == ["task-3"]


LAN = "192.168.0.42"


def _raw(**body: object) -> bytes:
    return json.dumps(body).encode()


def test_the_retire_route_answers_the_task_and_the_writers_refusal(started: tuple[Board, Path]) -> None:
    built, _ = started

    retired = writes.retire_task(LAN, _raw(task="task-5"), built)
    again = writes.retire_task(LAN, _raw(task="task-5"), built)

    assert retired == (200, {"task": "task-5"})
    assert again[0] == 409 and "task-5" in again[1]["error"]


@pytest.mark.parametrize(
    ("source", "raw", "status"),
    [("8.8.8.8", _raw(task="task-5"), 403), (LAN, b"{}", 400), (LAN, _raw(task=5), 400), (LAN, b"nope", 400)],
    ids=["outside-the-lan", "no-task", "task-not-text", "not-json"],
)
def test_the_retire_route_refuses_a_non_lan_caller_and_a_malformed_body(
    started: tuple[Board, Path], source: str, raw: bytes, status: int
) -> None:
    built, base = started

    assert writes.retire_task(source, raw, built)[0] == status

    assert _path(base).is_file()


def test_the_retired_route_reads_one_or_every_retired_task(started: tuple[Board, Path]) -> None:
    built, base = started
    text = _path(base).read_text()
    assert built.retire is not None and built.retire("task-5").ok
    row = {"task": "task-5", "name": "task-5 - Title.md", "text": text}

    assert writes.retired_list(built, "") == (200, {"tasks": [row]})
    assert writes.retired_list(built, "task-5") == (200, {"tasks": [row]})
    assert writes.retired_list(built, "task-6") == (200, {"tasks": []})


def test_the_retired_import_route_answers_the_task_and_refuses_a_conflict(started: tuple[Board, Path]) -> None:
    built, _ = started
    text = "---\nid: task-3\nstatus: Done\n---\n"

    imported = writes.import_retired(LAN, _raw(name="task-3.md", text=text), built)
    differing = writes.import_retired(LAN, _raw(name="task-3.md", text=text + "more\n"), built)
    malformed = writes.import_retired(LAN, _raw(name="task-3.md"), built)
    outside = writes.import_retired("8.8.8.8", _raw(name="task-4.md", text=text), built)

    assert imported == (200, {"task": "task-3"})
    assert [differing[0], malformed[0], outside[0]] == [409, 400, 403]


@pytest.mark.parametrize("board_without", [None, Board(machines=lambda qualify, workflows: {}, start=lambda *_: None)])
def test_the_retired_routes_on_a_board_that_keeps_no_retired_tasks_are_404(board_without: Board | None) -> None:
    assert writes.retire_task(LAN, _raw(task="task-5"), board_without)[0] == 404
    assert writes.retired_list(board_without, "")[0] == 404
    assert writes.import_retired(LAN, _raw(name="task-3.md", text="---\nid: task-3\n---\n"), board_without)[0] == 404


@pytest.fixture
def scanning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Board, BoardFeed, UpstreamBacklog, Path]:
    """The default native board started on a history store, its first scan done; the caller scans again by hand."""
    scans: list[UpstreamBacklog] = []

    def start(self: UpstreamBacklog, interval: float, scanned: Callable[[], None]) -> None:
        scans.append(self)
        self.scan()
        scanned()

    monkeypatch.setattr(UpstreamBacklog, "start", start)
    built, feed = assemble(load(None), tmp_path, None, ())
    write_task(tmp_path, "task-5", "Done")
    write_task(tmp_path, "task-6", "To Do", dependencies="[task-5]")
    built.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"))
    return built, feed, scans[0], tmp_path


def _waiting_on(feed: BoardFeed, task: str) -> list[str]:
    snapshot = feed.snapshot()
    return task_view(next(a for a in board_flow(snapshot)["agents"] if a["id"] == task), snapshot)["waiting_on"]


def test_a_dependent_of_a_retired_done_task_is_workable_and_not_waiting(
    scanning: tuple[Board, BoardFeed, UpstreamBacklog, Path],
) -> None:
    built, feed, backlog, _ = scanning
    assert built.retire is not None and built.retire("task-5").ok

    backlog.scan()

    assert feed.is_done("task-5")
    assert feed.task("task-6")["workable"]
    assert _waiting_on(feed, "task-6") == []


def test_a_dependent_of_a_done_task_imported_as_retired_is_workable_and_not_waiting(
    scanning: tuple[Board, BoardFeed, UpstreamBacklog, Path],
) -> None:
    built, feed, backlog, base = scanning
    assert built.import_retired is not None
    write_task(base, "task-7", "Done")
    text = _path(base, "task-7").read_text()
    _path(base, "task-7").unlink()
    write_task(base, "task-8", "To Do", dependencies="[task-7]")
    backlog.scan()
    assert not feed.task("task-8")["workable"]

    assert built.import_retired("task-7 - Title.md", text).ok
    backlog.scan()

    assert feed.task("task-8")["workable"]
    assert _waiting_on(feed, "task-8") == []


def test_a_dependent_of_an_archived_then_retired_task_stays_waiting(
    scanning: tuple[Board, BoardFeed, UpstreamBacklog, Path],
) -> None:
    built, feed, backlog, base = scanning
    assert built.archive is not None and built.retire is not None
    write_task(base, "task-7", "To Do")
    assert built.archive("task-7", "").ok
    write_task(base, "task-8", "To Do", dependencies="[task-7]")  # the archiver refuses once it exists
    backlog.scan()
    assert built.retire("task-7").ok

    backlog.scan()

    assert not feed.is_done("task-7")
    assert not feed.task("task-8")["workable"]
    assert _waiting_on(feed, "task-8") == ["task-7"]


def test_a_restored_retired_task_is_open_again_for_its_dependents(
    scanning: tuple[Board, BoardFeed, UpstreamBacklog, Path],
) -> None:
    built, feed, backlog, _ = scanning
    assert built.retire is not None and built.restore is not None
    assert built.retire("task-5").ok
    backlog.scan()

    assert built.restore("task-5").ok
    backlog.scan()

    assert feed.is_done("task-5")
    assert feed.task("task-5") is not None
