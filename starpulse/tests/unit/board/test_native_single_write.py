"""One native task write is one file write, stamped in UTC, and a `[board] validate` hook can refuse it before it lands."""

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from starpulse._internal.board import native
from starpulse._internal.board.native import board
from starpulse._internal.board.seam import Written
from starpulse._internal.board.upstream_backlog import _split

#: The hook's calls, as `(file name, before, after)`; the hook refuses any write whose text holds `REFUSE`.
CALLS: list[tuple[str, str | None, str]] = []
REFUSE = "refuse this write"
HOOK = f"{__name__}:refuse_marked"


def refuse_marked(path: Path, before: str | None, after: str) -> str | None:
    CALLS.append((path.name, before, after))
    return "the hook refused it" if REFUSE in after else None


@pytest.fixture(autouse=True)
def _fresh_calls() -> None:
    CALLS.clear()


def _tasks(base: Path) -> Path:
    return base / ".starpulse" / "board" / "tasks"


def _snapshot(base: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in _tasks(base).iterdir()}


def _replaces(monkeypatch: pytest.MonkeyPatch, base: Path) -> list[Path]:
    """Every `os.replace` the adapter makes into `tasks/`, recorded and then performed."""
    landed: list[Path] = []
    real = os.replace

    def replace(source: os.PathLike[str], target: os.PathLike[str]) -> None:
        if Path(target).parent == _tasks(base):
            landed.append(Path(target))
        real(source, target)

    monkeypatch.setattr(native.os, "replace", replace)
    return landed


def test_a_create_with_every_field_writes_the_file_once_holding_them_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = board({}, tmp_path)
    landed = _replaces(monkeypatch, tmp_path)

    written = built.create(
        "Draw the board",
        {
            "description": "Draw it.",
            "labels": ["ui"],
            "acceptanceCriteria": ["It draws"],
            "status": "In Progress",
            "type": "feature",
            "references": ["https://example.test/1"],
            "documentation": ["docs/spec.md"],
            "definitionOfDone": [{"text": "Docs updated", "checked": False}],
            "plan": "1. Draw",
            "notes": "Started",
        },
    )

    assert written.ok, written.output
    assert len(landed) == 1
    frontmatter, body = _split(landed[0].read_text())
    assert frontmatter["status"] == "In Progress"
    assert frontmatter["type"] == "feature"
    assert frontmatter["references"] == ["https://example.test/1"]
    assert frontmatter["documentation"] == ["docs/spec.md"]
    assert "- [ ] #1 Docs updated" in body
    assert "1. Draw" in body and "Started" in body and "- [ ] #1 It draws" in body


def test_a_create_refuses_a_field_it_cannot_write_and_writes_nothing(tmp_path: Path) -> None:
    built = board({}, tmp_path)

    written = built.create("Draw the board", {"status": "Nowhere"})

    assert not written.ok
    assert _snapshot(tmp_path) == {}


def test_an_edit_with_three_comments_writes_the_file_once_holding_them_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = board({}, tmp_path)
    task = built.create("Draw the board", {}).output
    landed = _replaces(monkeypatch, tmp_path)

    written = built.edit(task, {"plan": "1. Draw"}, ["first", "second", "third"])

    assert written.ok, written.output
    assert len(landed) == 1
    text = landed[0].read_text()
    assert text.index("first") < text.index("second") < text.index("third")
    assert "1. Draw" in text


@pytest.fixture
def _phoenix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "America/Phoenix")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.mark.usefixtures("_phoenix")
def test_create_and_edit_stamp_their_dates_in_utc(tmp_path: Path) -> None:
    built = board({}, tmp_path)
    before = datetime.now(timezone.utc).replace(second=0, microsecond=0)

    task = built.create("Draw the board", {}).output
    created = _split(next(_tasks(tmp_path).iterdir()).read_text())[0]
    built.edit(task, {"plan": "1. Draw"}, "")
    edited = _split(next(_tasks(tmp_path).iterdir()).read_text())[0]

    after = datetime.now(timezone.utc) + timedelta(minutes=1)
    for stamp in (created["created_date"], created["updated_date"], edited["updated_date"]):
        assert before <= datetime.strptime(stamp, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc) <= after
    assert edited["created_date"] == created["created_date"]


def test_a_refused_edit_leaves_the_task_file_byte_identical(tmp_path: Path) -> None:
    built = board({"validate": HOOK}, tmp_path)
    task = built.create("Draw the board", {}).output
    held = _snapshot(tmp_path)

    written = built.edit(task, {"plan": REFUSE}, "")

    assert written == Written(False, "the hook refused it")
    assert _snapshot(tmp_path) == held
    name, before, after = CALLS[-1]
    assert name in held and before == held[name].decode() and REFUSE in after


def test_a_refused_create_writes_no_file_and_leaves_its_id_free(tmp_path: Path) -> None:
    built = board({"validate": HOOK}, tmp_path)

    refused = built.create("Draw the board", {"description": REFUSE})
    made = built.create("Draw the board", {})

    assert refused == Written(False, "the hook refused it")
    assert CALLS[0][1] is None
    assert made.output == "task-1"
    assert [path.name for path in _tasks(tmp_path).iterdir()] == ["task-1 - Draw-the-board.md"]


def test_a_validate_setting_that_names_no_function_is_refused_when_the_board_loads(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no_such_hook"):
        board({"validate": f"{__name__}:no_such_hook"}, tmp_path)
