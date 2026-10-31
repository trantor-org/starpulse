"""The one-shot backfill copies each task file's last claim marker into the frontmatter `assignee` field."""

from pathlib import Path

import yaml
from starpulse.board.adapters.claim_backfill import backfill

_TASK = "---\nid: task-{n}\ntitle: T\nstatus: {status}\nupdated_date: 2026-10-01 10:00\n{extra}---\n\n{notes}\n"
_NOTES = "<!-- SECTION:NOTES:BEGIN -->\n{text}\n<!-- SECTION:NOTES:END -->"


def _write(root: Path, folder: str, n: int, text: str, extra: str = "") -> Path:
    path = root / folder / f"task-{n} - T.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TASK.format(n=n, status="Done", extra=extra, notes=_NOTES.format(text=text)))
    return path


def _front(path: Path) -> dict:
    return yaml.safe_load(path.read_text().split("---\n")[1])


def test_the_last_marker_of_each_folders_file_becomes_the_assignee_and_the_notes_keep_it(tmp_path: Path) -> None:
    tasks = _write(tmp_path, "tasks", 1, "**Assignee:** https://claude.ai/x\n**Assignee:** s-1")
    done = _write(tmp_path, "completed", 2, "**Assignee:** s-2")
    archived = _write(tmp_path, "archive/tasks", 3, "**Assignee:** s-3")

    assert backfill(tmp_path) == 3

    assert [_front(path)["assignee"] for path in (tasks, done, archived)] == ["s-1", "s-2", "s-3"]
    assert "**Assignee:** s-1" in tasks.read_text()


def test_a_released_from_marker_becomes_released_from(tmp_path: Path) -> None:
    path = _write(tmp_path, "tasks", 1, "**Released from:** s-1")

    backfill(tmp_path)

    assert _front(path)["released_from"] == "s-1"
    assert "assignee" not in _front(path)


def test_a_field_already_set_and_a_markerless_task_are_left_alone(tmp_path: Path) -> None:
    held = _write(tmp_path, "tasks", 1, "**Assignee:** s-old", extra="assignee: s-new\n")
    plain = _write(tmp_path, "tasks", 2, "plain note")
    before = plain.read_text()

    assert backfill(tmp_path) == 0

    assert _front(held)["assignee"] == "s-new"
    assert plain.read_text() == before


def test_the_backfill_keeps_the_updated_date(tmp_path: Path) -> None:
    path = _write(tmp_path, "tasks", 1, "**Assignee:** s-1")

    backfill(tmp_path)

    assert str(_front(path)["updated_date"]) == "2026-10-01 10:00"


def test_a_second_run_changes_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "tasks", 1, "**Assignee:** s-1")
    assert backfill(tmp_path) == 1

    assert backfill(tmp_path) == 0
