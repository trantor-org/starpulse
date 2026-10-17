"""A board scan keeps no retired task's text: it streams the rows when they change, and a task's text reads back from
`starpulse_retired_tasks` by id on request."""

from pathlib import Path

import pytest

from starpulse._internal.board import native
from starpulse._internal.board.native import _Retired
from starpulse._internal.board.seam import Board
from starpulse._internal.board.upstream_backlog import UpstreamBacklog
from starpulse._internal.config.config import load
from starpulse._internal.eventlog.event_log import EventLog
from starpulse._internal.server.server import assemble
from starpulse.tests.unit.board.test_native import native_root, write_task


def _holds(value: object, text: str) -> bool:
    """Whether `text` is `value` or sits anywhere inside a container it reaches."""
    if isinstance(value, str):
        return value == text
    if isinstance(value, dict):
        return any(_holds(item, text) for item in (*value.keys(), *value.values()))
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_holds(item, text) for item in value)
    return False


@pytest.fixture
def started(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Board, UpstreamBacklog]:
    """The default native board on a history store in `tmp_path`, holding Done `task-5` and `task-6`."""
    adapters: list[UpstreamBacklog] = []

    def scan_once(self: UpstreamBacklog, interval: float, scanned: object) -> None:
        adapters.append(self)
        self.scan()

    monkeypatch.setattr(UpstreamBacklog, "start", scan_once)
    built, feed = assemble(load(None), tmp_path, None, ())
    write_task(tmp_path, "task-5", "Done")
    write_task(tmp_path, "task-6", "Done")
    built.start(feed, "test", EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}"))
    return built, adapters[0]


def test_a_scan_settles_a_retired_done_task_without_holding_its_text(
    started: tuple[Board, UpstreamBacklog], tmp_path: Path
) -> None:
    built, adapter = started
    assert built.retire is not None and built.retired is not None
    text = (native_root(tmp_path) / "tasks" / "task-5 - Title.md").read_bytes().decode()
    built.retire("task-5")

    adapter.scan()

    assert adapter._settled_retired == {"task-5"}
    assert not any(_holds(held, text) for held in vars(adapter).values())
    assert built.retired("task-5")[0]["text"] == text


def test_the_reader_streams_every_text_in_id_order_across_pages(
    started: tuple[Board, UpstreamBacklog], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built, _ = started
    assert built.retire is not None and built.retired is not None
    monkeypatch.setattr(native, "_RETIRED_PAGE", 1)
    for task in ("task-6", "task-5"):
        built.retire(task)
    texts = [row["text"] for row in built.retired("")]
    retired = _Retired()
    retired.engine = EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}").engine

    assert list(retired.texts()) == texts
    assert len(texts) == 2


def test_the_change_reader_answers_none_until_the_rows_change_or_a_read_is_forced(
    started: tuple[Board, UpstreamBacklog], tmp_path: Path
) -> None:
    built, _ = started
    assert built.retire is not None
    retired = _Retired()
    retired.engine = EventLog(f"sqlite:///{tmp_path / 'history.sqlite'}").engine
    read = retired.changes()
    built.retire("task-5")

    assert read() is not None
    assert read() is None
    assert read(force=True) is not None
    built.retire("task-6")
    assert read() is not None


def test_an_unstarted_board_reads_no_retired_text() -> None:
    retired = _Retired()

    assert retired.changes()(force=True) is None
    assert list(retired.texts()) == []
