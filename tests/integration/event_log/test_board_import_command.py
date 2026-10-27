"""`starpulse import-board` imports a native board and its recorded runs and verifies every Task by replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starpulse.event_log import lane_import
from starpulse.event_log.event_log import EventLog
from starpulse.flow_metrics.adapters.outbound.history import HistoryStore
from starpulse.runtime import board_import

from tests.machines import MACHINES


def _project(tmp_path: Path) -> Path:
    tasks = tmp_path / "board" / "tasks"
    tasks.mkdir(parents=True)
    (tmp_path / "board" / "config.yml").write_text("project_name: demo\nstatuses: [To Do, Done]\ntask_prefix: task\n")
    (tasks / "task-1 - Cut over.md").write_text("---\nid: TASK-1\ntitle: Cut over\nstatus: Done\n---\n")
    config = tmp_path / "starpulse.toml"
    config.write_text(
        f'database_url = "sqlite:///{tmp_path / "store.sqlite"}"\n[board]\ntype = "native"\npath = "board"\n'
    )
    history = HistoryStore(f"sqlite:///{tmp_path / 'store.sqlite'}", MACHINES)
    history.import_lanes(
        [lane_import.Change("l1", "TASK-1", "To Do", 10.0), lane_import.Change("l2", "TASK-1", "Done", 20.0)]
    )
    run = {"workflow": "ci", "run_id": "7", "event": "StepStarted", "step": "lint", "time": 5.0}
    EventLog(f"sqlite:///{tmp_path / 'store.sqlite'}").publish("runs:events", run, event_id="r1")
    return config


def test_the_command_reports_every_task_equal_and_a_second_run_imports_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--config", str(_project(tmp_path))]

    assert board_import.main(argv) == 0
    first = json.loads(capsys.readouterr().out)
    assert board_import.main(argv) == 0
    second = json.loads(capsys.readouterr().out)

    assert (first["tasks"], first["imported"], first["equal"], first["runs_imported"], first["verified"]) == (
        1,
        1,
        1,
        1,
        True,
    )
    assert (second["imported"], second["runs_imported"], second["equal"]) == (0, 0, 1)


def test_a_dry_run_verifies_and_leaves_the_real_store_unimported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["--config", str(_project(tmp_path))]

    assert board_import.main([*argv, "--dry-run"]) == 0
    dry = json.loads(capsys.readouterr().out)
    assert board_import.main(argv) == 0
    real = json.loads(capsys.readouterr().out)

    assert (dry["imported"], dry["verified"]) == (1, True)
    assert real["imported"] == 1
