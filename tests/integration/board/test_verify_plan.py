"""A task's `verify_plan` front matter list on the native board: a `verifyPlan` edit writes it and the record reads it."""

import json
from pathlib import Path

import pytest
import yaml
from starpulse.board.adapters import native
from starpulse.board.adapters.upstream_backlog import _split
from starpulse.board.model.seam import Board
from tests.integration.cli.test_agent_cli import _run, _task_file, tasked  # noqa: F401

STATUSES = ["Ready", "In Progress", "Review", "Done"]
TASK = """---
id: task-1
title: Plan it
status: Ready
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Plan it.
<!-- SECTION:DESCRIPTION:END -->
"""


@pytest.fixture
def served(tmp_path: Path) -> tuple[Board, Path]:
    root = tmp_path / ".starpulse" / "board"
    (root / "tasks").mkdir(parents=True)
    (root / "config.yml").write_text(
        yaml.safe_dump({"project_name": "trantor", "statuses": STATUSES, "task_prefix": "task"})
    )
    path = root / "tasks" / "task-1 - Plan-it.md"
    path.write_text(TASK)
    return native.board({}, tmp_path), path


def test_verify_plan_list_writes_the_front_matter_key_and_the_record_reads_it(served: tuple[Board, Path]) -> None:
    built, path = served
    assert built.edit is not None and built.read is not None

    written = built.edit("task-1", {"verifyPlan": ["make check", " uv run agent-cmd lint "]}, "")

    assert written.ok, written.output
    assert _split(path.read_text())[0]["verify_plan"] == ["make check", "uv run agent-cmd lint"]
    assert (built.read("task-1") or {})["verifyPlan"] == ["make check", "uv run agent-cmd lint"]


def test_verify_plan_empty_removes_the_key_and_a_task_without_a_plan_reads_unchanged(
    served: tuple[Board, Path],
) -> None:
    built, path = served
    assert built.edit is not None and built.read is not None
    built.edit("task-1", {"verifyPlan": ["make check"]}, "")

    written = built.edit("task-1", {"verifyPlan": []}, "")

    assert written.ok, written.output
    assert "verify_plan" not in _split(path.read_text())[0]
    assert (built.read("task-1") or {})["verifyPlan"] == []


def test_task_edit_verify_plan_flags_write_and_drop_a_criterions_entries_on_the_server(
    tasked: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def edit(*flags: str) -> tuple[int, dict]:
        return _run(capsys, ["task", "edit", "task-1", *flags, "--server", tasked])

    code, doc = edit("--verify-plan", "1: make check", "--verify-plan", "2: uv run agent-cmd lint")
    assert (code, doc["changed"]) == (0, ["verifyPlan"])
    assert _split(_task_file(tmp_path).read_text())[0]["verify_plan"] == ["1: make check", "2: uv run agent-cmd lint"]

    code, doc = edit("--remove-verify-plan", "1", "--verify-plan", "1: make test")
    assert code == 0
    assert _split(_task_file(tmp_path).read_text())[0]["verify_plan"] == ["2: uv run agent-cmd lint", "1: make test"]

    code, doc = edit("--remove-verify-plan", "9")
    assert code != 0
    assert "no entry for criterion 9" in json.dumps(doc)
