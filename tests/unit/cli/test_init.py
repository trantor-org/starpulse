"""`starpulse init`: a first install is scaffolded with every file the quick start needs, and each file loads."""

import json
from pathlib import Path

import pytest
import yaml
from starpulse.cli import init
from starpulse.machine_engine.adapters.machine_loader import load_machine
from starpulse.machine_engine.model.transitions import lane_id
from starpulse.runtime.config import load


def test_init_writes_a_config_the_server_loads(tmp_path: Path) -> None:
    assert init.main(["--dir", str(tmp_path)]) == 0

    config = load(tmp_path / "starpulse.toml")

    assert [producer.name for producer in config.producers] == ["claude-code"]
    assert config.producers[0].token_env == "STARPULSE_TOKEN"
    assert config.board["guards"], "the config declares [[board.guards]]"
    assert config.scheduler is not None


def test_init_writes_a_machine_that_declares_its_roles(tmp_path: Path) -> None:
    init.main(["--dir", str(tmp_path)])

    compiled = load_machine(tmp_path / "board.yaml")

    assert set(compiled.roles.values()) >= {"resting", "waiting_on_person"}
    assert None not in compiled.roles.values()


def test_init_writes_board_lanes_that_are_the_machines_states(tmp_path: Path) -> None:
    init.main(["--dir", str(tmp_path)])

    statuses = yaml.safe_load((tmp_path / ".starpulse" / "board" / "config.yml").read_text())["statuses"]

    assert [lane_id(status) for status in statuses] == list(load_machine(tmp_path / "board.yaml").roles)


def test_init_writes_a_tasks_directory_a_task_can_be_created_in(tmp_path: Path) -> None:
    init.main(["--dir", str(tmp_path)])

    assert (tmp_path / ".starpulse" / "board" / "tasks").is_dir()


def test_init_writes_the_claude_code_telemetry_settings(tmp_path: Path) -> None:
    init.main(["--dir", str(tmp_path), "--harness", "claude-code"])

    env = json.loads((tmp_path / ".claude" / "settings.json").read_text())["env"]

    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"].startswith("http://127.0.0.1:")


def test_init_refuses_to_overwrite_and_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "starpulse.toml").write_text("# mine\n")

    assert init.main(["--dir", str(tmp_path)]) == 1

    assert "starpulse.toml" in capsys.readouterr().err
    assert (tmp_path / "starpulse.toml").read_text() == "# mine\n"
    assert not (tmp_path / "board.yaml").exists()
