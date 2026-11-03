"""A task's `aliases` are other ids it answers to: a lookup by an alias finds the task, and a new id never reuses one."""

from pathlib import Path

import yaml
from starpulse.board.adapters import native
from starpulse.board.model.seam import Board


def _write(base: Path, name: str, task_id: str, aliases: str = "") -> None:
    path = base / ".starpulse" / "board" / "tasks" / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {task_id}\ntitle: Title of {task_id}\nstatus: To Do\n{aliases}---\n\n## Description\n")


FIXTURE = Path(__file__).parents[2] / "fixtures" / "machines" / "proposed-board.yaml"
STATUSES = ["New", "Proposed", "Ready", "Waiting", "In Progress", "Done", "Archived"]


def _board(base: Path) -> Board:
    """A native board over `proposed-board.yaml` that numbers proposals `PROP-N`."""
    (base / "board.yaml").write_text(FIXTURE.read_text())
    (base / ".starpulse" / "board" / "config.yml").write_text(
        yaml.safe_dump({"project_name": "demo", "statuses": STATUSES, "task_prefix": "TASK"})
    )
    return native.board({"machine": "board.yaml", "proposal_prefix": "PROP"}, base)


def _title(built: Board, task: str) -> str | None:
    assert built.read is not None
    return (built.read(task) or {}).get("title")


def test_a_lookup_by_an_alias_finds_the_task_and_a_longer_id_does_not(tmp_path: Path) -> None:
    _write(tmp_path, "prop-3 - Idea", "PROP-3", "aliases:\n- TASK-12\n")
    built = _board(tmp_path)

    assert _title(built, "TASK-12") == "Title of PROP-3"
    assert _title(built, "task-12") == "Title of PROP-3"  # any case
    assert _title(built, "PROP-3") == "Title of PROP-3"
    assert _title(built, "TASK-1") is None
    assert _title(built, "TASK-120") is None


def test_a_new_id_never_reuses_an_alias(tmp_path: Path) -> None:
    _write(tmp_path, "prop-3 - Idea", "PROP-3", "aliases:\n- TASK-12\n")
    _write(tmp_path, "task-9 - Work", "TASK-9", "aliases:\n- PROP-7\n")
    built = _board(tmp_path)
    assert built.create is not None

    assert built.create("Next work", {}).output == "TASK-13"
    assert built.create("Next idea", {"status": "Proposed"}).output == "PROP-8"
